$ErrorActionPreference = "Stop"

$env:EMPTY_RESET_SECONDS = "3"
$env:FRAME_WIDTH = "1280"
$env:FACE_DETECT_WIDTH = "1280"
$env:CAMERA_WIDTH = "1920"
$env:CAMERA_HEIGHT = "1080"
$env:FACE_CONTEXT_SCALE = "3.2"
$env:FACE_MIN_CROP_WIDTH = "520"
$env:UPSCALE_FACE_CROP = "0"
$env:JPEG_QUALITY = "98"

& "$PSScriptRoot\.venv\Scripts\python.exe" "$PSScriptRoot\camara-ia.py"
