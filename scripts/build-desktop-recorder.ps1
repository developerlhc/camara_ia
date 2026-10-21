param(
    [string]$PythonPath = "",
    [string]$ModelPath = "",
    [string]$FfmpegPath = "",
    [string]$CloudflaredPath = ""
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

if (-not $FfmpegPath) {
    if ($env:FFMPEG_PATH -and (Test-Path -LiteralPath $env:FFMPEG_PATH -PathType Leaf)) {
        $FfmpegPath = $env:FFMPEG_PATH
    } else {
        $installedFfmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
        if ($installedFfmpeg) { $FfmpegPath = $installedFfmpeg.Source }
    }
}
if (-not $FfmpegPath) {
    $environmentFile = Join-Path $projectRoot ".env"
    if (Test-Path -LiteralPath $environmentFile -PathType Leaf) {
        $ffmpegSetting = Get-Content -LiteralPath $environmentFile |
            Where-Object { $_ -match '^FFMPEG_PATH=' } |
            Select-Object -First 1
        if ($ffmpegSetting) { $FfmpegPath = $ffmpegSetting.Substring('FFMPEG_PATH='.Length).Trim() }
    }
}
if (-not $FfmpegPath -or -not (Test-Path -LiteralPath $FfmpegPath -PathType Leaf)) {
    throw "No se encontró FFmpeg para el agente de live. Configura FFMPEG_PATH."
}
$ffmpegMuxers = & $FfmpegPath -hide_banner -muxers 2>&1 | Out-String
if ($LASTEXITCODE -ne 0 -or $ffmpegMuxers -notmatch '(?m)^\s*E\s+whip\s') {
    throw "El FFmpeg seleccionado no incluye el muxer WHIP requerido para video en vivo."
}
$ffmpegTarget = Join-Path $binaryDirectory "vigilay-ffmpeg-$targetTriple.exe"
Copy-Item -LiteralPath $FfmpegPath -Destination $ffmpegTarget -Force
Write-Host "FFmpeg WHIP preparado: $ffmpegTarget"

$cloudflaredVersion = "2026.10.2"
$cloudflaredSha256 = "12c7c887f8aaab779aef1dfa9b60673530a5adb88ecc55dd6df8f56e0b70f199"
if (-not $CloudflaredPath) {
    $installedCloudflared = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($installedCloudflared) {
        $CloudflaredPath = $installedCloudflared.Source
    } else {
        $cloudflaredDirectory = Join-Path $projectRoot ".local\cloudflared\$cloudflaredVersion"
        $CloudflaredPath = Join-Path $cloudflaredDirectory "cloudflared.exe"
        if (-not (Test-Path -LiteralPath $CloudflaredPath -PathType Leaf)) {
            New-Item -ItemType Directory -Force -Path $cloudflaredDirectory | Out-Null
            $download = "$CloudflaredPath.download"
            Invoke-WebRequest `
                -Uri "https://github.com/cloudflare/cloudflared/releases/download/$cloudflaredVersion/cloudflared-windows-amd64.exe" `
                -OutFile $download
            Move-Item -LiteralPath $download -Destination $CloudflaredPath -Force
        }
    }
}
if (-not (Test-Path -LiteralPath $CloudflaredPath -PathType Leaf)) {
    throw "No se encontró cloudflared en $CloudflaredPath."
}
$sha256 = [System.Security.Cryptography.SHA256]::Create()
$cloudflaredStream = [System.IO.File]::OpenRead($CloudflaredPath)
try {
    $actualCloudflaredHash = ([System.BitConverter]::ToString(
        $sha256.ComputeHash($cloudflaredStream)
    )).Replace("-", "").ToLowerInvariant()
} finally {
    $cloudflaredStream.Dispose()
    $sha256.Dispose()
}
if ($actualCloudflaredHash -ne $cloudflaredSha256) {
    throw "La suma SHA-256 de cloudflared no coincide con la versión oficial $cloudflaredVersion."
}
$cloudflaredTarget = Join-Path $binaryDirectory "cloudflared-$targetTriple.exe"
Copy-Item -LiteralPath $CloudflaredPath -Destination $cloudflaredTarget -Force
Write-Host "Cloudflare Tunnel preparado: $cloudflaredTarget"
