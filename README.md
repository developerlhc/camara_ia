# Vigilay

Plataforma de videovigilancia multiempresa en construcción, siguiendo [el Master Prompt](<Vigilay — Master Prompt para Astra.md>). Primera entrega: administración central con backend real, MySQL, autenticación, permisos y configuración de cámaras simuladas.

## Iniciar

Esta instalación ya cuenta con `.env` local y claves aleatorias. El acceso inicial está en [el archivo privado local](.local/ACCESO_LOCAL.md), excluido de Git y Docker.

```powershell
.\scripts\iniciar-vigilay.ps1
```

O bien:

```powershell
docker compose up -d --build
```

- Web: http://localhost:3000
- OpenAPI: http://localhost:8000/api/docs
- Preparación API: http://localhost:8000/readyz

En otra instalación, crea `.env` desde [.env.example](.env.example), reemplaza todos los marcadores y genera claves aleatorias propias. Crea el primer administrador de forma interactiva:

```powershell
docker compose exec api vigilay create-superadmin --email admin@example.com --username admin
```

## Qué funciona

- Login/logout, contraseñas Argon2id, sesiones HttpOnly revocables, CSRF, limitación de intentos y bloqueo temporal.
- Superadministrador, administrador de cliente, operador y observador.
- Alta y edición de clientes, sedes y usuarios; suspensión de clientes y desactivación de usuarios.
- Aislamiento por cliente en endpoints, consultas ORM y referencias compuestas de MySQL.
- Registro de cámaras RTSP con URL cifrada AES-256-GCM, sin devolverla al navegador.
- Permisos de visualización/configuración por cámara para operadores y observadores.
- Simulador explícito: prueba de conexión, descubrimiento de capacidades, comandos persistidos, worker y lectura de confirmación desired/reported.
- Dashboard con datos reales de la base, auditoría y estado de API/MySQL/Redis/worker.
- Recuperación de contraseña mediante token de un solo uso emitido por CLI; cambio de contraseña desde Mi perfil.
- Contenedores web/API/worker, migraciones y volúmenes persistentes; checks y publicación GHCR preparados.

## Recorrido de prueba

1. Entra como administrador.
2. Crea un cliente en Clientes.
3. Crea una sede y un usuario de ese cliente.
4. En Cámaras, agrega una cámara de tipo **Simulador de desarrollo**.
5. Abre su detalle y pulsa Probar conexión.
6. Cambia la sensibilidad de movimiento y pulsa Aplicar configuración.
7. Comprueba el resultado del comando y los valores Deseado/Reportado.
8. Revisa los registros de Auditoría.

El simulador no genera video. Registrar una URL RTSP todavía no activa conexiones reales. Edge Agent, ONVIF, WebRTC, migración de YOLO/rostros, eventos, notificaciones e integraciones de fabricantes corresponden a las siguientes fases. El MVP completo del Master Prompt sigue pendiente.

## Desarrollo y pruebas

```powershell
python -m venv .venv-vigilay
.\.venv-vigilay\Scripts\python.exe -m pip install -e ".[dev]"
docker compose up -d mysql redis
.\.venv-vigilay\Scripts\alembic.exe upgrade head
.\.venv-vigilay\Scripts\uvicorn.exe vigilay.main:create_app --factory --host 127.0.0.1 --port 8000
```

En otra terminal: `.\.venv-vigilay\Scripts\vigilay-worker.exe`. Para la web: `cd apps/web`, `npm ci`, `npm run dev`.

Pruebas MySQL con esquema separado:

```powershell
docker compose cp infra/docker/init-test-db.sh mysql:/tmp/vigilay-init-test-db.sh
docker compose exec -T mysql sh /tmp/vigilay-init-test-db.sh
.\.venv-vigilay\Scripts\pytest.exe
.\.venv-vigilay\Scripts\alembic.exe check
```

Prueba de navegador contra el stack de desarrollo:

```powershell
$env:VIGILAY_E2E_EMAIL="tu-administrador@example.com"
$env:VIGILAY_E2E_PASSWORD="tu-contraseña-local"
$env:PLAYWRIGHT_CHANNEL="msedge"
cd apps/web
npm run test:e2e
```

También funciona Chromium instalado con `npx playwright install chromium`, omitiendo `PLAYWRIGHT_CHANNEL`. El E2E crea datos de demostración identificados en la base de desarrollo.

## Documentación

- [Estado inicial y reutilización](docs/CURRENT_STATE.md)
- [Arquitectura y decisiones](docs/ARCHITECTURE.md)
- [Plan de implementación](docs/IMPLEMENTATION_PLAN.md)
- [Verificación de esta entrega](docs/VALIDATION.md)
- [Modelo de datos](docs/DATABASE.md)
- [Autenticación](docs/AUTHENTICATION.md)
- [Seguridad y límites actuales](docs/SECURITY.md)
- [Variables de entorno](docs/ENVIRONMENT_VARIABLES.md)
- [Operación local y copias de seguridad](docs/OPERATIONS.md)
- [Prototipo original](docs/LEGACY.md)

El prototipo se conserva en `camara-ia.py`, `templates/` e `iniciar.ps1`. Sus credenciales locales se trasladaron a `.local/legacy-config.json`; las variables de entorno siguen teniendo prioridad. CSV, fotos y modelo YOLO originales permanecen en sus ubicaciones.
# camara_ia
