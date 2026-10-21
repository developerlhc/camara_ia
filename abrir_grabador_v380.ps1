$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$pythonw = Join-Path $projectRoot '.venv\Scripts\pythonw.exe'

if (-not (Test-Path -LiteralPath $pythonw -PathType Leaf)) {
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show(
        "No se encontró el entorno Python del proyecto.",
        "Grabador V380"
    ) | Out-Null
    exit 1
}

Set-Location -LiteralPath $projectRoot
Start-Process -FilePath $pythonw -ArgumentList '-m', 'tools.v380_motion_recorder.app' -WorkingDirectory $projectRoot -WindowStyle Hidden
