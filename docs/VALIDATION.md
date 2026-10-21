# Validación de la implementación propia de grabación

Fecha de revisión: 20 de octubre de 2026.

## Resultado

- La aplicación activa no registra rutas `/api/v1/frigate/*`.
- Vigilay Recorder supervisa múltiples cámaras, reconecta streams, detecta con
  OpenCV/YOLO, genera MP4 H.264 + JSON y aplica retención/reserva de disco.
- Desktop configura la ruta, registra cámaras, inicia/detiene el motor, mantiene
  el proceso en bandeja y publica un enlace autenticado por sede.
- Web consulta `/api/v1/media/events` y `/api/v1/media/recordings`; la API vuelve
  a comprobar empresa, sede y permiso de cámara antes de cada clip.
- El motor se empaqueta como binario auxiliar. Los instaladores MSI y NSIS se
  construyeron incluyendo OpenCV, YOLO y `yolo11n.pt`.

## Comprobaciones ejecutadas

```text
pytest --noconftest ...                         32 passed
cargo test                                     2 passed
npm run check (web)                            0 errores, 0 advertencias
npm run build (web y desktop)                  correcto
ruff check / ruff format --check               correcto
vigilay-recorder.exe --help                    correcto
tauri build --config tauri.bundle.conf.json    MSI y NSIS correctos
docker compose config --quiet                  correcto
```

La suite integral que necesita MySQL no puede ejecutarse si Docker Desktop está
apagado. Las pruebas de video físico V380/EZVIZ/Imou requieren estar en la LAN de
la sede y no se sustituyen por una cámara sintética.

## Límites verificados

- V380 todavía necesita su decodificador/puente propietario cuando el dispositivo
  no ofrece RTSP directo.
- El histórico que existe sólo en la microSD no puede recuperarse mediante RTSP.
- Los instaladores generados no están firmados digitalmente.
