from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List


def render_html(model: Dict[str, Any], state: Dict[str, Any] | None = None) -> str:
    state = state or {}
    title = model.get("title", "Flujo cronologico funcional de subetapas")
    subtitle = model.get("subtitle", "Vista compacta para negocio")
    stages = model.get("stages", [])

    def esc(s: str) -> str:
        return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    stage_rows = []
    for st in stages:
        name = str(st.get("name", "")).strip()
        if not name:
            continue
        stage_rows.append(
            {
                "name": name,
                "display_id": str(st.get("display_id", "N/A")),
                "business_code": str(st.get("business_code", "")).strip(),
                "routes": [str(r) for r in st.get("routes", [])],
                "groups": st.get("groups", []) if isinstance(st.get("groups", []), list) else [],
            }
        )

    def norm(s: str) -> str:
        s = unicodedata.normalize("NFD", s.lower())
        s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
        return " ".join(s.split())

    def is_noise(name: str) -> bool:
        n = norm(name)
        if re.fullmatch(r"[0-9a-f.\-]{8,}", n):
            return True
        if n in {"success", "error", "end", "finalizar", "test", "folio", "acciones", "sin titulo1", "untitled1"}:
            return True
        return len(n) < 4

    def normalize_route(route: str) -> str:
        r = route.strip()
        if "->" not in r:
            return r
        left, right = r.split("->", 1)
        target = right.strip()
        if is_noise(target):
            return left.strip()
        return f"{left.strip()} -> {target}"

    canonical = [
        ("inco", "INCO", ["inco"]),
        ("idc", "IDC", ["sp idc"]),
        ("rev-idc", "Revision IDC", ["revision idc"]),
        ("coin", "Coincidencia de Saldos", ["coincidencia de saldos"]),
        ("rev-coin", "Revision Coincidencia de Saldos", ["revision saldos no coincidentes", "revision coincid"]),
        ("matriz", "Matriz de Convivencia", ["matriz de conviv"]),
        ("rev-matriz", "Revision Matriz de Convivencia", ["revision de matriz"]),
        ("bono", "Bono de Pension", ["calcular bono de pension", "bono devengado y por devengar"]),
        ("rev-udi", "Revision Valor UDI", ["revision udi", "valor udi"]),
        ("gcc", "Generacion Cifras Control", ["generar cifras control", "cifras control bono devengado"]),
        ("rev-gcc", "Revision Cifras Control", ["revision cifras control", "is revision cifras"]),
        ("ar", "Archivo Respuesta", ["archivo respuesta op80", "archivo respuesta"]),
        ("rev-ar", "Revision Archivo Respuesta", ["consulta archivo respuesta"]),
        ("rev-ar-err", "Revision Archivo Respuesta Error", ["revision de errores archivo respuesta"]),
        ("gen-mov", "Generacion de Movimientos", ["generacion de movimientos"]),
        ("cmov", "Confirmacion de Movimientos", ["confirmacion de movimientos"]),
        ("autoriza", "Autorizacion de Movimientos", ["autorizar movimientos"]),
        ("acreditar", "Acreditar Movimientos", ["acreditar movimientos"]),
        ("actualiza", "Actualizacion de Indicadores", ["actualizar indicadores"]),
        ("desmarca", "Desmarca NCI / Desmarca de Cuentas", ["desmarca nci", "desmarcar cuentas"]),
        ("intercambio", "Archivo de Intercambio / CNDTI", ["archivo de intercambio", "ctindi"]),
        ("historico", "Resguardo Historico / Cifras Historico", ["cifras historico"]),
        ("fin", "Fin", ["fin", "finalizar", "end"]),
    ]

    used = set()
    sections = []

    def find_match(patterns: List[str]) -> Dict[str, Any] | None:
        for idx, st in enumerate(stage_rows):
            if idx in used:
                continue
            n = norm(st["name"])
            if any(p in n for p in patterns):
                used.add(idx)
                return st
        return None

    def find_unmatched_by_patterns(patterns: List[str]) -> Dict[str, Any] | None:
        for idx, st in enumerate(stage_rows):
            if idx in used:
                continue
            n = norm(st["name"])
            if any(p in n for p in patterns):
                used.add(idx)
                return st
        return None

    for sec_id, sec_title, patterns in canonical:
        st = find_match(patterns)
        if not st and sec_id == "rev-idc":
            st = find_unmatched_by_patterns(["idc"])
        if not st and sec_id == "rev-udi":
            st = find_unmatched_by_patterns(["inicio bono", "calcular bono"])
        if not st and sec_id == "fin":
            st = find_unmatched_by_patterns(["fin", "finalizar", "end"])

        if not st:
            sections.append(
                {
                    "id": sec_id,
                    "title": sec_title,
                    "label": sec_title,
                    "routes": ["No detectada claramente en este TWX"],
                    "groups": [],
                }
            )
            continue
        routes = [normalize_route(r) for r in st.get("routes", [])]
        routes = [r for r in routes if r] or ["Sin transiciones relevantes detectadas"]
        title_text = sec_title
        code = st.get("business_code")
        title_for_toc = title_text
        if code:
            title_text = f"{title_text} ({code})"
        label = f"[{st.get('display_id', 'N/A')}] {st.get('name', sec_title)}"
        sections.append(
            {
                "id": sec_id,
                "title": title_for_toc,
                "label": label,
                "routes": routes[:8],
                "groups": st.get("groups", [])[:6],
            }
        )

    title = "Redencion Bono - Flujo cronologico funcional de subetapas (contexto Copilot)"
    subtitle = "Vista compacta para negocio. Generado en modo agentes locales de Copilot (sin OPENAI_API_KEY)."
    toc = "\n".join(f'<a href="#{esc(sec["id"])}">{esc(sec["title"])}</a>' for sec in sections)
    cards = []
    for sec in sections:
        routes_html = "".join(f"<li>{esc(r)}</li>" for r in sec["routes"])
        groups_html = ""
        for g in sec.get("groups", []):
            gr = "".join(f"<li>{esc(r)}</li>" for r in g.get("routes", []))
            meta = f'<div class="route-meta">{esc(g.get("meta",""))}</div>' if g.get("meta") else ""
            note = f'<div class="route-note">{esc(g.get("note",""))}</div>' if g.get("note") else ""
            groups_html += (
                '<div class="route-group">'
                f'<div class="route-title">{esc(g.get("title","Grupo"))}</div>'
                f"{meta}{note}"
                f'<ul class="route-paths">{gr}</ul>'
                "</div>"
            )
        cards.append(
            f"""
            <section class="sec" id="{esc(sec["id"])}">
              <h2>Subetapa: {esc(sec["label"])}</h2>
              <div class="body">
                <h3>UCA / Servicio</h3>
                <ul>{routes_html}</ul>
                {groups_html}
              </div>
            </section>
            """
        )

    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{esc(title)}</title>
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
  </style>
</head>
<body>
  <header>
    <h1>{esc(title)}</h1>
    <div class="meta">{esc(subtitle)}</div>
  </header>
  <div class="wrap">
    <nav class="toc">{toc}</nav>
    {''.join(cards)}
  </div>
</body>
</html>"""
