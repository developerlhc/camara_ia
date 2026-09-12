$ErrorActionPreference = "Stop"
Push-Location (Split-Path -Parent $PSScriptRoot)
try {
    if (-not (Test-Path -LiteralPath ".env")) {
        throw "Configura .env a partir de .env.example antes de iniciar Vigilay."
    }
    docker compose up -d --build
    if ($LASTEXITCODE -ne 0) { throw "No se pudo iniciar Vigilay." }
    Write-Host "Vigilay: http://localhost:3000"
    Write-Host "API: http://localhost:8000/api/docs"
} finally {
    Pop-Location
}
