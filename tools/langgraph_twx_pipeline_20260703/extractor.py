from __future__ import annotations

import html
import os
import re
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


REFERENCE_TAGS = {"attachedprocessid", "attachedactivityid", "sourcenodeid", "targetnodeid", "flowid"}
REFERENCE_ATTRS = {
    "id",
    "guid",
    "ref",
    "flowref",
    "sourceref",
    "targetref",
    "processref",
    "serviceref",
    "coachviewref",
}


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def _lname(elem: ET.Element) -> str:
    return _strip_ns(elem.tag).lower()


def _norm_ref(value: str) -> str:
    return value.strip().strip("/")


def extract_twx(twx_path: str, extract_dir: Optional[str] = None) -> str:
    if not os.path.isfile(twx_path):
        raise FileNotFoundError(f"TWX no encontrado: {twx_path}")

    out = extract_dir or tempfile.mkdtemp(prefix="twx_extract_")
    os.makedirs(out, exist_ok=True)
    out_path = Path(out).resolve()

    with zipfile.ZipFile(twx_path, "r") as zf:
        for member in zf.infolist():
            raw_name = member.filename
            if not raw_name or raw_name.endswith("/"):
                continue
            dest = (out_path / raw_name).resolve()
            if not str(dest).startswith(str(out_path)):
                raise ValueError(f"Ruta insegura en ZIP (zip-slip): {raw_name}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member, "r") as src, open(dest, "wb") as dst:
                dst.write(src.read())

    return str(out_path)


def parse_manifest(extracted_dir: str) -> Tuple[Dict[str, Any], List[str]]:
    manifest_path = os.path.join(extracted_dir, "manifest.xml")
    warnings: List[str] = []
    result: Dict[str, Any] = {
        "process_name": None,
        "environment_variables": {},
        "environment_overrides": {},
        "metadata": {"manifest_path": manifest_path},
    }
    if not os.path.isfile(manifest_path):
        warnings.append("manifest.xml no encontrado")
        return result, warnings

    try:
        tree = ET.parse(manifest_path)
        root = tree.getroot()
    except Exception as ex:
        warnings.append(f"Error parseando manifest.xml: {ex}")
        return result, warnings

    process_name = None
    env_defaults: Dict[str, str] = {}
    env_overrides: Dict[str, List[Dict[str, str]]] = {}

    for e in root.iter():
        ln = _lname(e)
        txt = (e.text or "").strip()
        if not process_name and ln in {"name", "displayname", "processname"} and txt:
            process_name = txt

        if ln in {"environmentvariable", "variable"}:
            entry = _parse_env_var_entry(e)
            if entry.get("name"):
                var_name = entry["name"]
                if entry.get("default") is not None:
                    env_defaults[var_name] = entry["default"]
                for ov in entry.get("overrides", []):
                    env_overrides.setdefault(var_name, []).append(ov)

    result["process_name"] = process_name
    result["environment_variables"] = env_defaults
    result["environment_overrides"] = env_overrides
    return result, warnings


def parse_xml_artifacts_recursive(extracted_dir: str) -> Tuple[Dict[str, Any], List[str]]:
    artifacts: Dict[str, Any] = {}
    warnings: List[str] = []

    for root_dir, _, files in os.walk(extracted_dir):
        for fn in files:
            if not fn.lower().endswith(".xml"):
                continue
            path = os.path.join(root_dir, fn)
            try:
                tree = ET.parse(path)
                xroot = tree.getroot()
                artifact = _catalog_artifact(xroot, path, extracted_dir)
                aid = artifact["artifact_id"]
                if aid in artifacts:
                    alt_id = f"{aid}::{Path(path).name}"
                    artifact["artifact_id"] = alt_id
                    warnings.append(f"Colisión artifact_id '{aid}', renombrado a '{alt_id}'")
                    aid = alt_id
                artifacts[aid] = artifact
            except Exception as ex:
                rel = os.path.relpath(path, extracted_dir)
                warnings.append(f"Error parseando XML '{rel}': {ex}")

    return artifacts, warnings


def _catalog_artifact(root: ET.Element, source_file: str, extracted_dir: str) -> Dict[str, Any]:
    rel = os.path.relpath(source_file, extracted_dir)
    artifact_id = _first_attr(root, ("id", "guid")) or os.path.splitext(os.path.basename(source_file))[0]
    name = _find_first_text(root, ("name", "displayname", "label")) or artifact_id
    artifact_type = _infer_artifact_type(root)

    tags = sorted({_lname(e) for e in root.iter()})
    refs = _extract_references(root)
    snippets = _collect_text_snippets(root, limit=25, min_len=3)
    analysis = _extract_analysis(root)

    process_model = None
    if artifact_type == "process":
        process_model = _extract_process_model(root, artifact_id, name)

    return {
        "artifact_id": _norm_ref(artifact_id),
        "name": name,
        "artifact_type": artifact_type,
        "source_file": rel,
        "tags": tags,
        "references": refs,
        "text_snippets": snippets,
        "analysis": analysis,
        "process_model": process_model,
    }


def _infer_artifact_type(root: ET.Element) -> str:
    tags = {_lname(e) for e in root.iter()}
    text_blob = " ".join((e.text or "") for e in root.iter()).lower()
    source_name = (_find_first_text(root, ("name",)) or "").lower()

    if "manifest" in tags:
        return "manifest"
    if "bpd" in tags or "businessprocessdiagram" in tags or "process" in tags:
        return "process"
    if "coach" in tags or "coachview" in tags or "boundaryevent" in tags:
        return "coach_ui"
    if "undercover" in text_blob or "uca" in text_blob or "schedevent" in tags:
        return "uca_bus"
    if "gateway" in text_blob or "conditionexpression" in tags:
        return "gateway_or_rules"
    if "processtype" in tags or "service" in source_name:
        return "service"
    return "artifact"


def _extract_references(root: ET.Element) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {
        "attachedProcessId": [],
        "attachedActivityId": [],
        "sourceNodeId": [],
        "targetNodeId": [],
        "flowId": [],
        "attributes": [],
    }

    for e in root.iter():
        ln = _lname(e)
        text = (e.text or "").strip()
        if ln in REFERENCE_TAGS and text:
            key = {
                "attachedprocessid": "attachedProcessId",
                "attachedactivityid": "attachedActivityId",
                "sourcenodeid": "sourceNodeId",
                "targetnodeid": "targetNodeId",
                "flowid": "flowId",
            }[ln]
            out[key].append(_norm_ref(text))

        for ak, av in e.attrib.items():
            if not av:
                continue
            lka = ak.lower()
            if lka in REFERENCE_ATTRS:
                out["attributes"].append(f"{lka}:{_norm_ref(av)}")
            if lka in {"flowref", "ref"}:
                out["flowId"].append(_norm_ref(av))

    for k in out:
        seen = set()
        ordered = []
        for v in out[k]:
            if v not in seen:
                ordered.append(v)
                seen.add(v)
        out[k] = ordered
    return out


def _collect_text_snippets(root: ET.Element, limit: int = 25, min_len: int = 3) -> List[str]:
    snippets: List[str] = []
    for e in root.iter():
        t = (e.text or "").strip()
        if len(t) >= min_len and t not in snippets:
            snippets.append(t)
            if len(snippets) >= limit:
                break
    return snippets


def _extract_analysis(root: ET.Element) -> Dict[str, Any]:
    params: List[str] = []
    actions: List[str] = []
    conditions: List[str] = []
    visibility_rules: List[str] = []
    env_refs: List[str] = []
    id_candidate_values: List[str] = []
    subprocess_values: List[str] = []

    for e in root.iter():
        ln = _lname(e)
        txt = (e.text or "").strip()

        if ln in {"bpdparameter", "processparameter"}:
            pname = (e.attrib.get("name") or "").strip()
            if pname:
                params.append(pname)

        if ln in {"name", "eventlabel"} and txt and _looks_action_or_ui_name(txt):
            actions.append(txt)

        if ln in {"expression", "condition"} and txt:
            conditions.append(" ".join(txt.split()))

        if ln == "script" and txt:
            script = txt
            for m in re.finditer(r"tw\.env\.[A-Z0-9_]+", script):
                env_refs.append(m.group(0))
            for m in re.finditer(r"tw\.local\.([A-Za-z0-9_\.]+)\s*=\s*([^;\n]+)", script, flags=re.IGNORECASE):
                var = m.group(1).strip()
                val = m.group(2).strip()
                if var.lower().startswith("id") or ".id" in var.lower():
                    id_candidate_values.append(val)
                if "subproceso" in var.lower():
                    subprocess_values.append(val)

        if txt and ("VisibilityRules" in txt or "visibility.VisibilityRules" in txt):
            decoded = html.unescape(txt)
            vars_found = re.findall(r'"var":"([^"]+)"', decoded)
            actions_found = re.findall(r'"action":"([^"]+)"', decoded)
            if vars_found or actions_found:
                vars_text = ", ".join(_dedupe(vars_found)[:4]) or "N/A"
                act_text = ", ".join(_dedupe(actions_found)[:3]) or "N/A"
                visibility_rules.append(f"vars=[{vars_text}] action=[{act_text}]")

    return {
        "parameters": _dedupe(params)[:120],
        "actions": _dedupe(actions)[:80],
        "conditions": _dedupe(conditions)[:120],
        "visibility_rules": _dedupe(visibility_rules)[:30],
        "env_refs": _dedupe(env_refs)[:120],
        "id_candidate_values": _dedupe(id_candidate_values)[:60],
        "subprocess_values": _dedupe(subprocess_values)[:60],
    }


def _extract_process_model(root: ET.Element, artifact_id: str, artifact_name: str) -> Dict[str, Any]:
    bpd = _first(root.iterfind(".//BusinessProcessDiagram"), None)
    if bpd is None:
        for e in root.iter():
            if _lname(e) == "businessprocessdiagram":
                bpd = e
                break

    if bpd is None:
        return {
            "process_id": _norm_ref(artifact_id),
            "process_name": artifact_name,
            "nodes": [],
            "flows": [],
            "entry_nodes": [],
            "exit_nodes": [],
            "evidence_refs": [],
        }

    flow_defs = _extract_flow_defs(bpd)
    node_defs = _extract_flowobject_defs(bpd)
    _bind_flows_to_nodes(flow_defs, node_defs)
    _infer_entry_exit_nodes(node_defs)

    mappings = []
    assignments = []
    conditions = []
    ui_rules = []
    call_sites = []
    for node in node_defs.values():
        mappings.extend(node.get("mappings", []))
        assignments.extend(node.get("assignments", []))
        conditions.extend(node.get("conditions", []))
        ui_rules.extend(node.get("ui_rules", []))
        if node.get("attached_process_id"):
            call_sites.append(
                {
                    "node_id": node["node_id"],
                    "attached_process_id": node["attached_process_id"],
                    "input_mappings": [m for m in node.get("mappings", []) if m.get("direction") == "input"],
                    "output_mappings": [m for m in node.get("mappings", []) if m.get("direction") == "output"],
                }
            )

    evidence_refs = []
    for nd in node_defs.values():
        evidence_refs.append(
            {
                "xml_locator": f"flowObject[{nd['node_id']}]",
                "snippet": nd.get("name", ""),
                "relation_type": "node",
            }
        )
    for fd in flow_defs.values():
        evidence_refs.append(
            {
                "xml_locator": f"flow[{fd['flow_id']}]",
                "snippet": fd.get("name", ""),
                "relation_type": "flow",
            }
        )

    return {
        "process_id": _norm_ref(artifact_id),
        "process_name": artifact_name,
        "nodes": list(node_defs.values()),
        "flows": list(flow_defs.values()),
        "entry_nodes": [n["node_id"] for n in node_defs.values() if n.get("is_entry")],
        "exit_nodes": [n["node_id"] for n in node_defs.values() if n.get("is_exit")],
        "mappings": _dedupe_dict_objects(mappings, ("node_id", "direction", "name", "value")),
        "assignments": _dedupe_dict_objects(assignments, ("node_id", "var", "value")),
        "conditions": _dedupe_dict_objects(conditions, ("node_id", "expression")),
        "ui_rules": _dedupe_dict_objects(ui_rules, ("node_id", "control", "var", "operand", "action")),
        "call_sites": call_sites,
        "evidence_refs": evidence_refs[:400],
    }


def _extract_flow_defs(bpd: ET.Element) -> Dict[str, Dict[str, Any]]:
    flow_defs: Dict[str, Dict[str, Any]] = {}
    for f in bpd.iter():
        if _lname(f) != "flow":
            continue
        fid = _norm_ref(f.attrib.get("id", ""))
        if not fid:
            continue
        condition_ref = ""
        condition_expr = ""
        for c in f.iter():
            if _lname(c) == "condition":
                condition_ref = _norm_ref(c.attrib.get("id", "") or (c.text or ""))
                expr = _find_first_text(c, ("expression",))
                if expr:
                    condition_expr = " ".join(expr.split())
                break
        flow_defs[fid] = {
            "flow_id": fid,
            "name": _find_first_text(f, ("name",)) or "",
            "connection_type": (f.attrib.get("connectionType") or "").strip(),
            "source_node_id": "",
            "target_node_id": "",
            "condition_ref": condition_ref,
            "condition_expression": condition_expr,
            "evidence": {"flow_id": fid},
        }
    return flow_defs


def _extract_flowobject_defs(bpd: ET.Element) -> Dict[str, Dict[str, Any]]:
    nodes: Dict[str, Dict[str, Any]] = {}
    for fo in bpd.iter():
        if _lname(fo) != "flowobject":
            continue
        nid = _norm_ref(fo.attrib.get("id", ""))
        if not nid:
            continue

        component_type = (fo.attrib.get("componentType") or "").strip() or "Unknown"
        name = _find_first_text(fo, ("name",)) or nid
        component = _first(fo.iterfind("./component"), None)
        if component is None:
            for x in fo:
                if _lname(x) == "component":
                    component = x
                    break

        attached_process_id = ""
        attached_activity_id = ""
        implementation_type = ""
        gateway_type = ""
        split_join_type = ""
        event_type = ""
        scripts: List[str] = []
        mappings: List[Dict[str, Any]] = []
        assignments: List[Dict[str, Any]] = []
        conditions: List[Dict[str, Any]] = []
        ui_rules: List[Dict[str, Any]] = []
        in_flows: List[str] = []
        out_flows: List[str] = []

        if component is not None:
            implementation_type = _find_first_text(component, ("implementationtype",)) or ""
            gateway_type = _find_first_text(component, ("gatewaytype",)) or ""
            split_join_type = _find_first_text(component, ("splitjointype",)) or ""
            event_type = _find_first_text(component, ("eventtype",)) or ""

            for impl in component.iter():
                ln = _lname(impl)
                txt = (impl.text or "").strip()
                if ln == "attachedprocessid" and txt:
                    attached_process_id = _norm_ref(txt)
                elif ln == "attachedactivityid" and txt:
                    attached_activity_id = _norm_ref(txt)
                elif ln == "script" and txt:
                    scripts.append(txt)
                elif ln in {"inputprocessparametermapping", "outputprocessparametermapping", "inputactivityparametermapping", "outputactivityparametermapping"}:
                    map_name = _find_first_text(impl, ("name",)) or ""
                    map_value = _find_first_text(impl, ("value",)) or ""
                    direction = "input" if ln.startswith("input") else "output"
                    mappings.append(
                        {
                            "node_id": nid,
                            "direction": direction,
                            "name": map_name,
                            "value": map_value,
                            "mapping_type": ln,
                            "evidence": {"node_id": nid, "mapping_tag": ln},
                        }
                    )

        for script in scripts:
            assignments.extend(_extract_assignments_from_script(script, nid))
            conds = _extract_condition_expressions(script, nid)
            conditions.extend(conds)
            ui_rules.extend(_extract_ui_rules(script, nid))

        # Algunas reglas de visibilidad vienen doble-escapadas en valores XML, no en <script>.
        for txt in fo.itertext():
            t = (txt or "").strip()
            if not t:
                continue
            if "VisibilityRules" in t or "visibility.VisibilityRules" in t:
                ui_rules.extend(_extract_ui_rules(t, nid))

        for p in fo:
            ln = _lname(p)
            if ln not in {"inputport", "outputport"}:
                continue
            port_is_input = ln == "inputport"
            for z in p.iter():
                if _lname(z) != "flow":
                    continue
                flow_ref = _norm_ref(z.attrib.get("ref", "") or (z.text or ""))
                if not flow_ref:
                    continue
                if port_is_input:
                    in_flows.append(flow_ref)
                else:
                    out_flows.append(flow_ref)

        node_type, node_subtype = _classify_node_type(
            component_type=component_type,
            implementation_type=implementation_type,
            attached_process_id=attached_process_id,
            attached_activity_id=attached_activity_id,
            gateway_type=gateway_type,
            event_type=event_type,
        )

        nodes[nid] = {
            "node_id": nid,
            "name": name,
            "component_type": component_type,
            "node_type": node_type,
            "node_subtype": node_subtype,
            "implementation_type": implementation_type,
            "gateway_type": gateway_type,
            "split_join_type": split_join_type,
            "event_type": event_type,
            "attached_process_id": attached_process_id,
            "attached_activity_id": attached_activity_id,
            "incoming_flow_ids": _dedupe(in_flows),
            "outgoing_flow_ids": _dedupe(out_flows),
            "mappings": mappings,
            "assignments": assignments,
            "conditions": conditions,
            "ui_rules": ui_rules,
            "scripts": scripts[:6],
            "is_user_action_candidate": node_type == "activity" and node_subtype in {"human_task", "coach_task"},
            "is_entry": False,
            "is_exit": False,
        }
    return nodes


def _bind_flows_to_nodes(flow_defs: Dict[str, Dict[str, Any]], node_defs: Dict[str, Dict[str, Any]]) -> None:
    for node in node_defs.values():
        nid = node["node_id"]
        for fid in node.get("outgoing_flow_ids", []):
            if fid in flow_defs:
                flow_defs[fid]["source_node_id"] = nid
        for fid in node.get("incoming_flow_ids", []):
            if fid in flow_defs:
                flow_defs[fid]["target_node_id"] = nid

    incoming = {nid: 0 for nid in node_defs}
    outgoing = {nid: 0 for nid in node_defs}
    for fd in flow_defs.values():
        s = fd.get("source_node_id")
        t = fd.get("target_node_id")
        if s in outgoing:
            outgoing[s] += 1
        if t in incoming:
            incoming[t] += 1
    for nid, node in node_defs.items():
        node["incoming_count"] = incoming.get(nid, 0)
        node["outgoing_count"] = outgoing.get(nid, 0)


def _infer_entry_exit_nodes(node_defs: Dict[str, Dict[str, Any]]) -> None:
    for node in node_defs.values():
        node["is_entry"] = node.get("incoming_count", 0) == 0
        node["is_exit"] = node.get("outgoing_count", 0) == 0


def _classify_node_type(
    component_type: str,
    implementation_type: str,
    attached_process_id: str,
    attached_activity_id: str,
    gateway_type: str,
    event_type: str,
) -> Tuple[str, str]:
    ct = component_type.lower()
    if ct == "gateway":
        return "gateway", gateway_type or "gateway"
    if ct == "event":
        return "event", event_type or "event"

    if attached_process_id:
        return "activity", "call_activity"
    if attached_activity_id:
        if implementation_type == "1":
            return "activity", "human_task"
        if implementation_type == "2":
            return "activity", "service_call"
        return "activity", "activity_ref"

    if implementation_type == "3":
        return "activity", "script_task"
    if implementation_type == "2":
        return "activity", "service_task"
    return "activity", "generic_activity"


def _extract_assignments_from_script(script: str, node_id: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for m in re.finditer(r"(tw\.(?:local|env)\.[A-Za-z0-9_\.]+)\s*=\s*([^;\n]+)", script):
        out.append(
            {
                "node_id": node_id,
                "var": m.group(1).strip(),
                "value": m.group(2).strip(),
                "evidence": {"node_id": node_id, "snippet": m.group(0).strip()},
            }
        )
    return _dedupe_dict_objects(out, ("node_id", "var", "value"))[:120]


def _extract_condition_expressions(script: str, node_id: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for m in re.finditer(r"if\s*\((.*?)\)", script, flags=re.DOTALL):
        expr = " ".join(m.group(1).split())
        if expr:
            out.append({"node_id": node_id, "expression": expr, "evidence": {"node_id": node_id, "snippet": m.group(0)[:220]}})
    return _dedupe_dict_objects(out, ("node_id", "expression"))[:80]


def _extract_ui_rules(script: str, node_id: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if "VisibilityRules" not in script and "visibility.VisibilityRules" not in script:
        return out
    decoded = html.unescape(html.unescape(script))
    for m in re.finditer(r'"var":"([^"]+)".*?"operand":"([^"]+)".*?"action":"([^"]+)".*?(?:"control":"([^"]+)")?', decoded, flags=re.DOTALL):
        out.append(
            {
                "node_id": node_id,
                "control": (m.group(4) or "").strip(),
                "var": m.group(1).strip(),
                "operand": m.group(2).strip(),
                "action": m.group(3).strip(),
                "evidence": {"node_id": node_id, "snippet": m.group(0)[:260]},
            }
        )
    return _dedupe_dict_objects(out, ("node_id", "control", "var", "operand", "action"))[:120]


def _parse_env_var_entry(e: ET.Element) -> Dict[str, Any]:
    name = ""
    default = None
    overrides: List[Dict[str, str]] = []
    env_name_hint = ""
    for c in e.iter():
        ln = _lname(c)
        txt = (c.text or "").strip()
        if not txt:
            continue
        if ln in {"name", "key"} and not name:
            name = txt
        elif ln in {"defaultvalue", "value"} and default is None:
            default = txt
        elif ln in {"environment", "profile", "configuration", "executionprofile"}:
            env_name_hint = txt
        elif ln in {"override", "environmentvalue", "profilevalue"}:
            ov_name = env_name_hint or c.attrib.get("environment") or c.attrib.get("profile") or ""
            ov_val = txt
            overrides.append({"environment": ov_name.strip(), "value": ov_val.strip()})

    if not overrides and env_name_hint and default is not None:
        # En algunos exportes la variante aparece en sibling tags sin nodo explícito override.
        # Aquí no asumimos que sea un override real; se conserva en blanco para evitar inventar.
        pass

    return {"name": name, "default": default, "overrides": _dedupe_dict_objects(overrides, ("environment", "value"))}


def _looks_action_or_ui_name(value: str) -> bool:
    t = value.strip()
    if len(t) < 3 or len(t) > 120:
        return False
    lt = t.lower()
    if re.fullmatch(r"[0-9a-f.\-]{8,}", lt):
        return False
    keywords = (
        "repro",
        "rechaz",
        "generar",
        "actualiz",
        "continu",
        "enviar",
        "acreditar",
        "movimiento",
        "archivo",
        "revisi",
        "consult",
        "confirm",
        "autoriza",
        "calcular",
    )
    return any(k in lt for k in keywords)


def _dedupe(items: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in items:
        key = item.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _dedupe_dict_objects(items: List[Dict[str, Any]], keys: Tuple[str, ...]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()
    for item in items:
        sig = tuple((item.get(k) or "").strip() if isinstance(item.get(k), str) else str(item.get(k) or "") for k in keys)
        if sig in seen:
            continue
        seen.add(sig)
        out.append(item)
    return out


def _first(it: Any, default: Any = None) -> Any:
    for x in it:
        return x
    return default


def _first_attr(root: ET.Element, attrs: tuple[str, ...]) -> Optional[str]:
    for e in root.iter():
        for a in attrs:
            if a in e.attrib and e.attrib[a]:
                return e.attrib[a]
    return None


def _find_first_text(root: ET.Element, names: tuple[str, ...]) -> Optional[str]:
    names_set = {n.lower() for n in names}
    for e in root.iter():
        if _lname(e) in names_set:
            t = (e.text or "").strip()
            if t:
                return t
    return None
