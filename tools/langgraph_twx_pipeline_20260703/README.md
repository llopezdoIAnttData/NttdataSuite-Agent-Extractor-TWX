# LangGraph TWX -> HTML Pipeline (auditable)

Pipeline multi-agente para convertir paquetes IBM BPM/BAW `.twx` en HTML funcional orientado a negocio, con trazabilidad técnica intermedia.

## Instalación

```powershell
pip install -r requirements.txt
```

## Dependencias

- langgraph
- networkx

## Variable de entorno

No requiere `OPENAI_API_KEY`. Ejecuta procesamiento local completo.

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

3. **Traductor funcional local (`agents.py`)**
   - Convierte grafo técnico a JSON funcional consolidado con reglas locales.

4. **Generador HTML local (`agents.py`)**
   - Genera HTML autocontenido en modo local.

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
- El mapeo funcional final usa reglas locales basadas en el grafo detectado.
- Puede haber artefactos con IDs colisionados; se renombran y se agrega warning.
- No ejecuta servicios IBM; solo analiza definición estática exportada.
