from __future__ import annotations

import copy
import re
import unicodedata
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Set, Tuple
import networkx as nx


CONF_CORROBORADA = "CORROBORADA"
CONF_INFERIDA = "INFERIDA CON EVIDENCIA"
CONF_AMBIGUA = "AMBIGUA"
CONF_NO_LOCALIZADA = "NO LOCALIZADA"


def build_functional_model(state: Dict[str, Any]) -> Dict[str, Any]:
    artifacts: Dict[str, Any] = state.get("artifacts", {}) or {}
    manifest = state.get("manifest", {}) or {}
    root_id = state.get("root_id")
    cfgs = (state.get("control_flow_graphs") or {}).get("nodes")
    if cfgs is None:
        # compatibilidad defensiva cuando viene dict serializado
        cfgs = state.get("control_flow_graphs", {})

    process_models = _collect_process_models(artifacts)
    if not process_models:
        return _empty_model(manifest.get("process_name") or "Proceso TWX")

    if not root_id or root_id not in process_models:
        root_id = _pick_root(process_models, manifest.get("process_name", ""))

    cfg_index = _build_cfg_index(process_models)
    call_index = _build_call_index(process_models)
    nearest_a_cache: Dict[Tuple[str, str], Optional[str]] = {}

    traversal = _traverse_contextual(root_id, cfg_index, call_index)
    lineage_graph = traversal["lineage_graph"]
    traces = traversal["traces"]
    ambiguities = traversal["ambiguities"]
    loop_patterns = traversal["loop_patterns"]
    evidence_index = traversal["evidence_index"]

    scope_meta = _classify_scope(process_models, traces, cfg_index, call_index, root_id)
    stage_index = _build_functional_stages(process_models, traces, scope_meta, nearest_a_cache, cfg_index, root_id)
    transitions, decisions = _build_transitions_and_decisions(stage_index, traces, cfg_index, nearest_a_cache, ambiguities)
    id_resolutions = _resolve_functional_ids(process_models, lineage_graph, traces, manifest, evidence_index)
    contexts = _collect_contexts(stage_index)
    _attach_id_variants(stage_index, id_resolutions)
    _attach_actions_and_external(stage_index, traces, cfg_index, nearest_a_cache, scope_meta, call_index)

    stages = list(stage_index.values())
    stages.sort(key=lambda s: s.get("_first_order", 10**9))
    for s in stages:
        s.pop("_first_order", None)

    technical_evidence_model = _build_technical_evidence_model(process_models, cfg_index, call_index, lineage_graph)
    legacy_stages = _to_legacy_stages(stages, transitions)

    process_name = manifest.get("process_name") or (process_models.get(root_id, {}) or {}).get("process_name") or "Proceso TWX"
    return {
        "title": f"{process_name} - Flujo cronologico funcional",
        "subtitle": "Reconstruccion funcional cronologica desde TWX",
        "process_identity": {"process_name": process_name, "root_artifact_id": root_id},
        "stages": legacy_stages,
        "functional_stages": stages,
        "transitions": transitions,
        "decisions": decisions,
        "contexts": contexts,
        "id_resolutions": id_resolutions,
        "loop_patterns": loop_patterns,
        "lineage_graph": lineage_graph,
        "traversal_traces": traces,
        "technical_evidence_model": technical_evidence_model,
        "evidence_index": evidence_index,
        "ambiguities": ambiguities,
    }


def _collect_process_models(artifacts: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for aid, a in artifacts.items():
        pm = a.get("process_model")
        if not pm:
            continue
        pid = pm.get("process_id") or aid
        out[pid] = pm
    return out


def _pick_root(process_models: Dict[str, Dict[str, Any]], process_name_hint: str) -> str:
    hint = _norm(process_name_hint)
    if hint:
        for pid, pm in process_models.items():
            if hint and hint in _norm(pm.get("process_name", "")):
                return pid
    ranked = sorted(
        process_models.keys(),
        key=lambda pid: (
            0 if any(k in _norm(process_models[pid].get("process_name", "")) for k in ("mp", "main", "principal")) else 1,
            process_models[pid].get("process_name", ""),
        ),
    )
    return ranked[0]


def _build_cfg_index(process_models: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    idx: Dict[str, Dict[str, Any]] = {}
    for pid, pm in process_models.items():
        nodes = {n["node_id"]: n for n in pm.get("nodes", []) if n.get("node_id")}
        flows = pm.get("flows", [])
        out_map: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        in_map: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for f in flows:
            s = f.get("source_node_id")
            t = f.get("target_node_id")
            if s and t:
                out_map[s].append(f)
                in_map[t].append(f)
        entry_nodes = [n for n in pm.get("entry_nodes", []) if n in nodes] or [nid for nid, n in nodes.items() if n.get("is_entry")]
        exit_nodes = [n for n in pm.get("exit_nodes", []) if n in nodes] or [nid for nid, n in nodes.items() if n.get("is_exit")]
        idx[pid] = {
            "nodes": nodes,
            "flows": flows,
            "out_map": out_map,
            "in_map": in_map,
            "entry_nodes": entry_nodes,
            "exit_nodes": exit_nodes,
        }
    return idx


def _build_call_index(process_models: Dict[str, Dict[str, Any]]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    process_ids = set(process_models.keys())
    for pid, pm in process_models.items():
        for n in pm.get("nodes", []):
            child = (n.get("attached_process_id") or "").strip().strip("/")
            if not child or child not in process_ids:
                continue
            in_maps = [m for m in n.get("mappings", []) if m.get("direction") == "input"]
            out_maps = [m for m in n.get("mappings", []) if m.get("direction") == "output"]
            out[(pid, n["node_id"])] = {"child_process_id": child, "input_mappings": in_maps, "output_mappings": out_maps}
    return out


def _traverse_contextual(root_id: str, cfg_index: Dict[str, Dict[str, Any]], call_index: Dict[Tuple[str, str], Dict[str, Any]]) -> Dict[str, Any]:
    traces: List[Dict[str, Any]] = []
    ambiguities: List[Dict[str, Any]] = []
    loop_patterns: List[Dict[str, Any]] = []
    evidence_index: List[Dict[str, Any]] = []
    lineage_nodes: Dict[str, Dict[str, Any]] = {}
    lineage_edges: List[Dict[str, Any]] = []
    ev_counter = 1
    trace_counter = 1
    max_depth = 16
    max_steps = 8000

    def add_evidence(kind: str, snippet: str, locator: str, relation: str) -> str:
        nonlocal ev_counter
        eid = f"ev-{ev_counter}"
        ev_counter += 1
        evidence_index.append(
            {
                "id": eid,
                "xml_locator": locator,
                "snippet": (snippet or "")[:300],
                "relation_type": relation,
                "kind": kind,
            }
        )
        return eid

    def add_lineage_node(node_id: str, kind: str, label: str, scope: str = "") -> None:
        if node_id in lineage_nodes:
            return
        lineage_nodes[node_id] = {"id": node_id, "kind": kind, "label": label, "scope": scope}

    def add_lineage_edge(source: str, target: str, relation: str, evidence_refs: Optional[List[str]] = None) -> None:
        lineage_edges.append({"source": source, "target": target, "relation": relation, "evidence_refs": evidence_refs or []})

    def resolve_value_expr(value_expr: str, scope: Dict[str, Any]) -> Any:
        expr = (value_expr or "").strip()
        if not expr:
            return None
        if expr in scope:
            return scope.get(expr)
        if expr.startswith("tw.local.") and expr in scope:
            return scope.get(expr)
        m = re.fullmatch(r"['\"](.*)['\"]", expr)
        if m:
            return m.group(1)
        if re.fullmatch(r"-?\d+(\.\d+)?", expr):
            return expr
        return scope.get(expr, expr)

    def apply_assignments(process_id: str, node: Dict[str, Any], scope: Dict[str, Any], evidence_refs: List[str]) -> None:
        for a in node.get("assignments", []):
            var = a.get("var", "").strip()
            val_expr = a.get("value", "").strip()
            if not var:
                continue
            val = resolve_value_expr(val_expr, scope)
            scope[var] = val
            lvar = f"var::{process_id}::{var}"
            lval = f"val::{_norm(str(val_expr))}"
            add_lineage_node(lvar, "variable", var, process_id)
            add_lineage_node(lval, "value", str(val_expr), process_id)
            add_lineage_edge(lval, lvar, "assigned_to", evidence_refs)

    def mapping_bindings(process_id: str, maps: List[Dict[str, Any]], scope: Dict[str, Any], direction: str, child_scope: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for m in maps:
            name = (m.get("name") or "").strip()
            value_expr = (m.get("value") or "").strip()
            if not name:
                continue
            val = resolve_value_expr(value_expr, scope if direction == "input" else (child_scope or {}))
            result[name] = val
            map_node = f"map::{process_id}::{direction}::{name}"
            add_lineage_node(map_node, "mapping", f"{direction}:{name}", process_id)
            if value_expr:
                val_node = f"val::{_norm(value_expr)}"
                add_lineage_node(val_node, "value", value_expr, process_id)
                add_lineage_edge(val_node, map_node, "mapping_value")
            tgt_var = f"var::{process_id}::{name}"
            add_lineage_node(tgt_var, "variable", name, process_id)
            add_lineage_edge(map_node, tgt_var, "maps_to")
        return result

    def choose_transition_kind(process_id: str, node: Dict[str, Any], outgoing: List[Dict[str, Any]]) -> Tuple[str, str, Optional[str]]:
        if len(outgoing) <= 1:
            return "normal", CONF_CORROBORADA, None

        if node.get("node_type") == "gateway":
            gtype = str(node.get("gateway_type", "")).strip()
            split_join = str(node.get("split_join_type", "")).strip()
            has_conditions = any((f.get("condition_expression") or f.get("condition_ref")) for f in outgoing)
            if split_join == "0":
                if gtype in {"0", "4", "5"} and not has_conditions:
                    return "parallel", CONF_INFERIDA, f"pg-{process_id}-{node.get('node_id')}"
                return "alternative", CONF_CORROBORADA if has_conditions else CONF_INFERIDA, None
            return "join", CONF_CORROBORADA, None
        return ("alternative", CONF_INFERIDA, None)

    def traverse_process(
        process_id: str,
        scope_in: Dict[str, Any],
        caller_frame: Optional[Dict[str, Any]],
        call_meta: Optional[Dict[str, Any]],
        depth: int,
        path: List[str],
        context_tags: List[str],
        path_conditions: List[str],
    ) -> List[Dict[str, Any]]:
        nonlocal trace_counter
        if depth > max_depth:
            ambiguities.append(
                {
                    "kind": "max_depth",
                    "stage_key": process_id,
                    "detail": f"Profundidad máxima alcanzada en subprocess anidado ({max_depth})",
                    "confidence": CONF_AMBIGUA,
                }
            )
            return []

        cfg = cfg_index.get(process_id)
        if not cfg:
            ambiguities.append(
                {
                    "kind": "missing_cfg",
                    "stage_key": process_id,
                    "detail": "No existe CFG para proceso",
                    "confidence": CONF_NO_LOCALIZADA,
                }
            )
            return []

        work = deque()
        exits: List[Dict[str, Any]] = []
        entry_nodes = cfg.get("entry_nodes", [])
        if not entry_nodes:
            return exits
        for en in entry_nodes:
            work.append((en, copy.deepcopy(scope_in), list(path_conditions), list(path), list(context_tags), []))

        visits: Dict[Tuple[str, str, str, str, str], int] = defaultdict(int)
        steps = 0

        while work:
            node_id, scope, conds, local_path, ctx_tags, ev_refs = work.popleft()
            steps += 1
            if steps > max_steps:
                ambiguities.append(
                    {
                        "kind": "max_steps",
                        "stage_key": process_id,
                        "detail": f"Se alcanzó límite de pasos ({max_steps})",
                        "confidence": CONF_AMBIGUA,
                    }
                )
                break

            node = cfg["nodes"].get(node_id)
            if not node:
                continue

            cond_sig = _canonical_state_signature(scope, conds)
            caller_pid = (caller_frame or {}).get("process_id") or ""
            caller_nid = (caller_frame or {}).get("node_id") or ""
            sig = (process_id, node_id, caller_pid, caller_nid, cond_sig)
            visits[sig] += 1
            if visits[sig] > 2:
                loop_patterns.append(
                    {
                        "loop_id": f"loop-{process_id}-{node_id}",
                        "loop_kind": "visited_state_cutoff",
                        "process_id": process_id,
                        "nodes": local_path[-6:] + [node_id],
                        "entry_stage": f"{process_id}::{node_id}",
                        "exit_stage": f"{process_id}::{node_id}",
                        "compensation_effect": None,
                        "reverse_evidence_chain": [],
                        "confidence": CONF_INFERIDA,
                    }
                )
                continue

            evidence_node = add_evidence("node", node.get("name", node_id), f"{process_id}/{node_id}", "node_visit")
            current_ev_refs = ev_refs + [evidence_node]
            apply_assignments(process_id, node, scope, current_ev_refs)

            trace_id = f"tr-{trace_counter}"
            trace_counter += 1
            traces.append(
                {
                    "trace_id": trace_id,
                    "order": len(traces),
                    "process_id": process_id,
                    "node_id": node_id,
                    "node_name": node.get("name", node_id),
                    "node_type": node.get("node_type", "activity"),
                    "node_subtype": node.get("node_subtype", ""),
                    "caller_process_id": (caller_frame or {}).get("process_id"),
                    "caller_node_id": (caller_frame or {}).get("node_id"),
                    "return_node_id": (caller_frame or {}).get("return_node_id"),
                    "path_conditions": list(conds),
                    "context_tags": list(ctx_tags),
                    "scope_snapshot": _compact_scope(scope),
                    "evidence_refs": list(current_ev_refs),
                }
            )

            # Mapeo de condiciones en lineage
            for f in cfg["out_map"].get(node_id, []):
                expr = (f.get("condition_expression") or "").strip()
                cref = (f.get("condition_ref") or "").strip()
                cond_text = expr or (f"condition_ref:{cref}" if cref else "")
                if not cond_text:
                    continue
                cnode = f"cond::{process_id}::{f.get('flow_id')}"
                add_lineage_node(cnode, "condition", cond_text, process_id)
                vars_in_expr = _extract_tw_vars(cond_text)
                for var in vars_in_expr:
                    v = f"var::{process_id}::{var}"
                    add_lineage_node(v, "variable", var, process_id)
                    add_lineage_edge(v, cnode, "used_in_condition", current_ev_refs)

            # Call activity: entrar/salir preservando frame/contexto
            call_info = call_index.get((process_id, node_id))
            if call_info:
                child_id = call_info["child_process_id"]
                in_binds = mapping_bindings(process_id, call_info.get("input_mappings", []), scope, "input")
                child_scope = {f"tw.local.{k}": v for k, v in in_binds.items()}
                child_ctx = ctx_tags + [f"caller:{process_id}::{node_id}", f"subprocess:{child_id}"]
                return_nodes = [e.get("target_node_id") for e in cfg["out_map"].get(node_id, []) if e.get("target_node_id")]
                return_node_id = return_nodes[0] if len(return_nodes) == 1 else ",".join(return_nodes[:4])
                child_exits = traverse_process(
                    child_id,
                    child_scope,
                    caller_frame={"process_id": process_id, "node_id": node_id, "return_node_id": return_node_id},
                    call_meta=call_info,
                    depth=depth + 1,
                    path=local_path + [node_id],
                    context_tags=child_ctx,
                    path_conditions=conds,
                )
                # merge output mappings (si no hay salida explícita se intenta con último scope hijo)
                child_last_scope = child_exits[-1]["scope"] if child_exits else child_scope
                out_bind_values = mapping_bindings(process_id, call_info.get("output_mappings", []), scope, "output", child_last_scope)
                for name, val in out_bind_values.items():
                    scope[f"tw.local.{name}"] = val

            outgoing = cfg["out_map"].get(node_id, [])
            if not outgoing:
                exits.append({"process_id": process_id, "node_id": node_id, "scope": scope})
                continue

            trans_kind, trans_conf, parallel_group_id = choose_transition_kind(process_id, node, outgoing)
            for edge in outgoing:
                tgt = edge.get("target_node_id")
                if not tgt:
                    continue
                edge_cond = (edge.get("condition_expression") or "").strip()
                edge_ref = (edge.get("condition_ref") or "").strip()
                cond_token = edge_cond
                if not edge_cond and edge_ref:
                    ambiguities.append(
                        {
                            "kind": "unresolved_flow_condition",
                            "stage_key": process_id,
                            "detail": f"No se resolvió expresión para condition_ref '{edge_ref}'",
                            "confidence": CONF_AMBIGUA,
                        }
                    )
                next_conds = list(conds)
                if cond_token:
                    next_conds.append(cond_token)

                # loop/back-edge detection con path local
                is_back_edge = tgt in local_path
                if is_back_edge:
                    # clasificación de reverso estructural (no léxica):
                    # trigger + secuencia + efecto: se usa cuando hay variable modificada que reaparece en decisiones/ruteo.
                    compensation = _detect_compensation_effect(process_id, scope, node, cfg, tgt)
                    loop_kind = "reverso_compensatorio" if compensation else "back_edge"
                    loop_patterns.append(
                        {
                            "loop_id": f"loop-{process_id}-{node_id}-{tgt}",
                            "loop_kind": loop_kind,
                            "process_id": process_id,
                            "nodes": local_path[-8:] + [node_id, tgt],
                            "entry_stage": f"{process_id}::{node_id}",
                            "exit_stage": f"{process_id}::{tgt}",
                            "compensation_effect": compensation,
                            "reverse_evidence_chain": list(current_ev_refs),
                            "confidence": CONF_CORROBORADA if compensation else CONF_INFERIDA,
                        }
                    )

                edge_ev = add_evidence(
                    "edge",
                    f"{node.get('name', node_id)} -> {cfg['nodes'].get(tgt, {}).get('name', tgt)}",
                    f"{process_id}/{edge.get('flow_id', '')}",
                    "sequence_flow",
                )
                work.append((tgt, copy.deepcopy(scope), next_conds, local_path + [node_id], list(ctx_tags), current_ev_refs + [edge_ev]))

                traces.append(
                    {
                        "trace_id": f"tr-{trace_counter}",
                        "order": len(traces),
                        "process_id": process_id,
                        "edge": True,
                        "source_node_id": node_id,
                        "target_node_id": tgt,
                        "flow_id": edge.get("flow_id", ""),
                        "transition_kind": trans_kind,
                        "parallel_group_id": parallel_group_id,
                        "condition": cond_token,
                        "condition_ref": edge_ref,
                        "is_back_edge": is_back_edge,
                        "confidence": trans_conf,
                        "caller_process_id": (caller_frame or {}).get("process_id"),
                        "caller_node_id": (caller_frame or {}).get("node_id"),
                        "context_tags": list(ctx_tags),
                        "evidence_refs": current_ev_refs + [edge_ev],
                    }
                )
                trace_counter += 1

        return exits

    traverse_process(
        root_id,
        scope_in={},
        caller_frame=None,
        call_meta=None,
        depth=0,
        path=[],
        context_tags=["root_process"],
        path_conditions=[],
    )

    # Detección estructural de ciclos (SCC / self-loop), independiente del recorrido.
    loop_patterns.extend(_detect_structural_loops(cfg_index))
    loop_patterns = _dedupe_dicts(loop_patterns, ("loop_id",))

    return {
        "traces": traces,
        "ambiguities": ambiguities,
        "loop_patterns": loop_patterns,
        "evidence_index": evidence_index,
        "lineage_graph": {"nodes": list(lineage_nodes.values()), "edges": lineage_edges},
    }


def _classify_scope(
    process_models: Dict[str, Dict[str, Any]],
    traces: List[Dict[str, Any]],
    cfg_index: Dict[str, Dict[str, Any]],
    call_index: Dict[Tuple[str, str], Dict[str, Any]],
    root_process_id: str,
) -> Dict[str, Dict[str, Any]]:
    visited_nodes: Set[Tuple[str, str]] = set()
    for t in traces:
        if t.get("edge"):
            continue
        visited_nodes.add((t.get("process_id"), t.get("node_id")))

    scope_meta: Dict[str, Dict[str, Any]] = {}
    for pid, cfg in cfg_index.items():
        for nid, node in cfg["nodes"].items():
            key = f"{pid}::{nid}"
            impacts = []
            if (pid, nid) in visited_nodes:
                impacts.append("reachable_from_main")
            if cfg["out_map"].get(nid):
                impacts.append("participates_in_control_flow")
            if node.get("assignments"):
                impacts.append("transforms_variables")
            if node.get("mappings"):
                impacts.append("cross_scope_mapping")
            if node.get("node_type") == "gateway":
                impacts.append("routing_decision")
            if (pid, nid) in call_index:
                impacts.append("subprocess_boundary")

            # Default conservador: C
            scope_class = "C"

            # A = subetapa funcional representable: call activity
            if (pid, nid) in call_index:
                scope_class = "A"
                impacts.append("functional_stage_subprocess_call")
            # End event visible solo para proceso raíz
            elif node.get("node_type") == "event" and node.get("is_exit") and pid == root_process_id:
                scope_class = "A"
                impacts.append("root_terminal_event")
            # Acción humana con impacto en ruteo: A
            elif node.get("is_user_action_candidate") and len(cfg["out_map"].get(nid, [])) > 0:
                scope_class = "A"
                impacts.append("human_action_boundary")
            elif node.get("node_type") == "gateway" and len(cfg["out_map"].get(nid, [])) > 1:
                scope_class = "B"
                impacts.append("branching_logic")
            elif impacts:
                scope_class = "B"
            scope_meta[key] = {
                "scope_class": scope_class,
                "scope_impact_reason": ", ".join(impacts) if impacts else "no_functional_impact_detected",
                "evidence": impacts,
            }
    return scope_meta


def _build_functional_stages(
    process_models: Dict[str, Dict[str, Any]],
    traces: List[Dict[str, Any]],
    scope_meta: Dict[str, Dict[str, Any]],
    nearest_a_cache: Dict[Tuple[str, str], Optional[str]],
    cfg_index: Dict[str, Dict[str, Any]],
    root_process_id: str,
) -> Dict[str, Dict[str, Any]]:
    stages: Dict[str, Dict[str, Any]] = {}
    stage_order = 0
    by_trace_node: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for t in traces:
        if t.get("edge"):
            continue
        by_trace_node[(t.get("process_id"), t.get("node_id"))].append(t)

    for pid, cfg in cfg_index.items():
        for nid, node in cfg["nodes"].items():
            technical_key = f"{pid}::{nid}"
            meta = scope_meta.get(technical_key, {})
            if meta.get("scope_class") != "A":
                continue
            if _is_noise_name(node.get("name", "")) and not node.get("attached_process_id"):
                continue
            stage_key = _stage_key(
                node.get("name", nid),
                technical_key,
                node=node,
                process_id=pid,
                root_process_id=root_process_id,
            )
            samples = by_trace_node.get((pid, nid), [])
            if stage_key not in stages:
                stages[stage_key] = {
                    "stage_key": stage_key,
                    "functional_name": _clean_stage_name(node.get("name", nid)),
                    "functional_type": "subetapa",
                    "technical_artifacts": [
                        {
                            "artifact_id": pid,
                            "artifact_name": process_models.get(pid, {}).get("process_name", pid),
                            "source_node_id": nid,
                            "source_node_name": node.get("name", nid),
                        }
                    ],
                    "scope_class": meta.get("scope_class", "A"),
                    "scope_impact_reason": meta.get("scope_impact_reason", ""),
                    "entry_points": [],
                    "actions": [],
                    "external_interactions": [],
                    "exits": [],
                    "contexts": [],
                    "id_variants": [],
                    "confidence": CONF_INFERIDA,
                    "_first_order": 10**9,
                }
            if samples:
                min_order = min(s.get("order", 10**9) for s in samples)
                stages[stage_key]["_first_order"] = min(stages[stage_key]["_first_order"], min_order)
                ctx_seen = set(c.get("context_key") for c in stages[stage_key]["contexts"])
                for s in samples[:24]:
                    ckey, clabel, cconds = _canonical_context_signature(
                        pid,
                        nid,
                        s.get("caller_process_id"),
                        s.get("caller_node_id"),
                        s.get("context_tags", []),
                        s.get("path_conditions", []),
                        s.get("scope_snapshot", {}) or {},
                    )
                    if ckey in ctx_seen:
                        continue
                    ctx_seen.add(ckey)
                    stages[stage_key]["contexts"].append(
                        {
                            "context_key": ckey,
                            "label": clabel,
                            "conditions": cconds,
                            "caller_process_id": s.get("caller_process_id"),
                            "caller_node_id": s.get("caller_node_id"),
                        }
                    )
            # Entry points
            for fin in cfg["in_map"].get(nid, []):
                src = fin.get("source_node_id")
                src_key = _nearest_a_stage_key(pid, src, scope_meta, cfg_index, nearest_a_cache)
                if src_key:
                    stages[stage_key]["entry_points"].append({"from_stage": src_key, "condition": _display_safe_condition(fin.get("condition_expression") or ""), "evidence_refs": []})

    for st in stages.values():
        st["entry_points"] = _dedupe_dicts(st["entry_points"], ("from_stage", "condition"))
    return stages


def _build_transitions_and_decisions(
    stage_index: Dict[str, Dict[str, Any]],
    traces: List[Dict[str, Any]],
    cfg_index: Dict[str, Dict[str, Any]],
    nearest_a_cache: Dict[Tuple[str, str], Optional[str]],
    ambiguities: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    transitions: List[Dict[str, Any]] = []
    decisions: List[Dict[str, Any]] = []

    trace_nodes_by_proc: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for t in traces:
        if t.get("edge"):
            continue
        trace_nodes_by_proc[(t.get("process_id"), t.get("node_id"))] = t

    for t in traces:
        if not t.get("edge"):
            continue
        pid = t.get("process_id")
        src = t.get("source_node_id")
        tgt = t.get("target_node_id")
        from_stage = _nearest_a_stage_key(pid, src, _scope_from_stages(stage_index), cfg_index, nearest_a_cache)
        to_stage = _nearest_a_stage_key(pid, tgt, _scope_from_stages(stage_index), cfg_index, nearest_a_cache)
        if not from_stage or not to_stage:
            continue
        transitions.append(
            {
                "from_stage": from_stage,
                "to_stage": to_stage,
                "transition_kind": _classify_transition_semantics(
                    from_stage,
                    to_stage,
                    t.get("transition_kind", "normal"),
                    bool(t.get("is_back_edge")),
                    bool((t.get("trigger") or {}).get("condition", "") if isinstance(t.get("trigger"), dict) else t.get("condition")),
                ),
                "parallel_group_id": t.get("parallel_group_id"),
                "trigger": {"kind": "flow", "condition": _display_safe_condition(t.get("condition", "")), "flow_id": t.get("flow_id", "")},
                "context_ref": " / ".join((t.get("context_tags") or [])[:3]),
                "confidence": t.get("confidence", CONF_INFERIDA),
                "evidence_refs": t.get("evidence_refs", []),
            }
        )

    # decisiones desde gateways del CFG (no requiere que gateway sea subetapa A)
    stage_scope = _scope_from_stages(stage_index)
    for pid, cfg in cfg_index.items():
        for nid, node in cfg.get("nodes", {}).items():
            if node.get("node_type") != "gateway":
                continue
            outs = cfg.get("out_map", {}).get(nid, [])
            if len(outs) <= 1:
                continue
            kind, conf, pgid = _gateway_decision_kind(node, outs, pid, nid)
            stage_key = _nearest_a_stage_key(pid, nid, stage_scope, cfg_index, nearest_a_cache)
            branches = []
            for o in outs:
                dest = _nearest_a_stage_key(pid, o.get("target_node_id"), stage_scope, cfg_index, nearest_a_cache)
                if not dest:
                    continue
                branches.append(
                    {
                        "condition": _display_safe_condition(o.get("condition_expression") or ""),
                        "destination_stage": dest,
                        "branch_kind": kind if kind in {"alternative", "parallel"} else "alternative",
                        "parallel_group_id": pgid,
                        "confidence": conf,
                    }
                )
            if len(branches) >= 2:
                decisions.append(
                    {
                        "decision_id": f"dec-{pid}-{nid}",
                        "stage_key": stage_key or _stage_key(node.get("name", nid), f"{pid}::{nid}", node=node, process_id=pid, root_process_id=pid),
                        "decision_type": kind if kind in {"alternative", "parallel"} else "alternative",
                        "expressions": [_display_safe_condition(b.get("condition", "")) for b in branches if _display_safe_condition(b.get("condition", ""))][:12],
                        "branches": _dedupe_dicts(branches, ("condition", "destination_stage", "branch_kind")),
                        "default_branch": None,
                        "evidence_refs": [],
                        "confidence": conf,
                    }
                )
            elif branches:
                ambiguities.append(
                    {
                        "kind": "gateway_without_resolved_branches",
                        "stage_key": stage_key or f"{pid}::{nid}",
                        "detail": "No se pudo resolver destino funcional de todas las ramas del gateway",
                        "confidence": CONF_AMBIGUA,
                    }
                )

    transitions = _dedupe_dicts(
        transitions,
        ("from_stage", "to_stage", "transition_kind", "parallel_group_id", "context_ref"),
    )
    return transitions, decisions


def _attach_actions_and_external(
    stage_index: Dict[str, Dict[str, Any]],
    traces: List[Dict[str, Any]],
    cfg_index: Dict[str, Dict[str, Any]],
    nearest_a_cache: Dict[Tuple[str, str], Optional[str]],
    scope_meta: Dict[str, Dict[str, Any]],
    call_index: Dict[Tuple[str, str], Dict[str, Any]],
) -> None:
    trace_edges = [t for t in traces if t.get("edge")]
    for sk, st in stage_index.items():
        ta = st.get("technical_artifacts", [{}])[0]
        pid = ta.get("artifact_id")
        nid = ta.get("source_node_id")
        if not pid or not nid:
            continue
        node = cfg_index.get(pid, {}).get("nodes", {}).get(nid)
        if not node:
            continue
        outgoing = [e for e in trace_edges if e.get("process_id") == pid and e.get("source_node_id") == nid]
        paths = []
        for oe in outgoing:
            dsk = _nearest_a_stage_key(pid, oe.get("target_node_id"), scope_meta, cfg_index, nearest_a_cache)
            if not dsk:
                continue
            paths.append(
                {
                    "condition": _display_safe_condition(oe.get("condition", "")),
                    "destination_stage": dsk,
                    "transition_kind": _classify_transition_semantics(
                        sk,
                        dsk,
                        oe.get("transition_kind", "normal"),
                        bool(oe.get("is_back_edge")),
                        bool(oe.get("condition")),
                    ),
                    "parallel_group_id": oe.get("parallel_group_id"),
                    "confidence": oe.get("confidence", CONF_INFERIDA),
                    "evidence_refs": oe.get("evidence_refs", []),
                }
            )
        paths = _dedupe_dicts(paths, ("condition", "destination_stage", "transition_kind", "parallel_group_id"))

        validations = _rules_to_validations(node.get("ui_rules", []))
        assignments = [{"var": a.get("var"), "value": a.get("value"), "evidence_refs": []} for a in node.get("assignments", [])[:8]]

        if node.get("is_user_action_candidate"):
            st["actions"].append(
                {
                    "action_name": node.get("name", nid),
                    "source_ui": node.get("name", nid),
                    "assignments": assignments,
                    "validations": validations,
                    "ui_state_signatures": _ui_state_signatures(validations),
                    "resulting_paths": paths,
                    "confidence": CONF_CORROBORADA if paths else CONF_INFERIDA,
                }
            )
        elif (pid, nid) in call_index:
            # Subetapa representada por call-activity: proyecta acciones humanas del proceso hijo.
            child_id = call_index[(pid, nid)].get("child_process_id")
            child_cfg = cfg_index.get(child_id, {})
            for cnid, cnode in child_cfg.get("nodes", {}).items():
                if not cnode.get("is_user_action_candidate"):
                    continue
                cpaths = []
                for ce in trace_edges:
                    if ce.get("process_id") != child_id or ce.get("source_node_id") != cnid:
                        continue
                    dest = _nearest_a_stage_key(child_id, ce.get("target_node_id"), scope_meta, cfg_index, nearest_a_cache)
                    if not dest:
                        # retorno al caller: usa siguiente destino del call-activity
                        if paths:
                            dest = paths[0].get("destination_stage")
                    if not dest:
                        continue
                    cpaths.append(
                        {
                            "condition": _display_safe_condition(ce.get("condition", "")),
                            "destination_stage": dest,
                            "transition_kind": _classify_transition_semantics(
                                sk,
                                dest,
                                ce.get("transition_kind", "normal"),
                                bool(ce.get("is_back_edge")),
                                bool(ce.get("condition")),
                            ),
                            "parallel_group_id": ce.get("parallel_group_id"),
                            "confidence": ce.get("confidence", CONF_INFERIDA),
                            "evidence_refs": ce.get("evidence_refs", []),
                        }
                    )
                st["actions"].append(
                    {
                        "action_name": cnode.get("name", cnid),
                        "source_ui": cnode.get("name", cnid),
                        "assignments": [{"var": a.get("var"), "value": a.get("value"), "evidence_refs": []} for a in cnode.get("assignments", [])[:8]],
                        "validations": _rules_to_validations(cnode.get("ui_rules", [])),
                        "ui_state_signatures": _ui_state_signatures(_rules_to_validations(cnode.get("ui_rules", []))),
                        "resulting_paths": _dedupe_dicts(cpaths, ("condition", "destination_stage", "transition_kind", "parallel_group_id")),
                        "confidence": CONF_CORROBORADA if cpaths else CONF_INFERIDA,
                    }
                )
        else:
            src_type = _infer_external_source_type(node)
            if paths:
                st["external_interactions"].append(
                    {
                        "source_type": src_type,
                        "source_name": node.get("name", nid),
                        "outcome_conditions": [p.get("condition", "") for p in paths if p.get("condition")][:10],
                        "derived_variables": _vars_from_assignments(node.get("assignments", [])),
                        "resulting_paths": paths,
                        "confidence": CONF_CORROBORADA if any(p.get("condition") for p in paths) else CONF_INFERIDA,
                    }
                )

        st["exits"] = _dedupe_dicts(
            [
                {
                    "to_stage": p.get("destination_stage"),
                    "trigger": {
                        "kind": "action" if node.get("is_user_action_candidate") else "external_outcome",
                        "action_name": node.get("name", nid) if node.get("is_user_action_candidate") else "",
                        "condition": p.get("condition", ""),
                    },
                    "transition_kind": p.get("transition_kind", "normal"),
                    "parallel_group_id": p.get("parallel_group_id"),
                }
                for p in paths
            ],
            ("to_stage", "transition_kind", "parallel_group_id"),
        )

        st["confidence"] = _stage_confidence(st)


def _collect_contexts(stage_index: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    contexts: List[Dict[str, Any]] = []
    seen = set()
    for st in stage_index.values():
        for c in st.get("contexts", []):
            ck = (st.get("stage_key"), c.get("context_key"))
            if ck in seen:
                continue
            seen.add(ck)
            contexts.append(
                {
                    "stage_key": st.get("stage_key"),
                    "context_key": c.get("context_key"),
                    "label": c.get("label", ""),
                    "conditions": [_display_safe_condition(x) for x in (c.get("conditions", []) or []) if _display_safe_condition(x)],
                    "caller_process_id": c.get("caller_process_id"),
                    "caller_node_id": c.get("caller_node_id"),
                }
            )
    return contexts


def _resolve_functional_ids(
    process_models: Dict[str, Dict[str, Any]],
    lineage_graph: Dict[str, Any],
    traces: List[Dict[str, Any]],
    manifest: Dict[str, Any],
    evidence_index: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    usages_by_var: Dict[str, List[str]] = defaultdict(list)
    for e in lineage_graph.get("edges", []):
        if e.get("relation") in {"used_in_condition", "maps_to"}:
            usages_by_var[e.get("source", "")].append(e.get("relation"))

    env_defaults = manifest.get("environment_variables", {}) or {}
    env_overrides = manifest.get("environment_overrides", {}) or {}

    candidates: List[Dict[str, Any]] = []
    for pid, pm in process_models.items():
        for n in pm.get("nodes", []):
            for a in n.get("assignments", []):
                value = (a.get("value") or "").strip()
                if not value:
                    continue
                if not _looks_id_candidate(value):
                    continue
                var = (a.get("var") or "").strip()
                var_key = f"var::{pid}::{var}"
                use_ctx = _functional_usage_context(var, value, var_key, usages_by_var, n, pm)
                if not use_ctx:
                    continue
                source_kind = "env_ref" if "tw.env." in value else ("numeric_literal" if re.fullmatch(r"-?\d+", value) else "expression")
                confidence = CONF_CORROBORADA if "routing_condition" in use_ctx else CONF_INFERIDA
                candidates.append(
                    {
                        "id_value": value,
                        "value_source": source_kind,
                        "context": f"{pid}::{n.get('node_id')}",
                        "id_usage_contexts": use_ctx,
                        "id_promotion_reason": "functional_usage_test_passed",
                        "evidence_refs": [],
                        "confidence": confidence,
                    }
                )

    # variables de ambiente como id funcional cuando su uso es funcional
    for env_name, default in env_defaults.items():
        if not _looks_id_candidate(default or env_name):
            continue
        ov = env_overrides.get(env_name, [])
        candidates.append(
            {
                "id_value": default or env_name,
                "value_source": "environment_default",
                "context": env_name,
                "id_usage_contexts": ["environment_configuration"],
                "id_promotion_reason": "environment_variable_with_functional_usage",
                "environment_var": env_name,
                "environment_overrides": ov,
                "evidence_refs": [],
                "confidence": CONF_INFERIDA if ov else CONF_AMBIGUA,
            }
        )

    return _dedupe_dicts(
        candidates,
        ("id_value", "value_source", "context", "id_promotion_reason"),
    )[:220]


def _functional_usage_context(
    var: str,
    value: str,
    var_key: str,
    usages_by_var: Dict[str, List[str]],
    node: Dict[str, Any],
    process_model: Dict[str, Any],
) -> List[str]:
    out = []
    if usages_by_var.get(var_key):
        if "used_in_condition" in usages_by_var[var_key]:
            out.append("routing_condition")
        if "maps_to" in usages_by_var[var_key]:
            out.append("cross_scope_mapping")

    # evidencia por uso de mapping en fronteras funcionales (call activity)
    if node.get("attached_process_id"):
        out.append("subprocess_boundary")

    # uso en parámetros de mapping con semántica funcional (genérico por nombre de parámetro)
    for m in node.get("mappings", []):
        mv = (m.get("value") or "").strip()
        if var and mv.endswith(var):
            pname = _norm(m.get("name", ""))
            if any(tok in pname for tok in ("id", "stage", "step", "state", "status", "operation", "subproceso", "etapa")):
                out.append("functional_parameter_mapping")

    # uso en scripts de bitácora/notificación/estado (evidencia secundaria)
    for s in node.get("scripts", []):
        st = _norm(s)
        if var and var.split(".")[-1].lower() in st and any(tok in st for tok in ("bitacora", "log", "notify", "notific", "estado", "status")):
            out.append("functional_logging_or_notification")

    return _dedupe_strings(out)


def _attach_id_variants(stage_index: Dict[str, Dict[str, Any]], id_resolutions: List[Dict[str, Any]]) -> None:
    by_context: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for ir in id_resolutions:
        ctx = ir.get("context", "")
        by_context[ctx].append(ir)

    for st in stage_index.values():
        variants = []
        seen = set()
        for ta in st.get("technical_artifacts", []):
            context_key = f"{ta.get('artifact_id')}::{ta.get('source_node_id')}"
            for ir in by_context.get(context_key, []):
                sig = (ir.get("id_value", ""), ",".join(ir.get("id_usage_contexts", [])[:2]))
                if sig in seen:
                    continue
                seen.add(sig)
                variants.append(
                    {
                        "id_value": ir.get("id_value", ""),
                        "condition": "",
                        "context": ", ".join(ir.get("id_usage_contexts", [])[:2]),
                        "value_source": ir.get("value_source", ""),
                        "id_promotion_reason": ir.get("id_promotion_reason", ""),
                        "confidence": ir.get("confidence", CONF_INFERIDA),
                        "evidence_refs": ir.get("evidence_refs", []),
                    }
                )
        st["id_variants"] = variants[:8]


def _build_technical_evidence_model(
    process_models: Dict[str, Dict[str, Any]],
    cfg_index: Dict[str, Dict[str, Any]],
    call_index: Dict[Tuple[str, str], Dict[str, Any]],
    lineage_graph: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "processes": [
            {
                "process_id": pid,
                "process_name": pm.get("process_name", pid),
                "entry_nodes": cfg_index.get(pid, {}).get("entry_nodes", []),
                "exit_nodes": cfg_index.get(pid, {}).get("exit_nodes", []),
                "node_count": len(cfg_index.get(pid, {}).get("nodes", {})),
                "flow_count": len(cfg_index.get(pid, {}).get("flows", [])),
                "call_sites": pm.get("call_sites", []),
            }
            for pid, pm in process_models.items()
        ],
        "call_index": [
            {
                "caller_process_id": pid,
                "caller_node_id": nid,
                "child_process_id": meta.get("child_process_id"),
                "input_mappings": meta.get("input_mappings", []),
                "output_mappings": meta.get("output_mappings", []),
            }
            for (pid, nid), meta in call_index.items()
        ],
        "lineage_graph": lineage_graph,
    }


def _gateway_decision_kind(node: Dict[str, Any], outs: List[Dict[str, Any]], process_id: str, node_id: str) -> Tuple[str, str, Optional[str]]:
    gtype = str(node.get("gateway_type", "")).strip()
    split_join = str(node.get("split_join_type", "")).strip()
    has_conditions = any((o.get("condition_expression") or o.get("condition_ref")) for o in outs)
    if split_join == "0":
        if gtype in {"0", "4", "5"} and not has_conditions:
            return "parallel", CONF_INFERIDA, f"pg-{process_id}-{node_id}"
        return "alternative", CONF_CORROBORADA if has_conditions else CONF_INFERIDA, None
    return "alternative", CONF_INFERIDA, None


def _nearest_a_stage_key(
    process_id: str,
    node_id: Optional[str],
    scope_meta: Dict[str, Dict[str, Any]],
    cfg_index: Dict[str, Dict[str, Any]],
    cache: Dict[Tuple[str, str], Optional[str]],
) -> Optional[str]:
    if not node_id:
        return None
    ck = (process_id, node_id)
    if ck in cache:
        return cache[ck]

    this_key = f"{process_id}::{node_id}"
    if scope_meta.get(this_key, {}).get("scope_class") == "A":
        n = cfg_index[process_id]["nodes"].get(node_id, {})
        sk = _stage_key(n.get("name", node_id), this_key, node=n, process_id=process_id)
        cache[ck] = sk
        return sk

    # BFS hacia adelante hasta encontrar un nodo A
    seen = set([node_id])
    q = deque([node_id])
    while q:
        cur = q.popleft()
        for f in cfg_index.get(process_id, {}).get("out_map", {}).get(cur, []):
            nxt = f.get("target_node_id")
            if not nxt or nxt in seen:
                continue
            seen.add(nxt)
            nkey = f"{process_id}::{nxt}"
            if scope_meta.get(nkey, {}).get("scope_class") == "A":
                n = cfg_index[process_id]["nodes"].get(nxt, {})
                sk = _stage_key(n.get("name", nxt), nkey, node=n, process_id=process_id)
                cache[ck] = sk
                return sk
            q.append(nxt)
    cache[ck] = None
    return None


def _detect_compensation_effect(
    process_id: str,
    scope: Dict[str, Any],
    node: Dict[str, Any],
    cfg: Dict[str, Any],
    back_target_node_id: str,
) -> Optional[Dict[str, Any]]:
    # Reverso estructural: back-edge + modificaciones de variables que vuelven a usarse en decisiones.
    assigns = node.get("assignments", []) or []
    if not assigns:
        return None
    modified_vars = [a.get("var", "") for a in assigns if a.get("var")]
    if not modified_vars:
        return None
    used_in_gateways = []
    for gv in cfg.get("nodes", {}).values():
        if gv.get("node_type") != "gateway":
            continue
        for f in cfg.get("out_map", {}).get(gv.get("node_id"), []):
            cond = (f.get("condition_expression") or "") + " " + (f.get("condition_ref") or "")
            for mv in modified_vars:
                if mv and mv in cond:
                    used_in_gateways.append({"gateway_node_id": gv.get("node_id"), "var": mv})
    if not used_in_gateways:
        return None
    return {
        "type": "variable_compensation_reentry",
        "modified_vars": _dedupe_strings(modified_vars)[:8],
        "used_in_routing": used_in_gateways[:8],
        "target_node_id": back_target_node_id,
    }


def _detect_structural_loops(cfg_index: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    loops: List[Dict[str, Any]] = []
    for pid, cfg in cfg_index.items():
        g = nx.DiGraph()
        for nid in cfg.get("nodes", {}):
            g.add_node(nid)
        for f in cfg.get("flows", []):
            s = f.get("source_node_id")
            t = f.get("target_node_id")
            if s and t:
                g.add_edge(s, t)

        for comp in nx.strongly_connected_components(g):
            if len(comp) > 1:
                nodes = sorted(comp)
                loops.append(
                    {
                        "loop_id": f"scc-{pid}-{'-'.join(nodes[:3])}",
                        "loop_kind": "scc_cycle",
                        "process_id": pid,
                        "nodes": nodes[:20],
                        "entry_stage": f"{pid}::{nodes[0]}",
                        "exit_stage": f"{pid}::{nodes[-1]}",
                        "compensation_effect": None,
                        "reverse_evidence_chain": [],
                        "confidence": CONF_CORROBORADA,
                    }
                )
        for n in g.nodes:
            if g.has_edge(n, n):
                loops.append(
                    {
                        "loop_id": f"self-{pid}-{n}",
                        "loop_kind": "self_loop",
                        "process_id": pid,
                        "nodes": [n],
                        "entry_stage": f"{pid}::{n}",
                        "exit_stage": f"{pid}::{n}",
                        "compensation_effect": None,
                        "reverse_evidence_chain": [],
                        "confidence": CONF_CORROBORADA,
                    }
                )
    return loops


def _scope_from_stages(stage_index: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out = {}
    for st in stage_index.values():
        ta = st.get("technical_artifacts", [{}])[0]
        if ta.get("artifact_id") and ta.get("source_node_id"):
            out[f"{ta['artifact_id']}::{ta['source_node_id']}"] = {"scope_class": "A"}
    return out


def _rules_to_validations(rules: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    out = {"enabled_if": [], "disabled_if": [], "visible_if": [], "hidden_if": [], "readonly_if": []}
    for r in rules or []:
        var = r.get("var", "")
        op = r.get("operand", "")
        action = _norm(r.get("action", ""))
        cond = f"{var} == {op}" if var else ""
        if not cond:
            continue
        if "readonly" in action:
            out["readonly_if"].append(cond)
        elif "hide" in action:
            out["hidden_if"].append(cond)
        elif "show" in action or "default" in action:
            out["visible_if"].append(cond)
        elif "disable" in action:
            out["disabled_if"].append(cond)
        elif "enable" in action:
            out["enabled_if"].append(cond)
        else:
            out["disabled_if"].append(cond)
    for k in out:
        out[k] = _dedupe_strings(out[k])[:10]
    return out


def _ui_state_signatures(validations: Dict[str, List[str]]) -> List[str]:
    labels = (
        ("enabled_if", "enabled"),
        ("disabled_if", "disabled"),
        ("visible_if", "visible"),
        ("hidden_if", "hidden"),
        ("readonly_if", "readonly"),
    )
    sigs = []
    for key, label in labels:
        vals = validations.get(key, []) or []
        if vals:
            sigs.append(f"{label}:{' && '.join(vals[:2])}")
    return sigs[:6]


def _infer_external_source_type(node: Dict[str, Any]) -> str:
    sub = _norm(node.get("node_subtype", ""))
    if "service" in sub:
        return "service"
    if node.get("node_type") == "event":
        return "event"
    if node.get("attached_process_id"):
        return "subprocess"
    return "uca_bus"


def _vars_from_assignments(assignments: List[Dict[str, Any]]) -> List[str]:
    vals = [a.get("var", "") for a in assignments if a.get("var")]
    return _dedupe_strings(vals)[:12]


def _stage_confidence(stage: Dict[str, Any]) -> str:
    score = 0
    if stage.get("actions"):
        score += 3
    if stage.get("external_interactions"):
        score += 2
    if stage.get("contexts"):
        score += 1
    if stage.get("entry_points"):
        score += 1
    if stage.get("id_variants"):
        score += 1
    if score >= 6:
        return CONF_CORROBORADA
    if score >= 3:
        return CONF_INFERIDA
    if score >= 1:
        return CONF_AMBIGUA
    return CONF_NO_LOCALIZADA


def _to_legacy_stages(stages: List[Dict[str, Any]], transitions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    name_by_key = {s["stage_key"]: s.get("functional_name", s["stage_key"]) for s in stages}
    outgoing: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for t in transitions:
        outgoing[t.get("from_stage", "")].append(t)

    out = []
    for i, s in enumerate(stages, start=1):
        disp = _format_stage_ids(s.get("id_variants", []))
        groups = []
        for act in s.get("actions", []):
            paths = act.get("resulting_paths", [])
            if len(paths) <= 1:
                p = paths[0] if paths else {}
                dest = name_by_key.get(p.get("destination_stage"), p.get("destination_stage", ""))
                line = act.get("action_name", "Accion")
                if p.get("condition"):
                    line += f" ({p.get('condition')})"
                if dest:
                    line += f" -> {dest}"
                groups.append({"title": "Botones", "meta": _format_validations(act.get("validations", {})), "note": "", "routes": [line]})
            else:
                lines = []
                for p in paths:
                    dest = name_by_key.get(p.get("destination_stage"), p.get("destination_stage", ""))
                    txt = f"-> {dest}"
                    if p.get("condition"):
                        txt += f", si {p.get('condition')}"
                    lines.append(txt)
                groups.append(
                    {
                        "title": f"Botón: {act.get('action_name', 'Accion')}",
                        "meta": _format_validations(act.get("validations", {})),
                        "note": "Caminos alternativos: solo se ejecuta uno según condición" if any(p.get("transition_kind") == "alternative" for p in paths) else "Caminos paralelos: se ejecutan múltiples ramas",
                        "routes": lines,
                    }
                )

        routes = []
        for ext in s.get("external_interactions", []):
            src = (ext.get("source_type") or "SERVICIO").upper()
            for p in ext.get("resulting_paths", []):
                dest = name_by_key.get(p.get("destination_stage"), p.get("destination_stage", ""))
                cond = p.get("condition", "")
                if cond:
                    routes.append(f"{src}: {cond} -> {dest}")
                else:
                    routes.append(f"{src}: -> {dest}")
        if not routes:
            for t in outgoing.get(s["stage_key"], []):
                dest = name_by_key.get(t.get("to_stage"), t.get("to_stage", ""))
                cond = (t.get("trigger") or {}).get("condition", "")
                routes.append(f"{cond} -> {dest}" if cond else f"-> {dest}")
        routes = _dedupe_strings(routes) or ["Sin salida funcional comprobada"]
        out.append(
            {
                "id": f"s{i}",
                "display_id": disp,
                "business_code": "",
                "name": s.get("functional_name", s["stage_key"]),
                "tag": s.get("functional_type", "subetapa"),
                "routes": routes[:20],
                "groups": groups[:12],
            }
        )
    return out


def _format_stage_ids(variants: List[Dict[str, Any]]) -> str:
    parts = []
    for v in variants or []:
        val = (v.get("id_value") or "").strip()
        if not val:
            continue
        ctx = (v.get("context") or "").strip()
        parts.append(f"{val} ({ctx})" if ctx else val)
    return " / ".join(parts[:4])


def _format_validations(validations: Dict[str, List[str]]) -> str:
    chunks = []
    for k, label in (
        ("enabled_if", "habilitado si"),
        ("disabled_if", "deshabilitado si"),
        ("visible_if", "visible si"),
        ("hidden_if", "oculto si"),
        ("readonly_if", "solo lectura si"),
    ):
        vals = validations.get(k, []) or []
        if vals:
            chunks.append(f"{label}: {' OR '.join(vals[:2])}")
    return " | ".join(chunks)


def _compact_scope(scope: Dict[str, Any]) -> Dict[str, Any]:
    if not scope:
        return {}
    items = list(scope.items())[:40]
    return {k: (str(v)[:120] if v is not None else None) for k, v in items}


def _looks_id_candidate(value: str) -> bool:
    v = (value or "").strip()
    if not v:
        return False
    if "tw.env." in v:
        return True
    if re.fullmatch(r"-?\d+", v):
        return True
    if re.fullmatch(r"[A-Z0-9_]+", v) and "ID" in v:
        return True
    return False


def _extract_tw_vars(expr: str) -> List[str]:
    return _dedupe_strings(re.findall(r"(tw\.(?:local|env)\.[A-Za-z0-9_\.]+)", expr or ""))


def _canonical_state_signature(scope: Dict[str, Any], conditions: List[str]) -> str:
    vars_used = []
    for c in (conditions or [])[-6:]:
        vars_used.extend(_extract_tw_vars(c))
    vars_used = sorted(set(vars_used))[:8]
    if not vars_used:
        return "no-vars"
    buckets = []
    for v in vars_used:
        val = scope.get(v)
        if val is None:
            kind = "none"
        else:
            sval = str(val).strip()
            if sval == "":
                kind = "empty"
            elif re.fullmatch(r"-?\d+", sval):
                kind = "num"
            elif _norm(sval) in {"true", "false"}:
                kind = "bool"
            else:
                kind = "text"
        buckets.append(f"{v}:{kind}")
    return "|".join(buckets)


def _empty_model(process_name: str) -> Dict[str, Any]:
    return {
        "title": f"{process_name} - Flujo cronologico funcional",
        "subtitle": "Reconstruccion funcional cronologica desde TWX",
        "process_identity": {"process_name": process_name, "root_artifact_id": None},
        "stages": [],
        "functional_stages": [],
        "transitions": [],
        "decisions": [],
        "contexts": [],
        "id_resolutions": [],
        "loop_patterns": [],
        "lineage_graph": {"nodes": [], "edges": []},
        "traversal_traces": [],
        "technical_evidence_model": {},
        "evidence_index": [],
        "ambiguities": [{"kind": "no_processes_detected", "detail": "No se detectaron procesos en el TWX", "confidence": CONF_NO_LOCALIZADA}],
    }


def _stage_key(
    name: str,
    sid: str,
    node: Optional[Dict[str, Any]] = None,
    process_id: Optional[str] = None,
    root_process_id: Optional[str] = None,
) -> str:
    n = node or {}
    ntype = n.get("node_type", "")
    nsub = n.get("node_subtype", "")
    is_root = bool(process_id and root_process_id and process_id == root_process_id)
    if ntype == "event" and n.get("is_exit") and is_root:
        return "fin"

    base = _clean_stage_name(name or "")
    base_norm = re.sub(r"[^a-z0-9]+", "-", _norm(base)).strip("-")
    if not base_norm:
        base_norm = "subetapa"

    if n.get("attached_process_id"):
        role = "subproceso"
    elif n.get("is_user_action_candidate"):
        role = "accion"
    elif ntype == "event" and n.get("is_exit"):
        role = "fin-interno"
    elif ntype == "gateway":
        role = "gateway"
    else:
        role = nsub or ntype or "stage"
    role_norm = re.sub(r"[^a-z0-9]+", "-", _norm(role)).strip("-")
    if role_norm and role_norm not in base_norm:
        return f"{base_norm}-{role_norm}"
    return base_norm


def _display_safe_condition(raw: str) -> str:
    text = _clean(raw or "")
    if not text:
        return ""
    if text.lower().startswith("condition_ref:"):
        return ""
    if _contains_technical_token(text):
        return ""
    return text


def _contains_technical_token(text: str) -> bool:
    t = _norm(text)
    return any(
        (
            "condition_ref" in t,
            "bpdid" in t,
            "guid" in t,
            "nodeid" in t,
            "flowid" in t,
            "source_node_id" in t,
            "caller_node_id" in t,
            "caller_process_id" in t,
            "xml path" in t,
            "script " in t,
        )
    )


def _canonical_context_signature(
    process_id: str,
    node_id: str,
    caller_process_id: Optional[str],
    caller_node_id: Optional[str],
    context_tags: List[str],
    path_conditions: List[str],
    scope_snapshot: Dict[str, Any],
) -> Tuple[str, str, List[str]]:
    safe_conds = _dedupe_strings([_display_safe_condition(c) for c in (path_conditions or []) if _display_safe_condition(c)])[:4]
    scope_keys = sorted((scope_snapshot or {}).keys())[:8]
    caller = "root" if not caller_process_id else "subprocess-call"
    labels = []
    if caller == "root":
        labels.append("proceso principal")
    else:
        labels.append("invocado por subproceso")
    if any("subprocess:" in (x or "") for x in (context_tags or [])):
        labels.append("contexto anidado")
    if safe_conds:
        labels.append(f"{len(safe_conds)} condicion(es)")
    label = " | ".join(labels)
    key_raw = f"{process_id}|{node_id}|{caller}|{','.join(safe_conds)}|{','.join(scope_keys)}"
    key = re.sub(r"[^a-z0-9|,]+", "-", _norm(key_raw)).strip("-")
    return key, label, safe_conds


def _classify_transition_semantics(
    from_stage: str,
    to_stage: str,
    base_kind: str,
    is_back_edge: bool,
    has_condition: bool,
) -> str:
    if base_kind in {"parallel", "join"}:
        return base_kind
    if is_back_edge and from_stage == to_stage:
        return "reprocess"
    if is_back_edge:
        return "retry" if has_condition else "loop_back"
    if from_stage == to_stage:
        return "reprocess"
    return base_kind or "normal"


def _clean_stage_name(name: str) -> str:
    t = _clean(name)
    t = re.sub(r"^(SP|MP)\s+", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s{2,}", " ", t).strip()
    return t or "Subetapa"


def _is_noise_name(name: str) -> bool:
    n = _norm(name)
    if not n:
        return True
    if n in {"iniciar", "inicio", "start", "test", "logs", "log", "sin titulo1", "sin título1", "untitled1", "data ini"}:
        return True
    if re.fullmatch(r"[0-9a-f.\-]{8,}", n):
        return True
    return False


def _clean(v: str) -> str:
    return " ".join((v or "").replace("\r", " ").replace("\n", " ").split())


def _norm(s: str) -> str:
    t = unicodedata.normalize("NFD", (s or "").lower())
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Mn")
    return " ".join(t.split())


def _dedupe_strings(items: List[str]) -> List[str]:
    out = []
    seen = set()
    for x in items:
        k = _norm(str(x))
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(str(x))
    return out


def _dedupe_dicts(items: List[Dict[str, Any]], keys: Tuple[str, ...]) -> List[Dict[str, Any]]:
    out = []
    seen = set()
    for d in items:
        k = tuple(_norm(str(d.get(kk, ""))) for kk in keys)
        if k in seen:
            continue
        seen.add(k)
        out.append(d)
    return out
