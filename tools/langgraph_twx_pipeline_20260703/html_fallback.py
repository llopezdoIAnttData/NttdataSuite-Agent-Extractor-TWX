from __future__ import annotations

from typing import Any, Dict, List


def render_html(model: Dict[str, Any], state: Dict[str, Any] | None = None) -> str:
    state = state or {}
    title = model.get("title", "Flujo cronologico funcional de subetapas")
    subtitle = model.get("subtitle", "Vista compacta para negocio")

    stages = model.get("functional_stages") or []
    if not stages:
        stages = _from_legacy_stages(model.get("stages", []))

    stage_cards = []
    stage_label_by_key = {st.get("stage_key", ""): _toc_label(st) for st in stages}
    for st in stages:
        sname = _safe_text(st.get("functional_name", "Subetapa")) or "Subetapa"
        sids = _format_stage_ids(st.get("id_variants", []))
        header = f"[{sids}] {sname}" if sids else sname

        service_routes = _build_service_routes(st, stage_label_by_key)
        service_html = "".join(f"<li>{_esc(r)}</li>" for r in service_routes) or "<li>Sin salida funcional comprobada</li>"

        groups_html = ""
        for g in _build_action_groups(st, stage_label_by_key):
            lines = "".join(f"<li>{_esc(x)}</li>" for x in g.get("routes", []))
            meta = f'<div class="route-meta">{_esc(g.get("meta",""))}</div>' if g.get("meta") else ""
            note = f'<div class="route-note">{_esc(g.get("note",""))}</div>' if g.get("note") else ""
            groups_html += (
                '<div class="route-group">'
                f'<div class="route-title">{_esc(g.get("title","Botones"))}</div>{meta}{note}'
                f'<ul class="route-paths">{lines}</ul>'
                "</div>"
            )

        context_html = ""
        ctxs = st.get("contexts", []) or []
        if ctxs:
            ctx_lines = []
            for c in ctxs[:6]:
                label = _safe_text(c.get("label", ""))
                conds = [_safe_text(x) for x in (c.get("conditions", []) or []) if _safe_text(x)]
                if conds:
                    ctx_lines.append(f"{label}: {' | '.join(conds[:2])}")
                else:
                    ctx_lines.append(label)
            context_html = (
                '<div class="context-block">'
                '<div class="context-title">Contextos</div>'
                + "<ul>" + "".join(f"<li>{_esc(x)}</li>" for x in ctx_lines) + "</ul></div>"
            )

        stage_cards.append(
            f"""
            <section class="sec" id="{_esc(st.get('stage_key','stage'))}">
              <h2>Subetapa: {_esc(header)}</h2>
              <div class="body">
                <h3>UCA / Servicio</h3>
                <ul>{service_html}</ul>
                {groups_html}
                {context_html}
              </div>
            </section>
            """
        )

    toc = "\n".join(
        f'<a href="#{_esc(st.get("stage_key","stage"))}">{_esc(_toc_label(st))}</a>'
        for st in stages
    )

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{_esc(title)}</title>
  <style>
    :root{{--bg:#0d1117;--card:#161b22;--line:#30363d;--txt:#e6edf3;--muted:#8b949e;--acc:#58a6ff;}}
    *{{box-sizing:border-box}}
    body{{margin:0;background:var(--bg);color:var(--txt);font:14px/1.5 "Segoe UI",Arial,sans-serif}}
    header{{padding:18px 22px;background:#111827;border-bottom:1px solid var(--line)}}
    h1{{margin:0 0 6px;font-size:22px;color:var(--acc)}}
    .meta{{font-size:12px;color:var(--muted)}}
    .wrap{{max-width:1220px;margin:0 auto;padding:18px}}
    .toc{{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:8px;margin-bottom:16px}}
    .toc a{{display:block;text-decoration:none;color:#cfe8ff;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 10px}}
    .sec{{background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden;margin-bottom:12px}}
    .sec h2{{margin:0;padding:11px 13px;background:#1f2937;font-size:16px}}
    .body{{padding:12px 13px}}
    h3{{margin:10px 0 5px;font-size:13px;letter-spacing:.3px;text-transform:uppercase;color:#9fb7d6}}
    ul{{margin:0;padding-left:18px}}
    li{{margin:4px 0}}
    .route-group{{margin-top:10px;padding:10px 12px;border:1px solid #3a4553;border-radius:8px;background:#111827}}
    .route-title{{font-weight:700;color:#cfe8ff;margin-bottom:3px}}
    .route-meta{{font-size:12px;color:#b8c7dc}}
    .route-note{{margin-top:6px;font-size:12px;color:#ffd28a}}
    .route-paths{{margin-top:6px;padding-left:18px}}
    .route-paths li{{margin:4px 0}}
    .context-block{{margin-top:10px;padding:10px 12px;border:1px solid #3a4553;border-radius:8px;background:#111827}}
    .context-title{{font-weight:700;color:#cfe8ff;margin-bottom:6px}}
  </style>
</head>
<body>
  <header>
    <h1>{_esc(title)}</h1>
    <div class="meta">{_esc(subtitle)}</div>
  </header>

  <div class="wrap">
    <nav class="toc">{toc}</nav>
    {"".join(stage_cards)}
  </div>
</body>
</html>"""


def _from_legacy_stages(stages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for st in stages or []:
        out.append(
            {
                "stage_key": st.get("id", ""),
                "functional_name": st.get("name", "Subetapa"),
                "id_variants": ([{"id_value": st.get("display_id", ""), "context": "", "condition": ""}] if st.get("display_id") else []),
                "external_interactions": [
                    {
                        "source_type": "service",
                        "source_name": st.get("name", ""),
                        "resulting_paths": [{"condition": r, "destination_stage": "", "transition_kind": "normal"} for r in st.get("routes", [])],
                    }
                ],
                "actions": [],
                "contexts": [],
            }
        )
    return out


def _toc_label(st: Dict[str, Any]) -> str:
    name = _safe_text(st.get("functional_name", "Subetapa")) or "Subetapa"
    ids = _format_stage_ids(st.get("id_variants", []))
    return f"{name} [{ids}]" if ids else name


def _build_service_routes(stage: Dict[str, Any], stage_label_by_key: Dict[str, str]) -> List[str]:
    routes = []
    for ext in stage.get("external_interactions", []) or []:
        src = ext.get("source_type", "Servicio").upper().replace("_", "/")
        for rp in ext.get("resulting_paths", []) or []:
            cond = _safe_text(rp.get("condition", ""))
            dest = rp.get("destination_stage", "")
            tkind = rp.get("transition_kind", "")
            if dest == "fin":
                dest_label = "Fin"
            else:
                dest_label = stage_label_by_key.get(dest, dest)
            if tkind == "retry":
                routes.append(f"{src}: {cond} -> Reintentar {dest_label}".strip())
            elif cond:
                routes.append(f"{src}: {cond} -> {dest_label}")
            else:
                routes.append(f"{src}: -> {dest_label}")
    return _dedupe(routes)[:12]


def _build_action_groups(stage: Dict[str, Any], stage_label_by_key: Dict[str, str]) -> List[Dict[str, Any]]:
    groups = []
    for a in stage.get("actions", []) or []:
        name = _safe_text(a.get("action_name", "Accion")) or "Accion"
        validations = _validation_text(a.get("validations", {}))
        paths = a.get("resulting_paths", []) or []
        if len(paths) <= 1:
            rp = paths[0] if paths else {}
            cond = _safe_text(rp.get("condition", ""))
            dest_key = rp.get("destination_stage", "")
            dest = stage_label_by_key.get(dest_key, dest_key)
            tkind = rp.get("transition_kind", "")
            route = name
            if cond:
                route += f" ({cond})"
            if dest:
                if tkind == "retry":
                    route += f" -> Reintentar {dest}"
                else:
                    route += f" -> {dest}"
            groups.append({"title": "Botones", "meta": validations, "note": "", "routes": [route]})
        else:
            lines = []
            for rp in paths:
                cond = _safe_text(rp.get("condition", ""))
                dest_key = rp.get("destination_stage", "")
                dest = stage_label_by_key.get(dest_key, dest_key)
                tkind = rp.get("transition_kind", "")
                prefix = f"-> Reintentar {dest}" if tkind == "retry" else f"-> {dest}"
                lines.append(prefix + (f", si {cond}" if cond else ""))
            groups.append(
                {
                    "title": f"Botón: {name}",
                    "meta": validations,
                    "note": "Caminos alternativos: solo se ejecuta uno según condición",
                    "routes": lines,
                }
            )
    return groups[:10]


def _validation_text(v: Dict[str, Any]) -> str:
    chunks = []
    for k, lbl in (
        ("enabled_if", "habilitado si"),
        ("disabled_if", "deshabilitado si"),
        ("visible_if", "visible si"),
        ("hidden_if", "oculto si"),
        ("readonly_if", "solo lectura si"),
    ):
        vals = (v.get(k, []) or [])[:2]
        if vals:
            chunks.append(f"{lbl}: {' OR '.join(vals)}")
    return " | ".join(chunks)


def _format_stage_ids(variants: List[Dict[str, Any]]) -> str:
    parts = []
    for v in variants or []:
        vid = _safe_text((v.get("id_value") or "").strip())
        if not vid:
            continue
        ctx = _safe_text((v.get("context") or "").strip())
        if ctx:
            parts.append(f"{vid} ({ctx})")
        else:
            parts.append(vid)
    return " / ".join(parts[:4])


def _safe_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    low = text.lower()
    blocked = (
        "condition_ref",
        "bpdid",
        "guid",
        "caller_process_id",
        "caller_node_id",
        "nodeid",
        "flowid",
        "xml path",
        "script",
        "source_node_id",
    )
    if any(tok in low for tok in blocked):
        return ""
    return text


def _dedupe(items: List[str]) -> List[str]:
    out = []
    seen = set()
    for x in items:
        k = (x or "").strip().lower()
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(x)
    return out


def _esc(s: Any) -> str:
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
