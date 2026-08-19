from __future__ import annotations

import json
import os
from typing import Any, Dict
from langgraph.graph import END, StateGraph

from state import PipelineState
from extractor import extract_twx, parse_manifest, parse_xml_artifacts_recursive
from graph_builder import build_execution_graph
from agents import translate_business_model, generate_html_agent


def node_extract_index(state: PipelineState) -> Dict[str, Any]:
    extracted_dir = extract_twx(state["input_twx"], state.get("extract_dir"))
    manifest, manifest_warnings = parse_manifest(extracted_dir)
    artifacts, artifact_warnings = parse_xml_artifacts_recursive(extracted_dir)
    warnings = [*manifest_warnings, *artifact_warnings]
    return {
        "extracted_dir": extracted_dir,
        "manifest": manifest,
        "artifacts": artifacts,
        "warnings": warnings,
    }


def node_build_graph(state: PipelineState) -> Dict[str, Any]:
    (
        nodes,
        edges,
        root_id,
        unresolved_references,
        graph_warnings,
        technical_graph,
        call_graph,
        control_flow_graphs,
    ) = build_execution_graph(state["artifacts"], state["manifest"])
    return {
        "graph_nodes": nodes,
        "graph_edges": edges,
        "root_id": root_id,
        "unresolved_references": unresolved_references,
        "technical_graph": technical_graph,
        "call_graph": call_graph,
        "control_flow_graphs": control_flow_graphs,
        "warnings": [*state.get("warnings", []), *graph_warnings],
    }


def node_translate(state: PipelineState) -> Dict[str, Any]:
    return translate_business_model(state)


def node_generate_html(state: PipelineState) -> Dict[str, Any]:
    return generate_html_agent(state)


def node_persist(state: PipelineState) -> Dict[str, Any]:
    out = state["output_html"]
    with open(out, "w", encoding="utf-8") as f:
        f.write(state["html"])
    _write_audit_files(state)
    return {}


def _write_audit_files(state: PipelineState) -> None:
    audit_dir = state.get("audit_dir")
    if not audit_dir:
        return
    os.makedirs(audit_dir, exist_ok=True)

    def dump_json(name: str, data: Any) -> None:
        with open(os.path.join(audit_dir, name), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    with open(os.path.join(audit_dir, "extracted_dir.txt"), "w", encoding="utf-8") as f:
        f.write(state.get("extracted_dir", ""))

    dump_json("manifest.json", state.get("manifest", {}))
    dump_json("artifacts.json", state.get("artifacts", {}))
    dump_json(
        "graph.json",
        {
            "root_id": state.get("root_id"),
            "nodes": state.get("graph_nodes", []),
            "edges": state.get("graph_edges", []),
            "unresolved_references": state.get("unresolved_references", []),
        },
    )
    dump_json("technical_graph.json", state.get("technical_graph", {}))
    dump_json("call_graph.json", state.get("call_graph", {}))
    dump_json("control_flow_graphs.json", state.get("control_flow_graphs", {}))
    dump_json("functional_model.json", state.get("functional_model", {}))
    dump_json("functional_stages.json", state.get("functional_model", {}).get("functional_stages", state.get("functional_stages", [])))
    dump_json("transitions.json", state.get("functional_model", {}).get("transitions", state.get("transitions", [])))
    dump_json("decisions.json", state.get("functional_model", {}).get("decisions", state.get("decisions", [])))
    dump_json("lineage_graph.json", state.get("functional_model", {}).get("lineage_graph", state.get("lineage_graph", {})))
    dump_json("traversal_traces.json", state.get("functional_model", {}).get("traversal_traces", state.get("traversal_traces", [])))
    dump_json("loop_patterns.json", state.get("functional_model", {}).get("loop_patterns", state.get("loop_patterns", [])))
    dump_json("id_resolutions.json", state.get("functional_model", {}).get("id_resolutions", state.get("id_resolutions", [])))
    dump_json("technical_evidence_model.json", state.get("functional_model", {}).get("technical_evidence_model", state.get("technical_evidence_model", {})))
    dump_json("ambiguities.json", state.get("functional_model", {}).get("ambiguities", state.get("ambiguities", [])))
    dump_json("evidence_index.json", state.get("functional_model", {}).get("evidence_index", state.get("evidence_index", [])))

    with open(os.path.join(audit_dir, "warnings.txt"), "w", encoding="utf-8") as f:
        warnings = state.get("warnings", [])
        unresolved = state.get("unresolved_references", [])
        if not warnings and not unresolved:
            f.write("Sin warnings\n")
            return
        for w in warnings:
            f.write(f"- {w}\n")
        if unresolved:
            f.write("\nReferencias no resueltas:\n")
            for u in unresolved:
                f.write(f"- {u}\n")


def build_app():
    g = StateGraph(PipelineState)
    g.add_node("extract_index", node_extract_index)
    g.add_node("build_graph", node_build_graph)
    g.add_node("translate", node_translate)
    g.add_node("generate_html", node_generate_html)
    g.add_node("persist", node_persist)

    g.set_entry_point("extract_index")
    g.add_edge("extract_index", "build_graph")
    g.add_edge("build_graph", "translate")
    g.add_edge("translate", "generate_html")
    g.add_edge("generate_html", "persist")
    g.add_edge("persist", END)

    return g.compile()
