# NTT DATA Suite — Agent Extractor TWX

Skill y pipeline para analizar archivos `.twx` de IBM BPM/BAW y generar HTML funcional.

## Contenido

- `tools/langgraph_twx_pipeline_20260703/`: pipeline LangGraph TWX -> HTML
- `.copilot/skills/nttdat-extractor/`: launcher `/nttdat-extractor`
- `.copilot/skills/nttdata-extractor/`: alias `/nttdata-extractor`

## Requisitos

- Python **3.10+**
- `pip`
- Variable de entorno `OPENAI_API_KEY`

## Instalación del pipeline

```bash
cd tools/langgraph_twx_pipeline_20260703
python3.10 -m pip install -r requirements.txt
```

## Instalación del menú (skill) en Copilot CLI

Desde la raíz de este repo:

```bash
mkdir -p ~/.copilot/skills/nttdat-extractor ~/.copilot/skills/nttdata-extractor
cp -R .copilot/skills/nttdat-extractor/. ~/.copilot/skills/nttdat-extractor/
cp -R .copilot/skills/nttdata-extractor/. ~/.copilot/skills/nttdata-extractor/
```

Luego recarga:

```text
/skills reload
```

o reinicia Copilot CLI.

## Cómo ejecutar el menú

Puedes invocar cualquiera:

```text
/nttdat-extractor
```

o

```text
/nttdata-extractor
```

El menú mostrará banner NTT DATA y 4 opciones:

1. Pipeline básico (TWX -> HTML)
2. Pipeline con auditoría (`--audit-dir`)
3. Verificación de entorno (`OPENAI_API_KEY` + dependencias)
4. Ayuda rápida (`--help`)

## Líneas de ejecución del menú

### Opción 1

```bash
cd tools/langgraph_twx_pipeline_20260703
python3.10 main.py --input "<RUTA_TWX>" --output "<RUTA_HTML>"
```

### Opción 2

```bash
cd tools/langgraph_twx_pipeline_20260703
python3.10 main.py --input "<RUTA_TWX>" --output "<RUTA_HTML>" --audit-dir "<RUTA_AUDIT>" --extract-dir "<RUTA_EXTRACT_OPCIONAL>"
```

### Opción 3

```bash
cd tools/langgraph_twx_pipeline_20260703
python3.10 --version
python3.10 -c "import os; print('OPENAI_API_KEY=' + ('OK' if os.getenv('OPENAI_API_KEY') else 'MISSING'))"
python3.10 -c "import langgraph, langchain_core, langchain_openai, networkx; print('deps=OK')"
```

### Opción 4

```bash
cd tools/langgraph_twx_pipeline_20260703
python3.10 main.py --help
```

## Validación realizada

En este entorno:

- `python3.10 main.py --help` responde correctamente.
- Imports de `langgraph`, `langchain_core`, `langchain_openai`, `networkx` correctos.
- `OPENAI_API_KEY` se reporta como `MISSING` si no está configurada.

