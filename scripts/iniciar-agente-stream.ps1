$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "No se encontró .venv. Instala el proyecto con: pip install -e ."
}
$env:PYTHONPATH = "$(Join-Path $projectRoot 'apps\api\src');$projectRoot"
Push-Location $projectRoot
try {
    & $python -m vigilay.stream_agent
    if ($LASTEXITCODE -ne 0) { throw "El agente de streaming terminó con error." }
} finally {
    Pop-Location
}
