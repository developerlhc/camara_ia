$ErrorActionPreference = "Stop"

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "No se encontró el entorno virtual .venv."
}

$apiSource = Join-Path $PSScriptRoot "apps\api\src"
$env:PYTHONPATH = "$apiSource;$PSScriptRoot"
Push-Location $PSScriptRoot
try {

# La comprobación usa DATABASE_URL desde .env y nunca imprime la contraseña.
& $python -c "from sqlalchemy import text; from vigilay.db import engine; c=engine().connect(); c.execute(text('SELECT 1')); c.close(); print('Conexión MySQL verificada.')"
if ($LASTEXITCODE -ne 0) {
    throw "MySQL no responde. Corrige DATABASE_URL en .env y vuelve a ejecutar este archivo."
}

& $python -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw "Falló la actualización del esquema MySQL." }

& $python (Join-Path $PSScriptRoot "scripts\migrate-cameras-to-mysql.py")
if ($LASTEXITCODE -ne 0) { throw "No se importaron las cámaras; .env se conserva intacto." }

& $python -c "from dotenv import set_key; set_key('.env','CAMERA_STORAGE','mysql',quote_mode='never')"
if ($LASTEXITCODE -ne 0) { throw "No se pudo activar MySQL como origen de cámaras." }

Write-Host "Migración terminada. Vigilay cargará cámaras y credenciales desde MySQL."
} finally {
    Pop-Location
}
