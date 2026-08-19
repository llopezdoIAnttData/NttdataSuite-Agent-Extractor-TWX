from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class PipelineState(TypedDict, total=False):
    # inputs
    input_twx: str
    output_html: str
    model: str
    audit_dir: Optional[str]
    extract_dir: Optional[str]

    # extractor/indexer outputs
    extracted_dir: str
    manifest: Dict[str, Any]
    artifacts: Dict[str, Any]
    warnings: List[str]

    # graph builder outputs
    graph_nodes: List[Dict[str, Any]]
    graph_edges: List[Dict[str, Any]]
    root_id: Optional[str]
    unresolved_references: List[Dict[str, Any]]
    technical_graph: Dict[str, Any]
    call_graph: Dict[str, Any]
    control_flow_graphs: Dict[str, Any]

    # ai agent outputs
    functional_model: Dict[str, Any]
    functional_stages: List[Dict[str, Any]]
    transitions: List[Dict[str, Any]]
    decisions: List[Dict[str, Any]]
    contexts: List[Dict[str, Any]]
    evidence_index: List[Dict[str, Any]]
    ambiguities: List[Dict[str, Any]]
    technical_evidence_model: Dict[str, Any]
    lineage_graph: Dict[str, Any]
    traversal_traces: List[Dict[str, Any]]
    loop_patterns: List[Dict[str, Any]]
    id_resolutions: List[Dict[str, Any]]
    html: str

    # misc
    error: Optional[str]
