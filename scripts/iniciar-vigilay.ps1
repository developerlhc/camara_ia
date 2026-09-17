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

    & (Join-Path $PSScriptRoot 'asegurar-agente-stream.ps1')
    Write-Host "Vigilay: http://localhost:3000"
    Write-Host "API: http://localhost:8000/api/docs"
    Write-Host "Agente de streaming: activo"
    $frigateStatus = if ($frigateContainer) { "conectado por red privada" } else { "no detectado" }
    Write-Host "Frigate: $frigateStatus"
} finally {
    Pop-Location
}
