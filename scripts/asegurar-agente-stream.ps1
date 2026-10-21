$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$lockName = 'Local\VigilayStreamAgent-' + [Convert]::ToBase64String(
    [System.Security.Cryptography.SHA256]::Create().ComputeHash(
        [Text.Encoding]::UTF8.GetBytes($projectRoot.ToLowerInvariant())
    )
).Replace('/', '_').Replace('+', '-').Substring(0, 16)
$probeMutex = New-Object System.Threading.Mutex($false, $lockName)
$canStart = $false
try {
    try { $canStart = $probeMutex.WaitOne(0) }
    catch [System.Threading.AbandonedMutexException] { $canStart = $true }
    if (-not $canStart) { return }
} finally {
    if ($canStart) { $probeMutex.ReleaseMutex() }
    $probeMutex.Dispose()
}
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
