# Vigilay Local en Docker — v0.2.1

La imagen `ghcr.io/developerlhc/vigilay-local:v0.2.1-build-N` contiene el panel
Python, administración de conexiones y empresa/sede, previsualización y controles
compatibles con cada cámara. Usa un proceso Waitress con hilos, usuario sin
privilegios, healthcheck y persistencia fuera de la imagen. No incluye `.env`,
credenciales de cámaras, modelos YOLO ni ejecutables Windows.

## Instalar con el stack local

1. Configura `.env` con **tu BDMYSQL existente**, clave de cifrado correspondiente
   a esos datos y el resto de variables del stack. No crees otra base para Local.
2. Detén el panel Python anterior antes de ocupar 5000; conserva el agente de
   streaming dedicado y Frigate. Para probar sin interrumpirlo, usa
   `VIGILAY_LOCAL_PORT=5002` y abre `http://localhost:5002`.
3. Ejecuta desde la raíz del repositorio:

```powershell
docker compose --profile local up -d --build vigilay-local
docker compose logs --tail 60 vigilay-local
```

Abre `http://localhost:5000`. El servicio publica exclusivamente en loopback,
no en todas las interfaces; no lo expongas en Bunny ni mediante un túnel público.
No sustituye al login multiempresa de Vigilay Web. El guard de Host/Origin del
contenedor rechaza peticiones de otros dominios.

En **Configuración**, selecciona una empresa y una sede existentes, o créalas
desde el panel. La sede debe pertenecer a la empresa. La identidad se guarda en
`.local/vigilay-local.json`, compartida con el gateway de esa instalación.
Reinicia Local tras cambiar de identidad si el panel lo indica:

```powershell
docker compose restart vigilay-local
```

No copies la identidad de una sede a otra. La existencia y pertenencia se
comprueban en MySQL, no únicamente en el archivo. Conserva la misma clave de
cifrado que corresponde a las cámaras de esa base; no la regeneres al instalar.

En Linux, el directorio montado `.local` debe ser escribible por UID/GID 10001;
no uses permisos globales 777. En Docker Desktop el bind mount se gestiona desde
el anfitrión. Respáldalo antes de trasladar una instalación.

## Si la API está en Bunny

No necesitas levantar otra API local. Configura en `.env`:

```dotenv
VIGILAY_LOCAL_API_URL=https://URL-DE-TU-VIGILAY.bunny.run
VIGILAY_LOCAL_RESTREAM_URL=rtsp://host.docker.internal:8554
```

Y arranca solamente el panel:

```powershell
docker compose --profile local up -d --build --no-deps vigilay-local
```

`BDMYSQL` debe ser alcanzable desde esa sede. Local mantiene el acceso directo a
MySQL del proyecto Python; dockerizarlo no convierte ese acceso en una API remota.
El gateway autenticado por sede y el agente dedicado se mantienen por separado.

Para consumir una versión publicada sin compilar, configura `VIGILAY_LOCAL_IMAGE`
con la etiqueta exacta que haya terminado de publicar Actions, y ejecuta:

```powershell
docker compose --profile local pull vigilay-local
docker compose --profile local up -d --no-build --no-deps vigilay-local
```

Si GHCR indica acceso denegado, verifica la visibilidad/permisos del paquete y
autentica Docker con una credencial con permiso de lectura. Nunca la agregues al
Dockerfile ni al repositorio.

## Cámaras, Frigate y V380

- Cámaras RTSP: el contenedor necesita ruta hacia sus IP LAN. Registrar una IP
  conocida no requiere descubrimiento automático.
- Frigate: por defecto se usa `rtsp://frigate:8554/<alias>` para cámaras vinculadas,
  evitando abrir otra conexión al dispositivo. Frigate debe compartir la red
  Compose con alias `frigate`. Si está fuera, usa `VIGILAY_LOCAL_RESTREAM_URL`
  con su IP LAN o `rtsp://host.docker.internal:8554` para el anfitrión.
- Descubrimiento: configura `VIGILAY_LOCAL_LAN_CIDR` con tu LAN real, por ejemplo
  `192.168.1.0/24`. No se escanea la red Docker por accidente. Se rechazan rangos
  públicos y mayores que /24. Docker puede limitar descubrimiento broadcast;
  el escaneo de puertos no sustituye todos los protocolos de descubrimiento.
- V380 con SDK propietario: `V380Decoder.exe` sigue ejecutándose en Windows.
  Linux no puede arrancarlo ni reiniciarlo. Local consume su RTSP desde
  `V380_EXTERNAL_BRIDGE_HOST=host.docker.internal`, o el alias de Frigate. Los
  controles que dependan del puente requieren que también responda su puerto HTTP.
- El contenedor no inicia otro agente WHIP ni instala FFmpeg del publicador:
  mantén `scripts/iniciar-agente-stream.ps1` y un solo publicador por cámara.
  `LOCAL_AI_ENABLED=false`: Frigate sigue encargado de IA y grabaciones.

Desde v0.2.1, Compose pasa `FRIGATE_LIVE_STREAM_SUFFIX` y
`VIGILAY_LOCAL_PREFER_RESTREAM` al panel. Usa `_live` sólo cuando esos aliases
estén creados y verificados en go2rtc. El stream de grabación no cambia.
`V380_LOCAL_TRANSPORT=mjpeg` permite probar el visor HTTP del puente V380 si su
RTSP es inestable; no cambia el transporte remoto WebRTC ni garantiza estabilidad
del dispositivo. El puente nuevo usa RTSP 8556 y HTTP 8081; Frigate conserva
8555 para WebRTC. Los puertos guardados de cámaras existentes no se migran solos.

Docker documenta [el acceso al anfitrión mediante host.docker.internal](https://docs.docker.com/desktop/features/networking/networking-how-tos/).
No publiques los puertos de cámaras o Frigate en Internet para resolver conectividad.

## Verificación y publicación

`/healthz` comprueba el proceso HTTP, **no** certifica conectividad con MySQL,
cámaras ni Frigate. Comprueba también empresa/sede y la previsualización real.
GitHub Actions prueba el arranque, página principal y rechazo de Host/Origin en
un contenedor aislado sin datos reales antes de publicar las imágenes de la versión.
La publicación GHCR no implica despliegue Bunny ni actualización de las sedes.
