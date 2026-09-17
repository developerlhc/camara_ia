$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "No se encontró .venv. Instala el proyecto con: pip install -e ."
}
$env:PYTHONPATH = "$(Join-Path $projectRoot 'apps\api\src');$projectRoot"
Push-Location $projectRoot
$lockName = 'Local\VigilayStreamAgent-' + [Convert]::ToBase64String(
    [System.Security.Cryptography.SHA256]::Create().ComputeHash(
        [Text.Encoding]::UTF8.GetBytes($projectRoot.ToLowerInvariant())
    )
).Replace('/', '_').Replace('+', '-').Substring(0, 16)
$agentMutex = New-Object System.Threading.Mutex($false, $lockName)
$ownsMutex = $false
try {
    try { $ownsMutex = $agentMutex.WaitOne(0) }
    catch [System.Threading.AbandonedMutexException] { $ownsMutex = $true }
    if (-not $ownsMutex) { throw "Ya hay un supervisor del agente para este proyecto." }
    $retrySeconds = 2
    while ($true) {
        & $python -m vigilay.stream_agent
        if ($LASTEXITCODE -eq 0) { break }
        Write-Warning "El agente terminó (código $LASTEXITCODE). Reintento en $retrySeconds segundos."
        Start-Sleep -Seconds $retrySeconds
        $retrySeconds = [Math]::Min(30, $retrySeconds * 2)
    }
} finally {
    if ($ownsMutex) { $agentMutex.ReleaseMutex() }
    $agentMutex.Dispose()
    Pop-Location
}
