# Vigilay Mobile y Vigilay Desktop

Mobile sirve al usuario del negocio. Desktop instala y mantiene el grabador de
una sede Windows. Ninguna de las dos aplicaciones distribuye claves MySQL.

## Mobile

`apps/mobile` es un proyecto Capacitor Android que reutiliza Vigilay Web y sus
permisos. WebRTC y audio deben probarse en un teléfono físico.

```powershell
cd apps/mobile
npm ci
npm test
npm run native:android
```

## Desktop y Recorder

`apps/desktop` es Tauri 2. El técnico inicia sesión con una cuenta administradora,
selecciona empresa/sede y configura cámaras, ruta, retención, reserva de disco y
detector. El motor propio:

- consume RTSP/RTSPS y HTTP/MJPEG;
- acepta la salida RTSP del puente V380;
- detecta personas con YOLO o movimiento con OpenCV;
- guarda MP4 y JSON por fecha/cámara;
- reconecta streams y reinicia trabajadores interrumpidos;
- elimina clips por retención y espacio reservado;
- publica un catálogo autenticado con HTTP Range.

Pulsa **Iniciar grabación** después de registrar al menos una cámara. Desktop
espera a que el motor responda antes de publicar la conexión. Al cerrar la ventana
permanece en la bandeja; **Salir y detener grabación** finaliza motor y túnel.

Para una sede que ya tiene cámaras en Vigilay Web, selecciona la empresa y la sede
y pulsa **Sincronizar accesos para grabación**. El comando requiere una cuenta
`SUPER_ADMIN` o `CLIENT_ADMIN`, recupera las fuentes cifradas mediante una operación
auditada y las guarda en la configuración privada del grabador sin mostrarlas en la
interfaz. La sincronización reemplaza el catálogo local para evitar mezclar cámaras
de sedes diferentes.

## Desarrollo y empaquetado

```powershell
cd apps/desktop
npm ci
npm run desktop:dev
```

En desarrollo se usa `.venv` y `tools.vigilay_recorder.agent`. Para construir los
instaladores:

```powershell
& .\.venv\Scripts\python.exe -m pip install -r tools/vigilay_recorder/requirements-build.txt
cd apps/desktop
npm run desktop:build
```

El script empaqueta OpenCV, YOLO y `yolo11n.pt` en un ejecutable auxiliar y Tauri
lo incorpora a MSI/NSIS. El equipo destino no necesita Python. Debe contar con
`cloudflared` o `CLOUDFLARED_PATH`; para una prueba local puede usarse
`VIGILAY_RECORDER_LOCAL_ONLY=true`.

## Almacenamiento y límites

```text
<ruta>/AAAA-MM-DD/<camera-id>/HH-MM-SS_movimiento.mp4
<ruta>/AAAA-MM-DD/<camera-id>/HH-MM-SS_movimiento.json
```

Desktop valida la ruta y escritura. El motor impide salir de esa raíz. V380 aún
necesita el puente propietario cuando no ofrece RTSP directo; los videos que sólo
existen en microSD no pueden recuperarse por RTSP. Tras reiniciar Windows se abre
Desktop y se inicia nuevamente la grabación; todavía no se instala como servicio.
Los instaladores actuales no están firmados digitalmente.
