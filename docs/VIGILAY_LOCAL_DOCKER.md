# Vigilay Local en Docker

El perfil `local` mantiene el panel heredado para diagnóstico y migración:

```powershell
docker compose --profile local up -d --build vigilay-local
```

Abre `http://localhost:5000` o el puerto indicado por `VIGILAY_LOCAL_PORT`. No
ejecutes a la vez `iniciar.ps1` en el mismo puerto.

Este contenedor no ejecuta Vigilay Recorder, no contiene el puente propietario
V380 y no debe recibir acceso directo a Internet. Para una instalación nueva usa
Vigilay Desktop en el equipo Windows de la sede; Desktop configura cámaras,
almacenamiento, retención y el canal autenticado con la plataforma central.

El panel puede descubrir equipos sólo si se define una subred LAN real de máximo
`/24` en `VIGILAY_LOCAL_LAN_CIDR`. Las pruebas de hardware están deshabilitadas
por defecto. No publiques RTSP, puertos de cámara ni el puerto local del grabador.
