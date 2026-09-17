$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$agentRunning = Get-CimInstance Win32_Process -ErrorAction Stop |
    Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -match 'vigilay\.stream_agent' } |
    Select-Object -First 1
if ($agentRunning) { return }
$logDirectory = Join-Path $projectRoot '.local'
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$supervisor = Join-Path $PSScriptRoot 'iniciar-agente-stream.ps1'
$process = Start-Process -FilePath 'powershell.exe' `
    -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"' + $supervisor + '"') `
    -WorkingDirectory $projectRoot -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $logDirectory "agent-$stamp.out.log") `
    -RedirectStandardError (Join-Path $logDirectory "agent-$stamp.err.log") -PassThru
Start-Sleep -Seconds 2
if ($process.HasExited) { throw "No inició el supervisor; revisa .local/agent-$stamp.err.log" }
Write-Host 'Supervisor del agente de streaming iniciado.'
