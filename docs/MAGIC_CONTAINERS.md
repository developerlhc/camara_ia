# Vigilay Web en Bunny Magic Containers

La imagen que se publica para el frontend es `ghcr.io/<propietario>/vigilay-web:v0.1.0-build-N`, construida exclusivamente con `apps/web/Dockerfile`. Escucha en el puerto 3000 y expone `/login` como comprobación de salud.

En Magic Containers el contenedor debe llamarse `vigilay-web` y tener un endpoint HTTP/CDN dirigido al puerto 3000. Configurar manualmente estas variables:

| Variable | Valor esperado |
| --- | --- |
| `HOST` | `0.0.0.0` |
| `PORT` | `3000` |
| `ORIGIN` | URL HTTPS pública exacta de Vigilay |
| `API_INTERNAL_URL` | Dirección alcanzable del API de Vigilay; en un mismo pod, `http://localhost:8000` |
| `INTERNAL_PROXY_SECRET` | El mismo secreto privado configurado en el API; sólo existe dentro del pod central |

La web es el único contenedor público. No contiene MySQL, Frigate ni el agente LAN. Si API y worker también se ejecutan en la misma aplicación de Magic Containers, se agregan como contenedores separados; al compartir red del pod, el API debe escuchar en un puerto distinto y la web lo alcanza mediante `localhost:8000`. La coordinación, los límites de acceso y los heartbeats se almacenan en MySQL; no se despliega Redis.

El workflow `.github/workflows/ci.yml` construye y sube `vigilay-api` y `vigilay-web` a GHCR en cada `push` a `main`. Publica una etiqueta legible con el formato `v0.1.0-build-N` y el alias `latest`. La versión se selecciona manualmente en Magic Containers; el workflow no intenta desplegar porque la actualización de imagen no garantiza un rollout directo y su API puede responder 503. El API aplica las migraciones Alembic antes de arrancar. El registro GHCR debe estar agregado previamente en Magic Containers.

El endpoint público del contenedor web admite HTTP y WebSocket. El navegador utiliza `/api/v1/realtime` y cada Vigilay Local mantiene una conexión saliente a `/api/v1/agent/realtime`; ambos se retransmiten internamente a `localhost:8000`. No se abre ningún puerto entrante en la sede. En `VIGILAY_REALTIME_URL` del cliente se coloca, por ejemplo, `wss://mc-xxxx.bunny.run/api/v1/agent/realtime`.

Frigate y Vigilay Local permanecen en la sede: necesitan acceso a la LAN de las cámaras. No reciben `INTERNAL_PROXY_SECRET`. Sin dominio, `frigate-gateway` usa temporalmente un Quick Tunnel saliente autenticado con una credencial aleatoria exclusiva de la sede y registra su URL efímera en MySQL. Bunny consulta únicamente el proxy restringido; nunca se publica directamente el puerto interno 5000. Para producción se reemplaza el Quick Tunnel por un túnel administrado con dominio, sin cambiar la separación empresa/sede.
