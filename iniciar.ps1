$ErrorActionPreference = "Stop"

$env:EMPTY_RESET_SECONDS = "3"
$env:FRAME_WIDTH = "960"
$env:FACE_DETECT_WIDTH = "1280"
$env:CAMERA_WIDTH = "1920"
$env:CAMERA_HEIGHT = "1080"
$env:FACE_CONTEXT_SCALE = "3.2"
$env:FACE_MIN_CROP_WIDTH = "520"
$env:UPSCALE_FACE_CROP = "0"
$env:JPEG_QUALITY = "85"
$env:TARGET_FPS = "20"
$env:DROP_BUFFER_FRAMES = "0"
$env:ANALYZE_EVERY_FRAMES = "4"
$env:FACE_SCAN_EVERY = "2"
# El directorio se crea antes de importar Ultralytics; evita depender del perfil de Windows.
$ultralyticsConfig = Join-Path $PSScriptRoot ".ultralytics"
New-Item -ItemType Directory -Force -Path $ultralyticsConfig | Out-Null
$env:YOLO_CONFIG_DIR = $ultralyticsConfig

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "No se encontró el entorno virtual en '$python'. Créalo con: python -m venv .venv"
}

function Get-LocalEnvValue([string]$Name) {
    $envFile = Join-Path $PSScriptRoot ".env"
    if (-not (Test-Path -LiteralPath $envFile)) { return "" }
    $line = Get-Content -LiteralPath $envFile | Where-Object { $_ -match "^\s*$([regex]::Escape($Name))\s*=" } | Select-Object -Last 1
    if (-not $line) { return "" }
    $value = ($line -split "=", 2)[1].Trim()
    if ($value.Length -ge 2 -and (($value[0] -eq "'" -and $value[-1] -eq "'") -or ($value[0] -eq '"' -and $value[-1] -eq '"'))) {
        $value = $value.Substring(1, $value.Length - 2)
    }
    return $value
}

if ((Get-LocalEnvValue "CAMERA_STORAGE") -eq "mysql") {
    $apiSource = Join-Path $PSScriptRoot "apps\api\src"
    $env:PYTHONPATH = "$apiSource;$PSScriptRoot"
    & $python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw "No se pudieron aplicar las migraciones MySQL." }
}

# PyTorch para Windows carga estas DLL desde PATH.
$torchLib = Join-Path $PSScriptRoot ".venv\Lib\site-packages\torch\lib"
if (Test-Path -LiteralPath $torchLib) {
    $env:PATH = "$torchLib;$env:PATH"
}

Write-Host "Vigilay Local: http://localhost:5000"
Write-Host "Aquí se configuran empresa, sede, conexiones de cámara y asignación Frigate."
& (Join-Path $PSScriptRoot 'scripts\asegurar-agente-stream.ps1')
& $python "$PSScriptRoot\camara-ia.py"
