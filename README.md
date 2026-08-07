# NTT DATA Suite — Agent Extractor TWX

Suite para analizar `.twx` de IBM BPM/BAW y generar HTML funcional con menú de ejecución en Copilot CLI.

## Instalación rápida (solo descargar y ejecutar)

### macOS / Linux

```bash
git clone https://github.com/llopezdoIAnttData/NttdataSuite-Agent-Extractor-TWX.git
cd NttdataSuite-Agent-Extractor-TWX
bash scripts/install_suite.sh
```

### Windows (PowerShell)

```powershell
git clone https://github.com/llopezdoIAnttData/NttdataSuite-Agent-Extractor-TWX.git
cd NttdataSuite-Agent-Extractor-TWX
powershell -ExecutionPolicy Bypass -File .\scripts\install_suite.ps1
```

## Prompt único para agregar la suite desde Copilot CLI

Si ya descargaste el repo y abriste Copilot en esta carpeta, usa este prompt:

```text
Ejecuta scripts/install_suite.sh y después recarga skills.
```

En Windows:

```text
Ejecuta .\scripts\install_suite.ps1 y después recarga skills.
```

## Activación

En Copilot CLI:

```text
/skills reload
```

Luego ejecuta:

```text
/nttdat-extractor
```

o:

```text
/nttdata-extractor
```

## Qué instala

- Skills Copilot:
  - `.copilot/skills/nttdat-extractor/`
  - `.copilot/skills/nttdata-extractor/` (alias)
- Dependencias del pipeline:
  - `tools/langgraph_twx_pipeline_20260703/requirements.txt`

## Requisitos

- Python 3.10+
- pip
- `OPENAI_API_KEY` en entorno para ejecutar el pipeline completo

## Comandos que ejecuta el menú

### Opción 1 — Pipeline básico

```bash
cd tools/langgraph_twx_pipeline_20260703
python3.10 main.py --input "<RUTA_TWX>" --output "<RUTA_HTML>"
```

### Opción 2 — Pipeline con auditoría

```bash
cd tools/langgraph_twx_pipeline_20260703
python3.10 main.py --input "<RUTA_TWX>" --output "<RUTA_HTML>" --audit-dir "<RUTA_AUDIT>" --extract-dir "<RUTA_EXTRACT_OPCIONAL>"
```

### Opción 3 — Verificación de entorno

```bash
cd tools/langgraph_twx_pipeline_20260703
python3.10 --version
python3.10 -c "import os; print('OPENAI_API_KEY=' + ('OK' if os.getenv('OPENAI_API_KEY') else 'MISSING'))"
python3.10 -c "import langgraph, langchain_core, langchain_openai, networkx; print('deps=OK')"
```

### Opción 4 — Ayuda

```bash
cd tools/langgraph_twx_pipeline_20260703
python3.10 main.py --help
```
