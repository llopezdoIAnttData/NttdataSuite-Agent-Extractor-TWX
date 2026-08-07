#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COPILOT_HOME="${HOME}/.copilot"
SKILLS_SRC="${REPO_ROOT}/.copilot/skills"
SKILLS_DST="${COPILOT_HOME}/skills"

echo "==> NTT DATA Suite Installer (macOS/Linux)"
echo "Repo: ${REPO_ROOT}"
echo "Destino Copilot: ${COPILOT_HOME}"

mkdir -p "${SKILLS_DST}"

if [[ ! -d "${SKILLS_SRC}" ]]; then
  echo "ERROR: No existe ${SKILLS_SRC}"
  exit 1
fi

for dir in "${SKILLS_SRC}"/*; do
  [[ -d "${dir}" ]] || continue
  name="$(basename "${dir}")"
  mkdir -p "${SKILLS_DST}/${name}"
  cp -R "${dir}/." "${SKILLS_DST}/${name}/"
  # Compatibilidad: algunos loaders buscan skill.md en minúsculas.
  if [[ -f "${SKILLS_DST}/${name}/SKILL.md" && ! -f "${SKILLS_DST}/${name}/skill.md" ]]; then
    cp "${SKILLS_DST}/${name}/SKILL.md" "${SKILLS_DST}/${name}/skill.md"
  fi
done

PYTHON_BIN=""
if command -v python3.10 >/dev/null 2>&1; then
  PYTHON_BIN="python3.10"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
fi

if [[ -n "${PYTHON_BIN}" ]]; then
  echo "==> Instalando dependencias del pipeline con ${PYTHON_BIN}"
  "${PYTHON_BIN}" -m pip install -r "${REPO_ROOT}/tools/langgraph_twx_pipeline_20260703/requirements.txt"
else
  echo "WARN: No se encontró Python. Omitiendo instalación de dependencias."
fi

echo
echo "✅ Suite instalada."
echo "Skills instalados en: ${SKILLS_DST}"
echo
echo "Siguiente paso en Copilot CLI:"
echo "  /skills reload"
echo "o reinicia Copilot CLI."
echo
echo "Comandos disponibles:"
echo "  /nttdat-extractor"
echo "  /nttdata-extractor"
