from __future__ import annotations

import os
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


REFERENCE_TAGS = {"attachedprocessid", "sourcenodeid", "targetnodeid", "flowid"}
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
    """
    Extracción segura contra zip-slip.
    """
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

    env: Dict[str, str] = {}
    process_name = None

    for e in root.iter():
        name = _lname(e)
        text = (e.text or "").strip()
        if not process_name and name in {"name", "displayname", "processname"} and text:
            process_name = text

        if name in {"environmentvariable", "variable"}:
            k, v = None, ""
            for c in list(e):
                cn = _lname(c)
                ct = (c.text or "").strip()
                if cn in {"name", "key"}:
                    k = ct
                elif cn in {"value", "defaultvalue"}:
                    v = ct
            if k:
                env[k] = v

    result["process_name"] = process_name
    result["environment_variables"] = env
    return result, warnings


def parse_xml_artifacts_recursive(extracted_dir: str) -> Tuple[Dict[str, Any], List[str]]:
    artifacts: Dict[str, Any] = {}
    warnings: List[str] = []

    for root, _, files in os.walk(extracted_dir):
        for fn in files:
            if not fn.lower().endswith(".xml"):
                continue
            path = os.path.join(root, fn)
            try:
                tree = ET.parse(path)
                xroot = tree.getroot()
                artifact = _catalog_artifact(xroot, path, extracted_dir)
                # no pisar silenciosamente: conservar ambos en caso de colisión
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
    snippets = _collect_text_snippets(root, limit=20, min_len=3)

    return {
        "artifact_id": _norm_ref(artifact_id),
        "name": name,
        "artifact_type": artifact_type,
        "source_file": rel,
        "tags": tags,
        "references": refs,
        "text_snippets": snippets,
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

    # deduplicar conservando orden
    for k in out:
        seen = set()
        ordered = []
        for v in out[k]:
            if v not in seen:
                ordered.append(v)
                seen.add(v)
        out[k] = ordered
    return out


def _collect_text_snippets(root: ET.Element, limit: int = 20, min_len: int = 3) -> List[str]:
    snippets: List[str] = []
    for e in root.iter():
        t = (e.text or "").strip()
        if len(t) >= min_len and t not in snippets:
            snippets.append(t)
            if len(snippets) >= limit:
                break
    return snippets


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

