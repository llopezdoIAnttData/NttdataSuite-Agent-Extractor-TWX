---
name: nttdat-extractor
description: >
  NTT DATA TWX Extractor launcher. Use this skill when the user types
  "/nttdat-extractor", "/nttdata-extractor", "nttdat-extractor",
  "nttdata-extractor", "menu extractor twx", or asks to run the TWX to HTML
  pipeline with NTT DATA banner and guided menu.
allowed-tools: shell
---

# 🔷 NTT DATA — TWX Extractor Launcher

Cuando este skill se activa, muestra el banner corporativo y un menú guiado
para ejecutar el pipeline `langgraph_twx_pipeline_20260703`.

---

## PASO 1 — Mostrar banner y menú

Imprime **exactamente** este bloque:

```
  ●
   ╭──────╮   ███╗   ██╗████████╗████████╗    ██████╗  █████╗ ████████╗ █████╗
  ╱ ╭────╮ ╲  ████╗  ██║╚══██╔══╝╚══██╔══╝    ██╔══██╗██╔══██╗╚══██╔══╝██╔══██╗
 │  │    │  │ ██╔██╗ ██║   ██║      ██║       ██║  ██║███████║   ██║   ███████║
 │  ╰────╯  │ ██║╚██╗██║   ██║      ██║       ██║  ██║██╔══██║   ██║   ██╔══██║
  ╲         ╱ ██║ ╚████║   ██║      ██║       ██████╔╝██║  ██║   ██║   ██║  ██║
   ╰──────╯   ╚═╝  ╚═══╝   ╚═╝      ╚═╝       ╚═════╝ ╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝
  NTT DATA TWX Extractor Suite  v1.0.0  ·  IBM BPM → HTML funcional
```

```
╔══════════════════════════════════════════════════════════════╗
║      🔷 NTT DATA — Extractor TWX (LangGraph Pipeline)       ║
╠══════════════════════════════════════════════════════════════╣
║  [1] Ejecutar pipeline básico (TWX -> HTML)                 ║
║  [2] Ejecutar pipeline con auditoría (--audit-dir)          ║
║  [3] Verificar entorno (OPENAI_API_KEY + dependencias)      ║
║  [4] Mostrar ayuda rápida de comandos                       ║
╚══════════════════════════════════════════════════════════════╝

  👉  Escribe el número o nombre de la opción.
```

---

## PASO 2 — Resolver la elección del usuario

Si el usuario elige:

### Opción 1 — Pipeline básico

1. Solicita:
   - ruta del `.twx`
   - ruta del `.html` de salida
2. Ejecuta en shell:

```bash
cd tools/langgraph_twx_pipeline_20260703
python3.10 main.py --input "<RUTA_TWX>" --output "<RUTA_HTML>"
```

### Opción 2 — Pipeline con auditoría

1. Solicita:
   - ruta del `.twx`
   - ruta del `.html` de salida
   - ruta de `audit-dir`
   - (opcional) `extract-dir`
2. Ejecuta en shell:

```bash
cd tools/langgraph_twx_pipeline_20260703
python3.10 main.py --input "<RUTA_TWX>" --output "<RUTA_HTML>" --audit-dir "<RUTA_AUDIT>" [--extract-dir "<RUTA_EXTRACT>"]
```

### Opción 3 — Verificar entorno

Ejecuta en shell:

```bash
cd tools/langgraph_twx_pipeline_20260703
python3.10 --version
python3.10 -c "import os; print('OPENAI_API_KEY=' + ('OK' if os.getenv('OPENAI_API_KEY') else 'MISSING'))"
python3.10 -c "import langgraph, langchain_core, langchain_openai, networkx; print('deps=OK')"
```

### Opción 4 — Ayuda rápida

Muestra:

```bash
cd tools/langgraph_twx_pipeline_20260703
python3.10 main.py --help
```

---

## PASO 3 — Reportar resultado

- Si se ejecuta pipeline: reporta la ruta del HTML generado.
- Si falla: muestra error exacto y sugiere revisar `OPENAI_API_KEY` y `pip install -r requirements.txt`.
