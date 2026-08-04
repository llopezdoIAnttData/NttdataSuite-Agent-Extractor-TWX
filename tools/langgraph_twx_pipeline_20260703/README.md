# LangGraph TWX -> HTML Pipeline (auditable)

Pipeline multi-agente para convertir paquetes IBM BPM/BAW `.twx` en HTML funcional orientado a negocio, con trazabilidad técnica intermedia.

## Instalación

```powershell
pip install -r requirements.txt
```

## Dependencias

- langgraph
- langchain-core
- langchain-openai
- networkx

## Variable de entorno requerida

Define `OPENAI_API_KEY` antes de ejecutar:

```powershell
$env:OPENAI_API_KEY="tu_api_key"
```

## Ejecución básica

```powershell
python main.py --input "C:\ruta\proceso.twx" --output "C:\ruta\vista_funcional.html"
```

## Ejecución con auditoría

```powershell
python main.py `
  --input "C:\ruta\proceso.twx" `
  --output "C:\ruta\vista_funcional.html" `
  --audit-dir "C:\ruta\audit_output"
```

## Ejecución con directorio de extracción explícito (opcional)

```powershell
python main.py `
  --input "C:\ruta\proceso.twx" `
  --output "C:\ruta\vista_funcional.html" `
  --extract-dir "C:\ruta\tmp_extract" `
  --audit-dir "C:\ruta\audit_output"
```

## Fases del pipeline

1. **Extractor/Indexador (`extractor.py`)**
   - Extracción ZIP segura (protección zip-slip).
   - Parseo de `manifest.xml`.
   - Parseo recursivo de XMLs.
   - Indexación de artefactos con tags, referencias y snippets.

2. **Constructor de grafo (`graph_builder.py`)**
   - Construcción de nodos y relaciones con evidencia.
   - Detección de `root_id`.
   - Registro de referencias no resueltas.

3. **Traductor funcional (LLM, `agents.py`)**
   - Convierte grafo técnico a JSON funcional consolidado.
   - Limpia fences de respuesta y valida estructura mínima.
   - Fallback local si falla.

4. **Generador HTML (LLM, `agents.py`)**
   - Genera HTML autocontenido.
   - Limpia fences HTML.
   - Fallback HTML auditable si falla.

5. **Persistencia y auditoría (`workflow.py`)**
   - Guarda HTML final.
   - Guarda artefactos intermedios cuando se usa `--audit-dir`.

## Archivos de auditoría generados (`--audit-dir`)

- `extracted_dir.txt`
- `manifest.json`
- `artifacts.json`
- `graph.json`
- `functional_model.json`
- `warnings.txt`

## Ejemplo de uso con otro TWX

```powershell
python main.py `
  --input "D:\bpm\otro_paquete.twx" `
  --output "D:\bpm\salidas\otro_paquete.html" `
  --audit-dir "D:\bpm\salidas\audit_otro_paquete"
```

## Limitaciones conocidas

- La detección de relaciones depende de referencias presentes en XML; no interpreta toda semántica BPMN avanzada.
- El mapeo funcional final depende del LLM; si la respuesta es inválida se usa fallback.
- Puede haber artefactos con IDs colisionados; se renombran y se agrega warning.
- No ejecuta servicios IBM; solo analiza definición estática exportada.

