# Operación de Vigilay

## Plataforma central

```powershell
docker compose up -d --build
docker compose ps
```

La web escucha en `127.0.0.1:3000`, API en `127.0.0.1:8000` y MySQL en
`127.0.0.1:3306`. En producción, sólo la web pública debe quedar expuesta.

## Sede Windows

1. Instala Vigilay Desktop con MSI o NSIS.
2. Instala `cloudflared` o configura `CLOUDFLARED_PATH`.
3. Para V380 sin RTSP nativo, inicia primero el puente `V380Decoder.exe` y usa su
   salida `rtsp://127.0.0.1:8556/live`.
4. Inicia sesión, selecciona empresa/sede y registra cada cámara.
5. Elige una ruta absoluta, retención, reserva de disco y detector.
6. Pulsa **Iniciar grabación**.

Cerrar la ventana minimiza Desktop a la bandeja y mantiene grabador, túnel y
heartbeats. Para finalizar realmente, usa **Salir y detener grabación** en la
bandeja o el botón **Detener** antes de salir.

Después de reiniciar Windows se debe abrir Desktop e iniciar la grabación; esta
versión todavía no instala un servicio de inicio automático.

Los clips se guardan en:

```text
<ruta>/AAAA-MM-DD/<camera-id>/HH-MM-SS_movimiento.mp4
<ruta>/AAAA-MM-DD/<camera-id>/HH-MM-SS_movimiento.json
```

## Diagnóstico

- Desktop indica `Grabando` y cantidad de cámaras.
- Web debe listar grabaciones en un intervalo de hasta siete días.
- Si el motor local deja de responder, el heartbeat publica `OFFLINE`.
- Un `502` de `/api/v1/media/*` indica que la sede está desconectada, el túnel no
  responde o la credencial fue reemplazada.
- Las descargas admiten HTTP Range; un reproductor puede reanudar sin cargar todo
  el archivo en memoria.

## Copias de seguridad

Respalda MySQL, `CREDENTIAL_ENCRYPTION_KEY` y la carpeta de grabaciones de cada
sede. Perder la clave impide descifrar credenciales. La limpieza elimina clips
vencidos y luego los más antiguos si no se respeta la reserva mínima de disco.
