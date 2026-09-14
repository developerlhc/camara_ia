# Vigilay — configuración

`.env.example` es el catálogo inicial; `.env` es privado de la instalación y está excluido de Git. API y CLI locales lo cargan desde el directorio de trabajo. Compose convierte la dirección local de MySQL a su nombre interno de servicio. La web usa un proxy del mismo origen para evitar exponer credenciales o requerir tokens en almacenamiento del navegador.

| Variable | Propósito |
| --- | --- |
| DATABASE_URL | Conexión SQLAlchemy `mysql+pymysql`, esquema UTF8MB4. |
| BDMYSQL | Cadena ADO.NET (`Server=...;Database=...;Uid=...;Pwd=...`) aceptada como alternativa y con prioridad sobre `DATABASE_URL`. |
| DATABASE_POOL_SIZE | Conexiones persistentes máximas por proceso; usar `2` en hosting con límite de 20 conexiones. |
| DATABASE_MAX_OVERFLOW | Conexiones adicionales temporales por proceso; usar `0` en el hosting compartido actual. |
| CAMERA_STORAGE | `mysql` hace que el visor cargue todas las cámaras desde MySQL. |
| LOCAL_AI_ENABLED | Debe permanecer `false` normalmente: Frigate realiza toda la IA. Sólo habilita el YOLO heredado para pruebas aisladas. |
| START_STREAM_AGENT_WITH_LOCAL | Inicia el agente de vivo dentro de Vigilay Local. Mantener `false` si se usa el agente dedicado recomendado. |
| MYSQL_DATABASE / MYSQL_USER / MYSQL_PASSWORD | Base y usuario de aplicación en Compose. |
| MYSQL_ROOT_PASSWORD | Inicialización/administración de MySQL; no se inyecta en la API. |
| SESSION_SECRET | Clave aleatoria de al menos 32 caracteres para CSRF. |
| INTERNAL_PROXY_SECRET | Secreto del despliegue central, compartido sólo entre `vigilay-web` y `api` dentro del pod. No se instala en Vigilay Local. |
| CREDENTIAL_ENCRYPTION_KEY | Clave AES de 32 bytes codificada en base64. No rotar sin migrar credenciales. |
| WEB_ORIGIN | Origen exacto permitido, inicialmente `http://localhost:3000`. |
| SESSION_COOKIE_SECURE | `true` para HTTPS/producción. |
| SESSION_TTL_SECONDS | Vida de sesión, inicialmente 28800. |
| ENABLE_SIMULATOR | Activa únicamente el adaptador de desarrollo. |
| API_INTERNAL_URL | Dirección privada de API que usa el servidor web. |
| VIGILAY_API_URL | API alcanzable desde Vigilay Local, normalmente `http://localhost:8000`; se usa para validar aliases Frigate sin entregar el secreto al navegador. |
| ORIGIN | Origen público que usa adapter-node. |
| TEST_DATABASE_URL | Esquema separado cuyo nombre termina en `_test`. |
| VIGILAY_E2E_EMAIL / VIGILAY_E2E_PASSWORD | Cuenta de desarrollo para pruebas de navegador. |
| PLAYWRIGHT_CHANNEL | Opcional: `msedge` para usar Edge instalado. |
| CLOUDFLARE_ACCOUNT_ID | Alternativa de despliegue a la configuración desde Administración → Sistema. |
| CLOUDFLARE_STREAM_API_TOKEN | Alternativa de despliegue; si se registra desde la web, se almacena cifrado en MySQL. |
| FFMPEG_PATH | Ruta configurable de FFmpeg en el equipo del agente. |
| V380_DECODER_PATH | Ruta local de V380Decoder en el equipo del agente. |
| FRIGATE_API_URL | API interna de Frigate; debe ser accesible sólo desde el API de Vigilay, nunca desde Internet ni desde el navegador. |
| FRIGATE_TIMEOUT_SECONDS | Tiempo máximo de consulta a Frigate. |
| FRIGATE_GATEWAY_PORT | Puerto loopback del proxy autenticado local; valor normal `8788`. |
| CLOUDFLARED_PATH | Ejecutable de Cloudflare Tunnel; el contenedor local ya lo incorpora. |
| STREAM_IDLE_TIMEOUT_SECONDS | Gracia sin espectadores antes de detener FFmpeg. |
| STREAM_START_TIMEOUT_SECONDS | Espera máxima de confirmación al abrir el visor. |

Generación manual de claves:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
python -c "import base64,secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())"
```

Usar claves independientes. Guardar SESSION_SECRET, INTERNAL_PROXY_SECRET, CREDENTIAL_ENCRYPTION_KEY y contraseñas MySQL en el gestor de secretos del entorno de despliegue. Nunca usar prefijos PUBLIC_ para secretos.

La autenticación del gateway de Frigate no se configura manualmente: Vigilay Local genera un token aleatorio diferente para cada sede, lo conserva cifrado en `frigate_connections` y lo reutiliza al reconectar. Cambiar `INTERNAL_PROXY_SECRET` del pod central no desconecta los gateways de clientes.

Las credenciales EZVIZ, Imou, V380 y RTSP genéricas se guardan cifradas con AES-GCM en `camera_credentials`. Para importar una instalación antigua se ejecuta `migrar-camaras-mysql.ps1`: comprueba la conexión, aplica Alembic, importa las cámaras y solo después retira de `.env` las URLs, usuarios y contraseñas individuales. No se requiere Docker para este flujo.
