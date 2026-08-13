from __future__ import annotations

import re
import unicodedata
from collections import deque
from typing import Any, Dict, List

from langchain_core.runnables import RunnableLambda


def run_local_translation_agents(state: Dict[str, Any]) -> Dict[str, Any]:
    chain = (
        RunnableLambda(_collect_context)
        | RunnableLambda(_extract_stage_candidates)
        | RunnableLambda(_curate_stages)
        | RunnableLambda(_build_functional_model)
    )
    return chain.invoke(state)


def _collect_context(state: Dict[str, Any]) -> Dict[str, Any]:
    nodes = state.get("graph_nodes", [])
    edges = state.get("graph_edges", [])
    root_id = state.get("root_id")
    manifest = state.get("manifest", {})
    artifacts = state.get("artifacts", {})

    by_id = {n["id"]: n for n in nodes if n.get("id")}
    out_map: Dict[str, List[Dict[str, Any]]] = {}
    for e in edges:
        out_map.setdefault(e.get("source", ""), []).append(e)

    order = _traversal_order(by_id, out_map, root_id)
    return {
        "process_name": manifest.get("process_name"),
        "by_id": by_id,
        "out_map": out_map,
        "order": order,
        "artifacts": artifacts,
    }


def _extract_stage_candidates(ctx: Dict[str, Any]) -> Dict[str, Any]:
    candidates = []
    by_id = ctx["by_id"]
    out_map = ctx["out_map"]
    artifacts = ctx["artifacts"]
    for aid in ctx["order"]:
        n = by_id.get(aid, {})
        name = (n.get("name") or aid).strip()
        if _is_noise_name(name):
            continue

        routes = []
        for e in out_map.get(aid, []):
            target = by_id.get(e.get("target"), {})
            t_name = (target.get("name") or e.get("target") or "").strip()
            if _is_noise_name(t_name):
                continue
            label = (e.get("label") or "Transicion").strip()
            routes.append(f"{label} -> {t_name}")
        routes = _dedupe(routes)

        a = artifacts.get(aid, {})
        analysis = a.get("analysis", {}) if isinstance(a, dict) else {}
        snippets = a.get("text_snippets", [])[:8]
        score = _stage_score(name, n.get("artifact_type", ""), routes, snippets, analysis)
        candidates.append(
            {
                "id": aid,
                "display_id": aid,
                "name": name,
                "tag": n.get("artifact_type", "artifact"),
                "routes": routes or ["Sin transiciones relevantes detectadas"],
                "snippets": snippets,
                "analysis": analysis,
                "score": score,
            }
        )
    ctx["candidates"] = candidates
    return ctx


def _curate_stages(ctx: Dict[str, Any]) -> Dict[str, Any]:
    candidates = sorted(ctx["candidates"], key=lambda x: x["score"], reverse=True)
    curated = []
    seen = set()
    has_finalize = False
    for c in candidates:
        if _norm(c["name"]) in {"finalizar", "end", "fin"}:
            has_finalize = True
        key = _norm(c["name"])
        if key in seen:
            continue
        seen.add(key)
        curated.append(c)
        if len(curated) >= 36:
            break

    # fallback de seguridad por si todo fue filtrado
    if not curated:
        curated = ctx["candidates"][:36]

    must_keywords = [
        "inco",
        "idc",
        "coincidencia de saldos",
        "revision saldos no coincidentes",
        "matriz de conviv",
        "revision de matriz",
        "calcular bono de pension",
        "revision cifras control",
        "generar cifras control",
        "archivo respuesta",
        "consulta archivo respuesta",
        "revision de errores archivo respuesta",
        "generacion de movimientos",
        "confirmacion de movimientos",
        "autorizar movimientos",
        "acreditar movimientos",
        "actualizar indicadores",
        "desmarca nci",
        "desmarcar cuentas",
        "archivo de intercambio",
        "cifras historico",
    ]
    for c in candidates:
        n = _norm(c["name"])
        if not any(k in n for k in must_keywords):
            continue
        key = _norm(c["name"])
        if key in seen:
            continue
        seen.add(key)
        curated.append(c)

    if has_finalize and not any(_norm(s["name"]) in {"fin", "end"} for s in curated):
        curated.append(
            {
                "id": "synthetic.fin",
                "display_id": "FIN",
                "name": "Fin",
                "tag": "process",
                "routes": ["Termino del proceso"],
                "snippets": [],
                "score": 0,
            }
        )

    # ordenar por flujo original para conservar narrativa
    order_index = {aid: i for i, aid in enumerate(ctx["order"])}
    curated = sorted(curated, key=lambda x: order_index.get(x["id"], 10**9))
    ctx["curated"] = curated
    return ctx


def _build_functional_model(ctx: Dict[str, Any]) -> Dict[str, Any]:
    stages = []
    for i, c in enumerate(ctx["curated"], start=1):
        code = _extract_business_code(c.get("snippets", []), c["name"], c["display_id"], c.get("analysis", {}))
        stages.append(
            {
                "id": f"s{i}",
                "display_id": c["display_id"],
                "business_code": code,
                "name": c["name"],
                "tag": c["tag"],
                "routes": c["routes"][:10],
                "groups": _build_groups(c),
            }
        )

    process_name = (ctx.get("process_name") or "").strip()
    if process_name:
        title = f"{process_name} - Flujo cronologico funcional"
    else:
        title = "Flujo cronologico funcional de subetapas"

    return {
        "title": title,
        "subtitle": "Vista compacta para negocio (agentes locales LangChain, sin API key)",
        "stages": stages,
    }


def _traversal_order(by_id: Dict[str, Dict[str, Any]], out_map: Dict[str, List[Dict[str, Any]]], root_id: str | None) -> List[str]:
    ordered: List[str] = []
    seen = set()

    def bfs(start: str) -> None:
        q = deque([start])
        while q:
            node = q.popleft()
            if node in seen or node not in by_id:
                continue
            seen.add(node)
            ordered.append(node)
            for e in out_map.get(node, []):
                tgt = e.get("target")
                if tgt and tgt not in seen:
                    q.append(tgt)

    if root_id:
        bfs(root_id)
    for aid in by_id:
        if aid not in seen:
            bfs(aid)
    return ordered


def _stage_score(name: str, tag: str, routes: List[str], snippets: List[str], analysis: Dict[str, Any]) -> int:
    n = _norm(name)
    score = 0
    if tag in {"process", "service", "uca_bus", "gateway_or_rules"}:
        score += 4
    if routes:
        score += min(len(routes), 4)
    if any(
        k in n
        for k in (
            "revision",
            "valid",
            "calcular",
            "gener",
            "archivo",
            "movimiento",
            "cifras",
            "bono",
            "inco",
            "idc",
            "matriz",
            "coincid",
            "autorizar",
            "acreditar",
            "desmarca",
            "intercambio",
            "historico",
            "notificacion",
            "actualizar indicadores",
        )
    ):
        score += 6
    if analysis.get("visibility_rules"):
        score += 3
    if analysis.get("conditions"):
        score += 2
    if analysis.get("actions"):
        score += 2
    if any("tw.resource" in _norm(s) for s in snippets):
        score -= 3
    if _is_noise_name(name):
        score -= 10
    return score


def _is_noise_name(name: str) -> bool:
    n = _norm(name)
    if len(n) < 4:
        return True
    if re.fullmatch(r"[0-9a-f.\-]{8,}", n):
        return True
    if n in {
        "success",
        "error",
        "end",
        "finalizar",
        "test",
        "folio",
        "acciones",
        "sin titulo1",
        "untitled1",
        "data ini",
    }:
        return True
    return False


def _norm(s: str) -> str:
    t = unicodedata.normalize("NFD", (s or "").lower())
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Mn")
    return " ".join(t.split())


def _dedupe(items: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for i in items:
        k = _norm(i)
        if not i or k in seen:
            continue
        seen.add(k)
        out.append(i)
    return out


def _extract_business_code(snippets: List[str], name: str, display_id: str, analysis: Dict[str, Any]) -> str:
    for raw in analysis.get("id_subetapa_values", []):
        nums = re.findall(r"\b\d{3,5}\b", str(raw))
        if nums:
            return nums[0]
        env_match = re.search(r"tw\.env\.([A-Z0-9_]+)", str(raw))
        if env_match:
            token = env_match.group(1)
            if token.startswith("ID_SUBETAPA_"):
                return token.replace("ID_SUBETAPA_", "")

    joined = " ".join([name, display_id, *snippets])
    nums = re.findall(r"\b\d{3,5}\b", joined)
    preferred = [n for n in nums if 20 <= int(n) <= 9999]
    if preferred:
        for n in preferred:
            if int(n) >= 1000:
                return n
        return preferred[0]
    if display_id and "." in display_id:
        return display_id.split(".", 1)[0]
    return ""


def _build_groups(stage: Dict[str, Any]) -> List[Dict[str, Any]]:
    analysis = stage.get("analysis", {}) or {}
    groups: List[Dict[str, Any]] = []
    action_names = [a for a in analysis.get("actions", []) if a]
    conditions = [c for c in analysis.get("conditions", []) if c]
    vis_rules = [v for v in analysis.get("visibility_rules", []) if v]
    params = {p for p in analysis.get("parameters", []) if isinstance(p, str)}

    if action_names:
        groups.append(
            {
                "title": "Botones / acciones detectadas",
                "meta": "Detectadas desde eventLabel/name en artefactos",
                "note": "",
                "routes": [f"{a}" for a in action_names[:8]],
            }
        )

    if vis_rules:
        groups.append(
            {
                "title": "Reglas de visibilidad",
                "meta": "Variables UI de Coach",
                "note": "",
                "routes": vis_rules[:6],
            }
        )

    # Caso rico detectado en Revision Cifras Control: generar 3 tiempos.
    n = _norm(stage.get("name", ""))
    if "revision cifras control" in n and "isGeneroArchivoRespuesta" in params and "isMovCargo" in params:
        groups.extend(
            [
                {
                    "title": "Botones - Tiempo 1",
                    "meta": "Estado inicial",
                    "note": "",
                    "routes": [
                        "Generar OP (habilitado si isGeneroArchivoRespuesta == false)",
                        "Generar Movimientos Cargo (deshabilitado si isGeneroArchivoRespuesta == false)",
                        "Generar Movimientos Abono (deshabilitado si isMovCargo == false)",
                        "Reprocesar / Rechazar habilitado mientras no se complete OP/Cargo",
                    ],
                },
                {
                    "title": "Botones - Tiempo 2",
                    "meta": "OP generado, cargo pendiente",
                    "note": "",
                    "routes": [
                        "Generar OP (deshabilitado si isGeneroArchivoRespuesta == true)",
                        "Generar Movimientos Cargo (habilitado si isGeneroArchivoRespuesta == true AND isMovCargo == false)",
                        "Reprocesar / Rechazar habilitado si isMovCargo == false",
                    ],
                },
                {
                    "title": "Botones - Tiempo 3",
                    "meta": "Cargo generado",
                    "note": "",
                    "routes": [
                        "Generar Movimientos Cargo (deshabilitado si isMovCargo == true)",
                        "Generar Movimientos Abono (habilitado si isMovCargo == true)",
                        "Reprocesar / Rechazar deshabilitado cuando OP y cargo ya se completaron",
                    ],
                },
            ]
        )

    if conditions:
        groups.append(
            {
                "title": "Condiciones detectadas",
                "meta": "Extraidas de sequenceFlow/expresiones",
                "note": "",
                "routes": conditions[:8],
            }
        )

    return groups[:5]
