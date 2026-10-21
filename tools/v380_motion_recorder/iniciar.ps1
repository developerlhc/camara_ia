$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "No se encontró $python. Crea el entorno virtual e instala requirements-local.txt."
}

Set-Location -LiteralPath $projectRoot
& $python -m tools.v380_motion_recorder.recorder @args
