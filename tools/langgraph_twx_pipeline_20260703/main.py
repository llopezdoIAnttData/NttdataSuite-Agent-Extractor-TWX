from __future__ import annotations

import argparse
from workflow import build_app


def parse_args():
    p = argparse.ArgumentParser(description="Pipeline LangGraph: TWX -> HTML funcional")
    p.add_argument("--input", required=True, help="Ruta del archivo .twx")
    p.add_argument("--output", required=True, help="Ruta del HTML de salida")
    p.add_argument("--model", default="local", help="Parámetro reservado (modo local)")
    p.add_argument("--audit-dir", default=None, help="Directorio para salidas de auditoria")
    p.add_argument("--extract-dir", default=None, help="Directorio opcional de extraccion")
    return p.parse_args()


def main():
    args = parse_args()

    app = build_app()
    result = app.invoke(
        {
            "input_twx": args.input,
            "output_html": args.output,
            "model": args.model,
            "audit_dir": args.audit_dir,
            "extract_dir": args.extract_dir,
        }
    )
    print(f"OK. HTML generado en: {args.output}")
    if result.get("warnings"):
        print("Warnings:")
        for w in result["warnings"]:
            print(f"- {w}")


if __name__ == "__main__":
    main()
