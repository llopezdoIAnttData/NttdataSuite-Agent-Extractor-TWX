from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import networkx as nx


def build_execution_graph(
    artifacts: Dict[str, Any], manifest: Dict[str, Any]
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Optional[str], List[Dict[str, Any]], List[str], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """
    Construye:
    - vista legacy de nodos/aristas (compatibilidad)
    - grafo técnico enriquecido:
      - control_flow_graphs por proceso
      - call_graph entre procesos
      - technical_graph unificado
    """
    unresolved: List[Dict[str, Any]] = []
    warnings: List[str] = []

    processes = _collect_process_models(artifacts)
    root = _guess_root(artifacts, manifest)
    if not root:
        warnings.append("No se pudo inferir root_id")

    call_graph = _build_call_graph(processes, unresolved)
    control_flow_graphs = _build_control_flow_graphs(processes, unresolved)
    technical_graph = _build_technical_graph(processes, control_flow_graphs, call_graph)

    # salida legacy para compatibilidad con fases anteriores / auditoría
    legacy_nodes, legacy_edges = _build_legacy_projection(artifacts, control_flow_graphs, call_graph, root)
    return legacy_nodes, legacy_edges, root, unresolved, warnings, technical_graph, call_graph, control_flow_graphs


def _collect_process_models(artifacts: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for aid, a in artifacts.items():
        pm = a.get("process_model")
        if not pm:
            continue
        pid = pm.get("process_id") or aid
        out[pid] = pm
    return out


def _build_call_graph(processes: Dict[str, Dict[str, Any]], unresolved: List[Dict[str, Any]]) -> Dict[str, Any]:
    cg = nx.DiGraph()
    for pid, pm in processes.items():
        cg.add_node(pid, process_name=pm.get("process_name", pid))

    for pid, pm in processes.items():
        for n in pm.get("nodes", []):
            child = (n.get("attached_process_id") or "").strip().strip("/")
            if not child:
                continue
            if child not in processes:
                unresolved.append(
                    {
                        "source": pid,
                        "field": "attachedProcessId",
                        "raw_value": child,
                        "source_node_id": n.get("node_id"),
                    }
                )
                continue
            cg.add_edge(
                pid,
                child,
                call_node_id=n.get("node_id"),
                call_node_name=n.get("name", ""),
                input_mappings=[m for m in n.get("mappings", []) if m.get("direction") == "input"],
                output_mappings=[m for m in n.get("mappings", []) if m.get("direction") == "output"],
            )
    return _to_graph_dict(cg)


def _build_control_flow_graphs(processes: Dict[str, Dict[str, Any]], unresolved: List[Dict[str, Any]]) -> Dict[str, Any]:
    cfgs: Dict[str, Any] = {}
    for pid, pm in processes.items():
        g = nx.DiGraph()

        node_by_id = {n.get("node_id"): n for n in pm.get("nodes", []) if n.get("node_id")}
        for nid, n in node_by_id.items():
            g.add_node(
                nid,
                node_name=n.get("name", nid),
                node_type=n.get("node_type", "activity"),
                node_subtype=n.get("node_subtype", ""),
                implementation_type=n.get("implementation_type", ""),
                gateway_type=n.get("gateway_type", ""),
                split_join_type=n.get("split_join_type", ""),
                is_entry=bool(n.get("is_entry")),
                is_exit=bool(n.get("is_exit")),
                is_user_action_candidate=bool(n.get("is_user_action_candidate")),
                attached_process_id=n.get("attached_process_id", ""),
                attached_activity_id=n.get("attached_activity_id", ""),
                mappings=n.get("mappings", []),
                assignments=n.get("assignments", []),
                conditions=n.get("conditions", []),
                ui_rules=n.get("ui_rules", []),
            )

        for f in pm.get("flows", []):
            src = f.get("source_node_id")
            tgt = f.get("target_node_id")
            if not src or not tgt:
                unresolved.append(
                    {
                        "source": pid,
                        "field": "flow_bind",
                        "raw_value": f.get("flow_id"),
                        "detail": "source/target incompleto",
                    }
                )
                continue
            if src not in node_by_id or tgt not in node_by_id:
                unresolved.append(
                    {
                        "source": pid,
                        "field": "flow_bind",
                        "raw_value": f.get("flow_id"),
                        "detail": f"source={src} target={tgt}",
                    }
                )
                continue
            g.add_edge(
                src,
                tgt,
                edge_type="sequence_flow",
                flow_id=f.get("flow_id", ""),
                condition_ref=f.get("condition_ref", ""),
                condition_expression=f.get("condition_expression", ""),
                connection_type=f.get("connection_type", ""),
                evidence=f.get("evidence", {}),
            )

        cfgs[pid] = _to_graph_dict(g)
    return cfgs


def _build_technical_graph(processes: Dict[str, Dict[str, Any]], cfgs: Dict[str, Any], call_graph: Dict[str, Any]) -> Dict[str, Any]:
    tg = nx.DiGraph()

    for pid, pm in processes.items():
        proc_key = f"proc::{pid}"
        tg.add_node(proc_key, kind="process", process_id=pid, process_name=pm.get("process_name", pid))
        cfg = cfgs.get(pid, {})
        for n in cfg.get("nodes", []):
            nid = n.get("id")
            nk = f"node::{pid}::{nid}"
            tg.add_node(nk, kind="node", process_id=pid, node_id=nid, **{k: v for k, v in n.items() if k != "id"})
            tg.add_edge(proc_key, nk, edge_type="contains")
        for e in cfg.get("edges", []):
            sk = f"node::{pid}::{e.get('source')}"
            tk = f"node::{pid}::{e.get('target')}"
            if tg.has_node(sk) and tg.has_node(tk):
                attrs = {k: v for k, v in e.items() if k not in {"source", "target", "edge_type"}}
                tg.add_edge(sk, tk, edge_type="control_flow", **attrs)

    for e in call_graph.get("edges", []):
        s = f"proc::{e.get('source')}"
        t = f"proc::{e.get('target')}"
        if not tg.has_node(s) or not tg.has_node(t):
            continue
        tg.add_edge(
            s,
            t,
            edge_type="invoke_subprocess",
            call_node_id=e.get("call_node_id", ""),
            call_node_name=e.get("call_node_name", ""),
            input_mappings=e.get("input_mappings", []),
            output_mappings=e.get("output_mappings", []),
        )

    return _to_graph_dict(tg)


def _build_legacy_projection(
    artifacts: Dict[str, Any], cfgs: Dict[str, Any], call_graph: Dict[str, Any], root_id: Optional[str]
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    nodes = []
    edges = []

    process_ids = set(cfgs.keys())
    for aid, a in artifacts.items():
        is_process = aid in process_ids
        nodes.append(
            {
                "id": aid,
                "name": a.get("name", aid),
                "artifact_type": a.get("artifact_type", "artifact"),
                "source_file": a.get("source_file", ""),
                "is_root": bool(root_id and aid == root_id),
                "is_process": is_process,
            }
        )

    for ce in call_graph.get("edges", []):
        edges.append(
            {
                "source": ce.get("source"),
                "target": ce.get("target"),
                "transition_type": "invoke_subprocess",
                "label": "Invoca subproceso",
                "evidence": {"call_node_id": ce.get("call_node_id"), "call_node_name": ce.get("call_node_name", "")},
            }
        )

    for pid, cfg in cfgs.items():
        for e in cfg.get("edges", []):
            edges.append(
                {
                    "source": pid,
                    "target": pid,
                    "transition_type": "intra_process_flow",
                    "label": f"{e.get('source')} -> {e.get('target')}",
                    "evidence": {"flow_id": e.get("flow_id", ""), "condition_ref": e.get("condition_ref", "")},
                }
            )
    return nodes, edges


def _to_graph_dict(g: nx.DiGraph) -> Dict[str, Any]:
    return {
        "nodes": [{"id": n, **d} for n, d in g.nodes(data=True)],
        "edges": [{"source": s, "target": t, **d} for s, t, d in g.edges(data=True)],
    }


def _guess_root(artifacts: Dict[str, Any], manifest: Dict[str, Any]) -> Optional[str]:
    process_ids = [aid for aid, a in artifacts.items() if a.get("artifact_type") == "process"]
    if not process_ids:
        return None

    pname = (manifest.get("process_name") or "").lower()
    if pname:
        for aid in process_ids:
            if pname == artifacts[aid].get("name", "").lower():
                return aid
        for aid in process_ids:
            if pname in artifacts[aid].get("name", "").lower():
                return aid

    # Preferencia general para proceso principal por nombre
    scored = []
    for aid in process_ids:
        name = artifacts[aid].get("name", "").lower()
        pm = artifacts[aid].get("process_model") or {}
        node_count = len(pm.get("nodes", []))
        score = 0
        if any(k in name for k in ("mp", "main", "principal")):
            score += 5
        score += min(node_count, 50) / 10.0
        scored.append((score, aid))
    if scored:
        scored.sort(key=lambda x: (-x[0], x[1]))
        return scored[0][1]

    ranked = sorted(
        process_ids,
        key=lambda aid: (
            0 if any(k in artifacts[aid].get("name", "").lower() for k in ("mp", "main", "principal")) else 1,
            artifacts[aid].get("name", "").lower(),
        ),
    )
    return ranked[0]
