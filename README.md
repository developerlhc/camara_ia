# Vigilay

Plataforma de videovigilancia multiempresa con administración central, agente local, video en vivo y consulta protegida de eventos y grabaciones de Frigate.

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
- Vigilay Local (ejecutando `.\iniciar.ps1`): http://localhost:5000
- OpenAPI: http://localhost:8000/api/docs
- Preparación API: http://localhost:8000/readyz

### Vigilay Local en Docker (v0.2.1)

El panel local también funciona en un contenedor, sin instalar Python en el anfitrión:

```powershell
docker compose --profile local up -d --build vigilay-local
```

Abre http://localhost:5000. No ejecutes simultáneamente el panel Python de
`iniciar.ps1` en ese puerto; para probar ambos, configura `VIGILAY_LOCAL_PORT=5002`.
La empresa/sede persisten en `.local/vigilay-local.json` y se validan contra MySQL.
El agente de streaming, Frigate y el puente V380 Windows siguen siendo servicios
separados. Consulta [instalación, red y límites de Docker Local](docs/VIGILAY_LOCAL_DOCKER.md).

GitHub Actions verifica y publica tres imágenes GHCR: `vigilay-api`, `vigilay-web`
y `vigilay-local`, con etiquetas `v0.2.1-build-N`. Publicar no despliega automáticamente
en Bunny. Vigilay Local se instala en la sede, no en Magic Containers.

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
- Dashboard con datos reales de la base, auditoría y estado de API/MySQL/worker/agente.
- Cuadrícula de cámaras con filtros empresa/sede, paginación y vivo automático en tarjetas visibles.
- Video en vivo bajo demanda mediante el agente local y Cloudflare Stream WebRTC.
- Eventos de IA y grabaciones obtenidos de Frigate y filtrados por empresa, sede y permisos de cámara.
- Gateway Frigate autenticado por sede; sin dominio usa un Quick Tunnel saliente que se registra automáticamente.
- Vigilay Local permite seleccionar, crear o modificar su empresa y sede; valida que ambas existan y que la sede pertenezca a la empresa antes de cargar cámaras.
- Recuperación de contraseña mediante token de un solo uso emitido por CLI; cambio de contraseña desde Mi perfil.
- Contenedores web/API/worker, migraciones y volúmenes persistentes; checks y publicación GHCR preparados.

## Recorrido operativo

1. Entra como administrador.
2. Crea un cliente en Clientes.
3. Crea una sede y un usuario de ese cliente.
4. En Cámaras, registra la conexión RTSP/V380 y, si la cámara ya existe en Frigate, selecciona su alias Frigate.
5. Pulsa **Probar conexión**; una conexión real correcta queda verificada/en línea.
6. En Cámaras, selecciona empresa/sede: las tarjetas visibles inician el vivo automáticamente; puedes ampliar una cámara.
7. Consulta **Eventos de IA** y **Grabaciones**. Estas vistas nunca leen Cloudflare: el API obtiene los datos y medios de Frigate y sólo entrega cámaras autorizadas.

Cloudflare Stream se usa exclusivamente para el video en vivo. Frigate sigue siendo el motor y almacén de detecciones, eventos y grabaciones. Cloudflare Tunnel sólo crea el canal privado entre la sede y Vigilay Cloud; no almacena esos medios. Una cámara puede funcionar en vivo y, aun así, no aparecer en Eventos/Grabaciones hasta que exista en Frigate, su alias se vincule y `frigate-gateway` esté conectado.

## Desarrollo y pruebas

```powershell
python -m venv .venv-vigilay
.\.venv-vigilay\Scripts\python.exe -m pip install -e ".[dev]"
docker compose up -d mysql
.\.venv-vigilay\Scripts\alembic.exe upgrade head
.\.venv-vigilay\Scripts\uvicorn.exe vigilay.main:create_app --factory --host 127.0.0.1 --port 8000
```

En otra terminal: `.\.venv-vigilay\Scripts\vigilay-worker.exe`. Para la web: `cd apps/web`, `npm ci`, `npm run dev`.

En el equipo Windows que comparte la red local con las cámaras, inicia el publicador bajo demanda:

```powershell
.\scripts\iniciar-agente-stream.ps1
```

El agente no abre puertos públicos ni inicia cámaras por sí solo. Mantiene un único FFmpeg por cámara mientras existan sesiones con heartbeat almacenadas en MySQL. En producción rechaza MySQL sin verificación TLS.

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
- [Despliegue de Vigilay Web en Magic Containers](docs/MAGIC_CONTAINERS.md)
- [Prototipo original](docs/LEGACY.md)

`camara-ia.py`, `templates/` e `iniciar.ps1` forman **Vigilay Local**: administran la identidad de la instalación, las conexiones de cámara y la vista LAN. La identidad queda en `.local/vigilay-local.json`; contiene identificadores, no credenciales. El YOLO local queda desactivado por defecto (`LOCAL_AI_ENABLED=false`) porque la IA normal pertenece a Frigate.

En `http://localhost:5000`, **Configurar empresa y sede** permite crear, seleccionar y modificar la identidad de esa instalación. **Agregar/Editar cámara** permite asignar uno de los aliases que existen realmente en Frigate; la lista se valida mediante el canal privado de Vigilay API.
# camara_ia
