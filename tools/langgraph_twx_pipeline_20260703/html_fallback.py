from __future__ import annotations

from typing import Any, Dict, List


def render_html(model: Dict[str, Any], state: Dict[str, Any] | None = None) -> str:
    state = state or {}
    title = model.get("title", "Flujo cronologico funcional de subetapas")
    subtitle = model.get("subtitle", "Vista compacta para negocio")
    stages = model.get("stages", [])
    warnings: List[str] = state.get("warnings", [])
    root_id = state.get("root_id")
    artifacts = state.get("artifacts", {})
    nodes = state.get("graph_nodes", [])
    edges = state.get("graph_edges", [])

    def esc(s: str) -> str:
        return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    toc = "\n".join(
        f'<a href="#{esc(st.get("id","sx"))}">{i+1}) {esc(st.get("name","Subetapa"))}</a>'
        for i, st in enumerate(stages)
    )

    cards: list[str] = []
    for st in stages:
        routes = "".join(f"<li>{esc(r)}</li>" for r in st.get("routes", []))
        groups_html = []
        for g in st.get("groups", []):
            gr = "".join(f"<li>{esc(r)}</li>" for r in g.get("routes", []))
            note = f'<div class="group-note">{esc(g.get("note",""))}</div>' if g.get("note") else ""
            groups_html.append(
                f'<div class="group"><div class="group-title">{esc(g.get("title","Grupo"))}</div>{note}<ul>{gr}</ul></div>'
            )
        cards.append(
            f"""
            <div class="card" id="{esc(st.get('id','sx'))}">
              <div class="title">Subetapa: [{esc(st.get('display_id','N/A'))}] {esc(st.get('name',''))}</div>
              <span class="tag">{esc(st.get('tag','Contexto'))}</span>
              <ul>{routes}</ul>
              {''.join(groups_html)}
            </div>
            """
        )

    warnings_html = "".join(f"<li>{esc(w)}</li>" for w in warnings) if warnings else "<li>Sin warnings</li>"
    artifact_rows = "".join(
        f"<li><code>{esc(aid)}</code> - {esc(a.get('name',''))} ({esc(a.get('artifact_type','artifact'))}) - <span class='small'>{esc(a.get('source_file',''))}</span></li>"
        for aid, a in list(artifacts.items())[:300]
    ) or "<li>Sin artefactos</li>"
    edge_rows = "".join(
        f"<li><code>{esc(e.get('source',''))}</code> -> <code>{esc(e.get('target',''))}</code> | {esc(e.get('label',''))} | "
        f"<span class='small'>evidence: {esc(str(e.get('evidence', {})))}</span></li>"
        for e in edges[:500]
    ) or "<li>Sin relaciones</li>"

    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{esc(title)}</title>
  <style>
    :root {{ --bg: #0d1117; --card: #161b22; --line: #30363d; --text: #e6edf3; --muted: #8b949e; --link: #58a6ff; --warn: #d29922; }}
    *{{box-sizing:border-box}}
    body{{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 "Segoe UI",Arial,sans-serif}}
    .wrap{{max-width:1180px;margin:0 auto;padding:20px}}
    h1{{margin:0 0 8px;font-size:28px}} .meta{{color:var(--muted);margin-bottom:14px}}
    .card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px;margin:12px 0}}
    .toc{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:8px}}
    .toc a{{display:block;text-decoration:none;color:var(--text);background:#111827;border:1px solid var(--line);padding:8px 10px;border-radius:8px}}
    .title{{font-weight:700;color:#d2e6ff}}
    .tag{{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:2px 8px;font-size:12px;margin:2px 6px 2px 0}}
    ul{{margin:8px 0 0 18px}} li{{margin:4px 0}}
    .group{{margin-top:10px;padding:10px;border:1px solid #3a3f4b;border-radius:8px;background:#111827}}
    .group-title{{font-weight:700;color:#cdd9e5;margin-bottom:6px}}
    .group-note{{font-size:12px;color:var(--muted);margin-bottom:6px}}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>{esc(title)}</h1>
    <div class="meta">{esc(subtitle)}</div>
    <div class="card">
      <h2>Resumen de auditoria</h2>
      <ul>
        <li>Total artefactos: <code>{len(artifacts)}</code></li>
        <li>Total nodos: <code>{len(nodes)}</code></li>
        <li>Total relaciones: <code>{len(edges)}</code></li>
        <li>root_id detectado: <code>{esc(str(root_id))}</code></li>
      </ul>
      <h3>Warnings</h3>
      <ul>{warnings_html}</ul>
    </div>
    <div class="card">
      <h2>Indice de subetapas</h2>
      <div class="toc">{toc}</div>
    </div>
    {''.join(cards)}
    <div class="card">
      <h2>Artefactos detectados</h2>
      <ul>{artifact_rows}</ul>
    </div>
    <div class="card">
      <h2>Relaciones detectadas (con evidencia)</h2>
      <ul>{edge_rows}</ul>
    </div>
  </div>
</body>
</html>"""
