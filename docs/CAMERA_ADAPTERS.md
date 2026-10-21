# Adaptadores de cámara

Vigilay separa tres responsabilidades:

1. Los adaptadores de `services/camera-adapters` prueban conectividad y aplican
   configuración compatible con cada dispositivo.
2. El agente de vivo consume la fuente RTSP autorizada sólo mientras existen
   espectadores.
3. Vigilay Recorder consume RTSP/RTSPS o HTTP/MJPEG, detecta actividad y guarda
   los clips en la ruta elegida en Desktop.

EZVIZ, Imou y cámaras genéricas se registran con su URL RTSP. V380 usa la salida
RTSP que publica `V380Decoder.exe`; el puente propietario continúa siendo
necesario para modelos que no ofrecen RTSP directo. El grabador, catálogo,
retención, autenticación y reproducción son componentes propios de Vigilay.

Las credenciales se cifran en MySQL para las operaciones centrales y se guardan
en el archivo privado de Desktop para el proceso local. Nunca se devuelven al
navegador ni se incluyen en logs.
