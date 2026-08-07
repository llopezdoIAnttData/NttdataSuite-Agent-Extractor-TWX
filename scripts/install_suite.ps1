$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$CopilotHome = Join-Path $env:USERPROFILE ".copilot"
$SkillsSrc = Join-Path $RepoRoot ".copilot\skills"
$SkillsDst = Join-Path $CopilotHome "skills"

Write-Host "==> NTT DATA Suite Installer (Windows)"
Write-Host "Repo: $RepoRoot"
Write-Host "Destino Copilot: $CopilotHome"

if (-not (Test-Path $SkillsSrc)) {
  throw "No existe $SkillsSrc"
}

New-Item -ItemType Directory -Force $SkillsDst | Out-Null

Get-ChildItem $SkillsSrc -Directory | ForEach-Object {
  $dst = Join-Path $SkillsDst $_.Name
  New-Item -ItemType Directory -Force $dst | Out-Null
  Copy-Item (Join-Path $_.FullName "*") $dst -Recurse -Force

  $upper = Join-Path $dst "SKILL.md"
  $lower = Join-Path $dst "skill.md"
  if ((Test-Path $upper) -and -not (Test-Path $lower)) {
    Copy-Item $upper $lower -Force
  }
}

Write-Host "==> Instalando dependencias del pipeline"
if (Get-Command py -ErrorAction SilentlyContinue) {
  py -3.10 -m pip install -r (Join-Path $RepoRoot "tools\langgraph_twx_pipeline_20260703\requirements.txt")
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
  python -m pip install -r (Join-Path $RepoRoot "tools\langgraph_twx_pipeline_20260703\requirements.txt")
} else {
  Write-Warning "No se encontró Python. Omitiendo instalación de dependencias."
}

Write-Host ""
Write-Host "✅ Suite instalada."
Write-Host "Skills instalados en: $SkillsDst"
Write-Host ""
Write-Host "Siguiente paso en Copilot CLI:"
Write-Host "  /skills reload"
Write-Host "o reinicia Copilot CLI."
Write-Host ""
Write-Host "Comandos disponibles:"
Write-Host "  /nttdat-extractor"
Write-Host "  /nttdata-extractor"
