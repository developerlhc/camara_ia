$ErrorActionPreference = "Stop"
Push-Location (Split-Path -Parent $PSScriptRoot)
try {
    if (-not (Test-Path -LiteralPath ".env")) {
        throw "Configura .env a partir de .env.example antes de iniciar Vigilay."
    }
    docker compose up -d --build
    if ($LASTEXITCODE -ne 0) { throw "No se pudo iniciar Vigilay." }

    $frigateContainer = docker ps --filter "name=^/frigate$" --format "{{.Names}}"
    if ($frigateContainer) {
        $frigateNetworks = docker inspect frigate --format "{{json .NetworkSettings.Networks}}"
        if ($frigateNetworks -notmatch 'vigilay_default') {
            docker network connect --alias frigate vigilay_default frigate
            if ($LASTEXITCODE -ne 0) { throw "No se pudo conectar Frigate a la red privada de Vigilay." }
        }
    }

    $python = Join-Path (Get-Location) ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $python)) {
        throw "No se encontró .venv para iniciar el agente local de streaming."
    }
    $agentRunning = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -eq "python.exe" -and $_.CommandLine -match "vigilay\.stream_agent" } |
        Select-Object -First 1
    if (-not $agentRunning) {
        $logDirectory = Join-Path (Get-Location) ".local"
        New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
        $agent = Start-Process -FilePath $python `
            -ArgumentList "-m", "vigilay.stream_agent" `
            -WorkingDirectory (Get-Location) `
            -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $logDirectory "stream-agent.out.log") `
            -RedirectStandardError (Join-Path $logDirectory "stream-agent.err.log") `
            -PassThru
        Set-Content -LiteralPath (Join-Path $logDirectory "stream-agent.pid") -Value $agent.Id
        Start-Sleep -Seconds 2
        if ($agent.HasExited) {
            throw "El agente local de streaming no pudo iniciar. Revisa .local\stream-agent.err.log"
        }
    }
    Write-Host "Vigilay: http://localhost:3000"
    Write-Host "API: http://localhost:8000/api/docs"
    Write-Host "Agente de streaming: activo"
    $frigateStatus = if ($frigateContainer) { "conectado por red privada" } else { "no detectado" }
    Write-Host "Frigate: $frigateStatus"
} finally {
    Pop-Location
}
