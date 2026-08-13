from __future__ import annotations

import json
import os
import re
from typing import Any, Dict
from langchain_openai import ChatOpenAI
from prompts import BUSINESS_TRANSLATOR_SYSTEM, HTML_GENERATOR_SYSTEM
from html_fallback import render_html
from local_agents import run_local_translation_agents


def translate_business_model(state: Dict[str, Any]) -> Dict[str, Any]:
    if not os.getenv("OPENAI_API_KEY"):
        local_model = run_local_translation_agents(state)
        return {"functional_model": local_model}

    payload = {
        "process_name": state.get("manifest", {}).get("process_name") or "Proceso TWX",
        "nodes": state.get("graph_nodes", []),
        "edges": state.get("graph_edges", []),
    }
    prompt = (
        "Convierte el siguiente grafo tecnico TWX a JSON funcional consolidado. "
        "Devuelve SOLO JSON valido.\n\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    try:
        llm = ChatOpenAI(model=state.get("model", "gpt-4o-mini"), temperature=0.1)
        response = llm.invoke(
            [
                {"role": "system", "content": BUSINESS_TRANSLATOR_SYSTEM},
                {"role": "user", "content": prompt},
            ]
        )
        text = response.content if isinstance(response.content, str) else str(response.content)
        cleaned = _strip_code_fences(text, "json")
        model = _load_json_lenient(cleaned)
        if not _is_valid_functional_model(model):
            raise ValueError("JSON funcional inválido: faltan title/stages")
        return {"functional_model": model}
    except Exception as ex:
        fallback = _fallback_model(state)
        return {"functional_model": fallback, "warnings": [*state.get("warnings", []), f"Fallback traductor: {ex}"]}


def generate_html_agent(state: Dict[str, Any]) -> Dict[str, Any]:
    functional_model = state.get("functional_model", {})
    if not os.getenv("OPENAI_API_KEY"):
        return {"html": render_html(functional_model, state)}

    prompt = (
        "Genera HTML completo autocontenido a partir del siguiente JSON. "
        "Devuelve SOLO HTML valido.\n\n"
        + json.dumps(functional_model, ensure_ascii=False)
    )
    try:
        llm = ChatOpenAI(model=state.get("model", "gpt-4o-mini"), temperature=0.1)
        response = llm.invoke(
            [
                {"role": "system", "content": HTML_GENERATOR_SYSTEM},
                {"role": "user", "content": prompt},
            ]
        )
        html = response.content if isinstance(response.content, str) else str(response.content)
        html = _strip_code_fences(html, "html")
        if "<html" not in html.lower():
            raise ValueError("Respuesta no parece HTML")
        return {"html": html}
    except Exception as ex:
        html = render_html(functional_model, state)
        return {"html": html, "warnings": [*state.get("warnings", []), f"Fallback HTML: {ex}"]}


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


def _strip_code_fences(text: str, lang: str) -> str:
    """
    Limpia fences tipo ```json ... ``` o ```html ... ```
    """
    t = (text or "").strip()
    fence_lang = re.compile(rf"^```{lang}\s*(.*?)\s*```$", re.IGNORECASE | re.DOTALL)
    fence_any = re.compile(r"^```[a-zA-Z0-9_-]*\s*(.*?)\s*```$", re.DOTALL)
    m = fence_lang.match(t)
    if m:
        return m.group(1).strip()
    m2 = fence_any.match(t)
    if m2:
        return m2.group(1).strip()
    return t


def _is_valid_functional_model(model: Dict[str, Any]) -> bool:
    return isinstance(model, dict) and isinstance(model.get("title"), str) and isinstance(model.get("stages"), list)


def _load_json_lenient(text: str) -> Dict[str, Any]:
    try:
        return json.loads(text)
    except Exception:
        # intenta extraer bloque JSON principal
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise
