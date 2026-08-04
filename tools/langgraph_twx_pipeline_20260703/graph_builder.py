from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import networkx as nx


def build_execution_graph(
    artifacts: Dict[str, Any], manifest: Dict[str, Any]
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Optional[str], List[Dict[str, Any]], List[str]]:
    """
    Grafo auditable:
    - nodos con metadata
    - aristas solo con evidencia real
    - referencias no resueltas
    """
    g = nx.DiGraph()
    unresolved: List[Dict[str, Any]] = []
    warnings: List[str] = []

    by_id = {aid: aid for aid in artifacts.keys()}

    for aid, a in artifacts.items():
        g.add_node(
            aid,
            name=a.get("name", aid),
            artifact_type=a.get("artifact_type", "artifact"),
            source_file=a.get("source_file", ""),
        )

    for aid, a in artifacts.items():
        refs = a.get("references", {})
        source_file = a.get("source_file", "")

        # referencias por tags
        for field in ("attachedProcessId", "sourceNodeId", "targetNodeId", "flowId"):
            for raw in refs.get(field, []):
                target = _normalize_ref(raw, by_id)
                if target:
                    transition_type = _map_field_to_transition(field)
                    label = _map_field_to_label(field)
                    g.add_edge(
                        aid,
                        target,
                        transition_type=transition_type,
                        label=label,
                        evidence={
                            "source_file": source_file,
                            "field": field,
                            "raw_value": raw,
                        },
                    )
                else:
                    unresolved.append(
                        {
                            "source": aid,
                            "field": field,
                            "raw_value": raw,
                            "source_file": source_file,
                        }
                    )

        # referencias por atributos capturadas como "attr:value"
        for encoded in refs.get("attributes", []):
            if ":" not in encoded:
                continue
            field, raw = encoded.split(":", 1)
            target = _normalize_ref(raw, by_id)
            if target:
                g.add_edge(
                    aid,
                    target,
                    transition_type="reference",
                    label=f"Referencia {field}",
                    evidence={
                        "source_file": source_file,
                        "field": field,
                        "raw_value": raw,
                    },
                )
            else:
                unresolved.append(
                    {
                        "source": aid,
                        "field": field,
                        "raw_value": raw,
                        "source_file": source_file,
                    }
                )

    root = _guess_root(artifacts, manifest)
    if root and root in g.nodes:
        g.nodes[root]["is_root"] = True
    elif not root:
        warnings.append("No se pudo inferir root_id")

    nodes = [
        {
            "id": n,
            "name": d.get("name", n),
            "artifact_type": d.get("artifact_type", "artifact"),
            "source_file": d.get("source_file", ""),
            "is_root": bool(d.get("is_root")),
        }
        for n, d in g.nodes(data=True)
    ]

    edges = []
    for s, t, d in g.edges(data=True):
        edges.append(
            {
                "source": s,
                "target": t,
                "transition_type": d.get("transition_type", "unknown"),
                "label": d.get("label", ""),
                "evidence": d.get("evidence", {}),
            }
        )

    return nodes, edges, root, unresolved, warnings


def _normalize_ref(raw: str, by_id: Dict[str, str]) -> Optional[str]:
    if not raw:
        return None
    norm = raw.strip().strip("/")
    if norm in by_id:
        return by_id[norm]
    # fallback por sufijo
    for aid in by_id:
        if aid.endswith(norm):
            return aid
    return None


def _map_field_to_transition(field: str) -> str:
    mapping = {
        "attachedProcessId": "invoke_subprocess",
        "sourceNodeId": "flow_source_ref",
        "targetNodeId": "flow_target_ref",
        "flowId": "flow_ref",
    }
    return mapping.get(field, "reference")


def _map_field_to_label(field: str) -> str:
    mapping = {
        "attachedProcessId": "Invoca subproceso",
        "sourceNodeId": "Referencia nodo origen",
        "targetNodeId": "Referencia nodo destino",
        "flowId": "Referencia de flujo",
    }
    return mapping.get(field, "Referencia")


def _guess_root(artifacts: Dict[str, Any], manifest: Dict[str, Any]) -> Optional[str]:
    process_ids = [aid for aid, a in artifacts.items() if a.get("artifact_type") == "process"]
    if not process_ids:
        return None

    pname = (manifest.get("process_name") or "").lower()
    if pname:
        for aid in process_ids:
            if pname in artifacts[aid].get("name", "").lower():
                return aid

    ranked = sorted(
        process_ids,
        key=lambda aid: (
            0 if any(k in artifacts[aid].get("name", "").lower() for k in ("mp", "main", "principal")) else 1,
            artifacts[aid].get("name", "").lower(),
        ),
    )
    return ranked[0]

