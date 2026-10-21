param(
    [string]$PythonPath = "",
    [string]$ModelPath = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $PythonPath) {
    $localPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $localPython -PathType Leaf) {
        $PythonPath = $localPython
    } else {
        $PythonPath = (Get-Command python -ErrorAction Stop).Source
    }
}
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "No se encontró Python en $PythonPath. Crea .venv e instala tools/vigilay_recorder/requirements-build.txt."
}
if (-not $ModelPath) {
    $ModelPath = Join-Path $projectRoot "yolo11n.pt"
}
if (-not (Test-Path -LiteralPath $ModelPath -PathType Leaf)) {
    Push-Location $projectRoot
    try {
        & $PythonPath -c "from ultralytics import YOLO; YOLO('yolo11n.pt')"
    } finally {
        Pop-Location
    }
}
if (-not (Test-Path -LiteralPath $ModelPath -PathType Leaf)) {
    throw "No se pudo preparar el modelo YOLO en $ModelPath. Indícalo con -ModelPath."
}

& $PythonPath -c "import PyInstaller, cv2, imageio_ffmpeg, ultralytics"
if ($LASTEXITCODE -ne 0) {
    throw "Faltan dependencias. Ejecuta: & '$PythonPath' -m pip install -r tools/vigilay_recorder/requirements-build.txt"
}

$buildRoot = Join-Path $projectRoot ".local\recorder-build"
$distPath = Join-Path $buildRoot "dist"
$workPath = Join-Path $buildRoot "work"
$specPath = Join-Path $buildRoot "spec"
$entryPoint = Join-Path $projectRoot "tools\vigilay_recorder\agent.py"
New-Item -ItemType Directory -Force -Path $distPath, $workPath, $specPath | Out-Null

& $PythonPath -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --name vigilay-recorder `
    --paths $projectRoot `
    --add-data "$ModelPath;." `
    --collect-all imageio_ffmpeg `
    --collect-all ultralytics `
    --distpath $distPath `
    --workpath $workPath `
    --specpath $specPath `
    $entryPoint
if ($LASTEXITCODE -ne 0) {
    throw "No se pudo construir Vigilay Recorder."
}

$hostLine = (& rustc -vV | Select-String -Pattern "^host:").Line
if (-not $hostLine) {
    throw "No se pudo determinar el target de Rust."
}
$targetTriple = $hostLine.Substring(5).Trim()
$binaryDirectory = Join-Path $projectRoot "apps\desktop\src-tauri\binaries"
New-Item -ItemType Directory -Force -Path $binaryDirectory | Out-Null
$sourceBinary = Join-Path $distPath "vigilay-recorder.exe"
$targetBinary = Join-Path $binaryDirectory "vigilay-recorder-$targetTriple.exe"
Copy-Item -LiteralPath $sourceBinary -Destination $targetBinary -Force
Write-Host "Motor de grabación preparado: $targetBinary"
