from __future__ import annotations

from typing import Any, Dict
from html_fallback import render_html


def translate_business_model(state: Dict[str, Any]) -> Dict[str, Any]:
    model = _fallback_model(state)
    return {"functional_model": model}


def generate_html_agent(state: Dict[str, Any]) -> Dict[str, Any]:
    html = render_html(state.get("functional_model", {}), state)
    return {"html": html}


def _fallback_model(state: Dict[str, Any]) -> Dict[str, Any]:
    stages = []
    node_name = {n["id"]: n.get("name", n["id"]) for n in state.get("graph_nodes", [])}
    out_map = {}
    for e in state.get("graph_edges", []):
        out_map.setdefault(e["source"], []).append(e)

    for i, n in enumerate(state.get("graph_nodes", []), start=1):
        routes = []
        for e in out_map.get(n["id"], []):
            routes.append(f'{e.get("label","Transicion")} -> {node_name.get(e["target"], e["target"])}')
        stages.append(
            {
                "id": f"s{i}",
                "display_id": n["id"],
                "name": n.get("name", n["id"]),
                "tag": n.get("artifact_type", "artifact"),
                "routes": routes or ["Sin rutas salientes detectadas"],
                "groups": [],
            }
        )
    return {
        "title": "Flujo cronologico funcional de subetapas",
        "subtitle": "Vista compacta para negocio",
        "stages": stages,
    }
