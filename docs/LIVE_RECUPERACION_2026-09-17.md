# Recuperación y rendimiento del live — 17/09/2026

Alcance: Cenfelec, Sede principal; tres cámaras reales. No se cambió el gestor MySQL ni se introdujo Redis/Rust.

## Causas comprobadas

- El agente de publicación no estaba ejecutándose; su último heartbeat era de muchas horas antes. La etiqueta ONLINE de una cámara no garantizaba que existiera un publicador.
- Imou y V380 tenían vacío `frigate_camera_name`. Se verificó cada IP contra las fuentes de go2rtc y se restauraron `imou` y `calle`; EZVIZ conserva `cuarto`.
- Docker/Frigate WebRTC y V380Decoder escuchaban simultáneamente en el puerto TCP 8555. El puente ahora usa 8556; Frigate conserva 8555.
- Local descartaba por defecto 14 fotogramas por lectura. `grab()` puede esperar fotogramas futuros: no es un mecanismo de vaciado instantáneo.
- Existía una carrera al cambiar de cámara durante una lectura: un fotograma de la anterior podía publicarse con la nueva selección. También se reutilizaban miniaturas antiguas y se declaraba conexión antes de recibir imagen.
- El formulario podía borrar la asignación de Frigate si omitía ese campo.
- Se decodificaba H.265 de alta resolución para vistas pequeñas y detección. Se midieron 533% de CPU en Frigate y cuatro procesadores lógicos en Windows; las mediciones son muestras, no un benchmark controlado.
- La V380 entregaba DTS repetidos/fuera de orden. Se registraron 49 reconexiones por hora antes de los cambios. Se aplica reloj de recepción en su entrada de Frigate. Se probó además normalizar el restream de go2rtc mediante FFmpeg, pero esa variante produjo timeouts y se retiró: se conserva el restream RTSP nativo que sí entregó imagen.
- El agente consideraba listo un proceso FFmpeg solo por sobrevivir 350 ms. Un proceso puede existir sin publicar video; esto provocaba intentos WHEP prematuros, incluyendo HTTP 409.

## Configuración aplicada

| Cámara | Grabación | Live / detección | Fuente |
| --- | --- | --- | --- |
| EZVIZ | `cuarto`, resolución original | `cuarto_live`, 768×432, H.265 | Substream `/ch1/sub` verificado |
| Imou | `imou`, resolución original | `imou_live`, 640×352, H.264 | Substream `subtype=1` verificado |
| V380 | `calle` | `calle_live`, misma fuente; detección 384×648 | Puente RTSP 8556; relay del fabricante |

Frigate concentra conexiones y graba el stream original. El publicador convierte el live a H.264/Opus compatible con Cloudflare WebRTC. La V380 sigue dependiendo del relay del fabricante porque su antigua IP LAN no respondió; no se cambió su identidad ni se crearon cámaras adicionales.

El equipo local usa `FRIGATE_LIVE_STREAM_SUFFIX=_live` y `VIGILAY_LOCAL_PREFER_RESTREAM=true`. **No configurar ese sufijo en otra sede hasta crear y verificar sus aliases `_live`.** El agente puede volver al alias principal si el alternativo no existe.

Para la V380, Local usa ahora `V380_LOCAL_TRANSPORT=mjpeg`: consume `/stream.mjpg` del puente, evitando su RTSP inestable en el visor local. No cambia los protocolos de grabación ni WebRTC. Esta alternativa recupera imagen pero no aumenta la cadencia real entregada por el dispositivo/relay.

El supervisor de `scripts/iniciar-agente-stream.ps1` reinicia salidas fallidas y evita dos supervisores del mismo proyecto. Tanto `iniciar.ps1` como `scripts/iniciar-vigilay.ps1` lo arrancan mediante `asegurar-agente-stream.ps1`. No se instaló una tarea de inicio de Windows.

FFmpeg informa progreso por un canal interno sin secretos. El agente anuncia `live` después de recibir progreso de fotogramas, aplica timeout RTSP y reinicia publicadores sin progreso. Esto no sustituye la comprobación de imagen decodificada del navegador.

## Verificación y límites

- 36 pruebas dirigidas de Local, streaming y rendimiento del publicador aprobadas; Ruff y formato sin errores. La base de pruebas es independiente de la base real.
- Pruebas de navegador reales con los proveedores existentes: se recibieron fotogramas decodificados y dimensiones no nulas en las tres cámaras. Se cerraron las sesiones de diagnóstico al terminar.
- Pruebas simultáneas de Local de 20 segundos: 105 JPEG en cada miniatura EZVIZ/Imou y 191–197 JPEG en la V380 seleccionada, sin errores de lectura. No equivale a una prueba de estabilidad de horas.
- Muestra posterior de Frigate: 120% de CPU frente a 533% durante la carga inicial. No son condiciones idénticas, ni una garantía de reducción porcentual fija.
- Tras normalizar timestamps, la muestra de Frigate mantuvo los mismos procesos FFmpeg para las tres cámaras, con cero reconexiones desde ese reinicio. Persistieron algunos stalls de la V380; no se declara ausencia absoluta de cortes.
- Hubo intentos WHEP con 409 y timeouts durante el diagnóstico. Tras añadir readiness por progreso y recuperación de publicadores detenidos, la última prueba recibió las tres cámaras al primer intento: EZVIZ 4,429 s, Imou 4,403 s y V380 8,135 s desde el inicio de negociación; 3,1–4,4 s correspondían al POST WHEP. Se verificaron respectivamente 83, 85 y 50 fotogramas decodificados, con dimensiones de video no nulas. Esto **no incluye** todo el flujo de login/API ni demuestra latencia de extremo a extremo desde el clic.
- La web remota usa WebRTC; el panel Local heredado sigue usando MJPEG. No se ha presentado este último como WebRTC.
- No se hizo despliegue nuevo en Bunny ni push a GitHub durante esta intervención. Se aplicaron los cambios al agente, Local, vínculos MySQL y Frigate de esta instalación. Las grabaciones existentes no se borraron. Copia previa de configuración: `F:\ia\frigate\config\config.yaml.bak-live-port-20260917`.

### Estado de cierre (supersede las muestras intermedias)

- Con los servicios nuevamente activos y sin reiniciar Frigate durante la prueba, las tres cámaras entregaron video WebRTC al primer intento: EZVIZ 5,225 s, Imou 5,048 s, V380 5,103 s. POST WHEP: 3,8–4,1 s. Se recibieron 82, 78 y 81 fotogramas decodificados. Imou utilizó el fallback al stream principal en esa ejecución. Son muestras, no percentiles ni garantía de arranque siempre en cinco segundos.
- Tras activar MJPEG para V380 Local, la prueba de 20 s recibió 90, 75 y **4** JPEG respectivamente, sin errores de lectura en esa ejecución. `/api/cameras/status` indicó las tres conectadas al terminar. La baja cadencia V380 y algunos timeouts previos persisten: no se declara fluidez ni estabilidad prolongada.
- **Pendiente real:** Frigate todavía reinicia la entrada V380 (`calle`): seis reconexiones desde el último reinicio y una muestra de 0 fps. No se debe afirmar que su grabación ya sea continua. La entrada directa vía LAN de esa cámara debe recuperarse/verificarse; su IP anterior no estaba disponible y el relay no permite demostrar estabilidad sostenida. No se enviaron credenciales a otras IP no identificadas en esta intervención.
- Las últimas pruebas de Local/MJPEG adicionales aprobaron 17 casos; las 36 pruebas dirigidas previas y las comprobaciones Ruff también pasaron. No se ejecutó toda la suite del proyecto.

## Preparación de la publicación v0.2.1

La revisión posterior para GitHub aprobó la suite completa: **85 pruebas**, Ruff
y formato en los directorios de CI, `npm run check`, `npm run build`, validación
de Compose y análisis sintáctico de los scripts PowerShell. La configuración
privada de Frigate y `.env` no se incluyen en las imágenes ni en Git.
Actions debe validar además el arranque del contenedor Local antes de publicar
las tres imágenes. Publicarlas no actualiza automáticamente Bunny ni las sedes.

## Rust

No hay evidencia que justifique una reescritura: los fallos medidos eran de supervisión, puertos, configuración, timestamps, carga de decodificación y preparación del publicador. FFmpeg y go2rtc ya procesan el video fuera de Python. Cambiar el lenguaje no elimina el relay V380 ni el tiempo de negociación del proveedor.

Referencias técnicas: [restream de Frigate](https://docs.frigate.video/configuration/restream/), [live de Frigate](https://docs.frigate.video/configuration/live/), [timestamps de FFmpeg](https://ffmpeg.org/ffmpeg-formats.html).

Diagnóstico de solo lectura, sin imprimir credenciales: `python scripts/inspect_live.py`.
