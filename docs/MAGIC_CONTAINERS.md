# Vigilay Web en Bunny Magic Containers

La imagen que se publica para el frontend es `ghcr.io/<propietario>/vigilay-web:<commit-sha>`, construida exclusivamente con `apps/web/Dockerfile`. Escucha en el puerto 3000 y expone `/login` como comprobación de salud.

En Magic Containers el contenedor debe llamarse `web` y tener un endpoint HTTP/CDN dirigido al puerto 3000. Configurar manualmente estas variables:

| Variable | Valor esperado |
| --- | --- |
| `HOST` | `0.0.0.0` |
| `PORT` | `3000` |
| `ORIGIN` | URL HTTPS pública exacta de Vigilay |
| `API_INTERNAL_URL` | Dirección alcanzable del API de Vigilay; en un mismo pod, `http://localhost:8000` |
| `INTERNAL_PROXY_SECRET` | El mismo secreto privado configurado en el API |

La web es el único contenedor público. No contiene MySQL, Redis, Frigate ni el agente LAN. Si API y worker también se ejecutan en la misma aplicación de Magic Containers, se agregan como contenedores separados; al compartir red del pod, el API debe escuchar en un puerto distinto y la web lo alcanza mediante `localhost:8000`.

El workflow `.github/workflows/ci.yml` construye y sube `vigilay-web` a GHCR en cada `push` a `main`. Publica una etiqueta legible con el formato `v0.1.0-build-N` y el alias `latest`. Si se configuran la variable de repositorio `BUNNYNET_APP_ID` y el secreto `BUNNYNET_API_KEY`, el job `deploy-web-magic-container` actualiza automáticamente el contenedor `web` a esa versión. El registro GHCR debe estar agregado previamente en Magic Containers.

Frigate y Vigilay Local permanecen en la sede: necesitan acceso a la LAN de las cámaras. La plataforma alojada consulta Frigate mediante una conexión privada/VPN; nunca se publica su puerto interno 5000.
