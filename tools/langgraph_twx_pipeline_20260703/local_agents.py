from __future__ import annotations

from typing import Any, Dict

from functional_model_builder import build_functional_model


def run_local_translation_agents(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Pipeline local sin LLM:
    - reconstruye modelo funcional consolidado desde artefactos + grafo
    - conserva trazabilidad para auditoría
    """
    return build_functional_model(state)
