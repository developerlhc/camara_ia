# Revisión de vivos y grabaciones — 16 de septiembre de 2026

Se contrastó `DIAGNOSTICO_RENDIMIENTO_VIGILAY.md` con el código actual y el Frigate
local. No se modificaron credenciales, empresa/sede ni retención de grabaciones.
No se desplegó a Bunny ni se publicaron imágenes en GHCR.

## Hallazgos comprobados

- El publicador actual **siempre recodificaba con libx264**, a diferencia de la
  mención de copia de video del diagnóstico. No limitaba resolución, FPS ni hilos.
  Tres cámaras podían competir con detección/recording por la CPU del host.
- Dos muestras `docker stats` mostraron Frigate al 354,53 % y 450,79 % de CPU
  (aproximadamente 3,5–4,5 núcleos). Son muestras, no una prueba de saturación
  sostenida ni una medición de latencia de video. Había pruebas de desarrollo en curso.
- Autenticación ejecutaba hasta cinco SELECT consecutivos contra MySQL. El agente
  retenía una conexión durante comprobaciones RTSP/arranque FFmpeg.
- La vista de cámaras no iniciaba video. WebRTC anunciaba «en vivo» al conectar
  transporte, incluso sin recibir fotogramas; no acotaba una negociación atascada.
- El proxy API descartaba Range, estado 206/416 y cabeceras del recurso. Las
  grabaciones se agrupaban hasta una hora y el listado consultaba siempre 24 horas.
- Frigate real tiene `record.enabled=true` y roles record/detect en cuarto, calle e
  imou, pero **continuous.days=0 y motion.days=0**. Alertas y detecciones conservan
  10 días en modo motion: no hay archivo continuo 24/7.
- En tres consultas, cuarto/EZVIZ tenía cero segmentos durante la última hora;
  calle e imou sí tenían segmentos. Esto es compatible con retención solo por
  eventos; no prueba un fallo de la tarjeta SD. Clips locales de calle/imou
  respondieron HTTP 200 y video/mp4.
- La versión local de Frigate devolvió 200 aun solicitando Range; conservar
  cabeceras no convierte ese origen en un servidor de rangos. La corrección evita
  perder 206/416 cuando el origen sí los devuelve. No se promete búsqueda inmediata
  ni compatibilidad universal de MP4 en Safari.
- No existe adaptador para catálogo/reproducción de SD en el proyecto: ni el
  contrato de adapters ni las rutas lo implementan. RTSP de vivo y PTZ no implican
  soporte de almacenamiento/replay. Se necesita conocer modelo, firmware y servicio
  compatible (p. ej. ONVIF Profile G o API del fabricante); no se simuló ese soporte.

## Cambios

- Autenticación agrupada en **un SELECT**, sin caché de permisos: se siguen
  comprobando expiración/revocación de sesión, estado de usuario, rol y empresa.
- Agente: configuración agrupada y conexión MySQL devuelta **antes** de RTSP/WHIP;
  relee sesiones activas al confirmar, sin resucitar espectadores que ya cerraron.
- Vivo: máximo 1280×720, 15 FPS, GOP de un segundo, tope 2000 kbit/s y dos hilos
  por códec por defecto. Parámetros documentados en ENVIRONMENT_VARIABLES. No se
  alteran los originales grabados por Frigate ni se abre otro consumidor RTSP por
  espectador. El restream go2rtc existente sigue siendo la fuente preferida.
- Cámaras: empresa/sede válidas predeterminadas y recordadas por usuario; cuatro
  cámaras por página, autoplay silenciado, solo tarjetas visibles; dos peticiones
  de arranque simultáneas como máximo. Pausa al ocultar pestaña/abrir modal; cierre
  al cambiar ámbito, navegar o recibir tarde una sesión ya cancelada.
- WHEP: timeout, reintentos con espera creciente y jitter, margen de recuperación
  de desconexión breve, detección de ausencia de fotogramas, aborto/DELETE/cierre
  de recursos. «En vivo» requiere fotograma decodificado en navegadores modernos.
- WebSocket de detalle: sondeo de respaldo SQL de 1 segundo con actividad y 10
  segundos en reposo, en lugar de 0,25/2; revalidación periódica de sesión/ACL.
  El mosaico usa heartbeats espaciados con jitter, no cuatro sockets que sondeen
  constantemente MySQL. `npm start` ejecuta el servidor con relay WebSocket.
- Dashboard ya no bloquea sus cámaras esperando a un gateway Frigate desconectado.
- Grabaciones: fecha/hora local explícita, validación de rango máximo siete días,
  cancelación lógica de respuestas viejas, error distinguido de listado vacío,
  fragmentos agrupados de hasta cinco minutos para segmentos normales de Frigate,
  límites de fecha recortados, reproducción consecutiva hacia adelante.
- Descargas: Content-Disposition attachment para descarga explícita, transferencia
  incremental (no cargar todo en RAM), propagación de Range/If-Range/206/416 y
  cierre de recursos. Se mantiene autenticación/autorización en cada recurso.

## Verificación

- 54 pruebas backend existentes pasaron; 22 pruebas de medios/streaming pasaron
  posteriormente (incluyen repetición de streaming). Dos pruebas adicionales
  confirmaron liberación del pool/cierre durante arranque y perfil FFmpeg.
- Cuatro pruebas Playwright con Chrome pasaron usando API/WHEP simulados:
  ámbito/autoplay, cierre tardío, fechas/descarga/orden y error de almacenamiento.
  Estas pruebas **no** demuestran transporte WebRTC real, UDP/NAT ni latencia WAN.
- `npm run check`, `npm run build`, Ruff y revisión de whitespace satisfactorios.
- Herramienta de diagnóstico local, sin imprimir secretos:

  ```powershell
  .\.venv\Scripts\python.exe scripts\diagnosticar_medios.py
  ```

  Sus tiempos incluyen docker exec; no deben interpretarse como tiempos puros de
  Frigate ni como latencia del despliegue Bunny.

## Activación y medición pendiente

Reconstruir API/web/gateway con los cambios y reiniciar el agente local supervisado
para cargar el perfil FFmpeg. No iniciar un segundo agente paralelo. En Bunny se
deben actualizar las imágenes de API y web mediante el flujo habitual; estos
cambios locales no actualizan automáticamente los contenedores remotos.

Comparar con la misma cámara/red:

1. Duración de `/live/start` en Network y cabecera `Server-Timing` (API).
2. Log `Publisher started ... elapsed_ms ... request_age_ms` del agente; indica
   arranque de proceso, no primer fotograma remoto.
3. Atributo `data-first-frame-ms` del video: desde montar WHEP hasta primer
   fotograma, incluyendo reintentos, **no** desde el click inicial.
4. `chrome://webrtc-internals`: RTT del par seleccionado, pérdida, jitter y frames
   decodificados; CPU local y subida con una y varias cámaras.

No se declara una mejora porcentual o tiempo objetivo alcanzado sin esa medición.
Cambiar de motor de base de datos no arregla la recodificación, la retención ni
ICE/NAT. Tampoco un WebSocket transporta por sí mismo el video WebRTC.

Para grabar continuamente hace falta elegir días de retención y comprobar espacio
disponible en la sede. La retención actual se conservó hasta recibir esa decisión.

## Referencias de protocolo

- [Cloudflare: WHEP en navegador y cierre de sesiones](https://developers.cloudflare.com/stream/examples/browser-based-webrtc/).
- [Frigate: restream go2rtc](https://docs.frigate.video/configuration/go2rtc/).
- [Frigate: clips y limitación de MP4 progresivo en Safari](https://docs.frigate.video/integrations/api/recording-clip-camera-name-start-start-ts-end-end-ts-clip-mp-4-get/).
