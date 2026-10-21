# Variables de entorno

La plantilla canónica es `.env.example`. Los secretos deben ser distintos por
instalación y nunca se versionan.

## Plataforma central

| Variable | Uso |
| --- | --- |
| `APP_ENV` | `development` o `production`. Producción exige HTTPS. |
| `WEB_ORIGIN` | Origen exacto permitido para cookies y CSRF. |
| `DATABASE_URL` / `BDMYSQL` | Conexión MySQL; `BDMYSQL` admite la cadena del proveedor. |
| `DATABASE_POOL_SIZE` | Conexiones por proceso, entre 1 y 10. |
| `SESSION_SECRET` | Secreto aleatorio de al menos 32 caracteres. |
| `CREDENTIAL_ENCRYPTION_KEY` | Clave AES de 32 bytes codificada en base64. |
| `INTERNAL_PROXY_SECRET` | Autenticación privada entre Web y API. |
| `SESSION_COOKIE_SECURE` | Debe ser `true` en producción. |
| `ENABLE_SIMULATOR` | Habilita únicamente cámaras de demostración. |

## Video en vivo

| Variable | Uso |
| --- | --- |
| `CLOUDFLARE_ACCOUNT_ID` / `CLOUDFLARE_STREAM_API_TOKEN` | Credenciales globales del vivo WebRTC; se configuran juntas. |
| `FFMPEG_PATH` | Ejecutable FFmpeg del agente de vivo. |
| `VIGILAY_REALTIME_URL` | WebSocket público que usa el agente de la sede. |
| `STREAM_IDLE_TIMEOUT_SECONDS` | Tiempo sin espectadores antes de cerrar FFmpeg. |
| `STREAM_START_TIMEOUT_SECONDS` | Máximo de inicio de una publicación. |
| `STREAM_LIVE_HEIGHT`, `STREAM_LIVE_FPS`, `STREAM_LIVE_BITRATE_KBPS` | Perfil exclusivo del vivo; no modifica los clips locales. |

## Vigilay Recorder

`RECORDING_API_URL`, `RECORDING_GATEWAY_TOKEN` y
`RECORDING_TIMEOUT_SECONDS` sirven para desarrollo cuando API y grabador están
en el mismo equipo. En una sede real, Desktop genera un token aleatorio, abre un
túnel saliente y registra la conexión de forma automática.

La ruta, retención, reserva de disco, detector, confianza y cámaras no son
variables de entorno. Desktop las guarda en su directorio privado de aplicación
como `recorder.json` y comprueba escritura antes de iniciar.

Variables opcionales de Desktop:

| Variable | Uso |
| --- | --- |
| `CLOUDFLARED_PATH` | Ruta alternativa de `cloudflared`. |
| `VIGILAY_RECORDER_EXECUTABLE` | Motor externo para desarrollo o diagnóstico. El instalador normal ya lo incluye. |
| `VIGILAY_RECORDER_LOCAL_ONLY=true` | Omite el túnel; sólo sirve si API alcanza `127.0.0.1:8788`. |

## Vigilay Local heredado

`VIGILAY_LOCAL_PORT`, `VIGILAY_LOCAL_API_URL`, `VIGILAY_LOCAL_LAN_CIDR`,
`V380_EXTERNAL_BRIDGE_HOST` y `V380_LOCAL_TRANSPORT` pertenecen al panel local
heredado. No sustituyen Vigilay Desktop ni Vigilay Recorder.
