Quiero implementar streaming en vivo automático con Cloudflare Stream WebRTC
dentro de mi proyecto Vigilay.

IMPORTANTE:
Antes de modificar código, analiza la arquitectura actual completa del proyecto.
No reemplaces funcionalidades existentes ni reestructures innecesariamente.
Reutiliza los servicios, repositorios, modelos, sistema de cifrado y patrones
existentes.

==================================================
OBJETIVO FUNCIONAL
==================================================

Actualmente Vigilay puede conectarse a cámaras locales.

Para cámaras V380 Pro el flujo actual funciona así:

V380 Pro
    ↓
V380Decoder.exe
    ↓
RTSP local
    ↓
FFmpeg
    ↓ WHIP
Cloudflare Stream
    ↓ WHEP
Vigilay Web

Ya se comprobó manualmente que:

1. V380Decoder genera correctamente RTSP.
2. FFmpeg 9.x puede leer dicho RTSP.
3. FFmpeg tiene el muxer WHIP.
4. FFmpeg puede publicar correctamente hacia Cloudflare Stream mediante WHIP.
5. Cloudflare reproduce correctamente mediante WebRTC/WHEP.

Ahora quiero AUTOMATIZAR completamente ese proceso.

El usuario NO debe:
- entrar a Cloudflare;
- copiar una URL WHIP;
- ejecutar FFmpeg;
- conocer RTSP;
- conocer direcciones locales;
- conocer credenciales Cloudflare.

Debe simplemente entrar a Vigilay y pulsar:

"Ver en vivo"

==================================================
ARQUITECTURA DESEADA
==================================================

Usuario Vigilay
     ↓
POST /api/cameras/{cameraId}/live/start
     ↓
Backend Vigilay
     ↓
validar usuario y permisos sobre cámara
     ↓
obtener o crear Live Input Cloudflare
     ↓
ordenar al Vigilay Agent local iniciar transmisión
     ↓
Vigilay Agent
     ↓
resolver fuente RTSP local
     ↓
FFmpeg
     ↓ WHIP
Cloudflare Stream
     ↓ WHEP
Frontend Vigilay

Cuando el usuario cierre el visor o transcurra un período sin espectadores:

POST /api/cameras/{cameraId}/live/stop

y Vigilay debe detener FFmpeg.

==================================================
CLOUDFLARE
==================================================

Usar Cloudflare Stream Live Inputs API.

Endpoint para crear un Live Input:

POST
https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/stream/live_inputs

Autenticación:

Authorization: Bearer CLOUDFLARE_STREAM_API_TOKEN

El API Token tendrá permiso:

Stream Write

Al crear el Live Input Cloudflare devuelve, entre otros:

uid

webRTC.url
    = URL WHIP privada para publicar.

webRTCPlayback.url
    = URL WHEP para reproducir.

Ejemplo conceptual:

{
    "uid": "...",
    "webRTC": {
        "url": "https://customer-xxx.cloudflarestream.com/SECRET/webRTC/publish"
    },
    "webRTCPlayback": {
        "url": "https://customer-xxx.cloudflarestream.com/UID/webRTC/play"
    }
}

IMPORTANTE:

webRTC.url es una CREDENCIAL.

Nunca:
- retornarla al frontend;
- escribirla en logs;
- mostrarla en excepciones;
- guardarla en texto plano;
- incluirla en Git;
- incluirla en .env.example.

==================================================
VARIABLES DE ENTORNO
==================================================

Agregar al .env real:

CLOUDFLARE_ACCOUNT_ID=
CLOUDFLARE_STREAM_API_TOKEN=

Agregar solamente los nombres, sin valores reales, a .env.example.

Agregar:

FFMPEG_PATH=F:\ia\ffmpeg\bin\ffmpeg.exe

En producción esta ruta debe ser configurable y no estar hardcodeada.

El API Token de Cloudflare nunca debe estar en la base de datos.
Es una credencial global del backend y debe permanecer solamente en variables
de entorno.

==================================================
BASE DE DATOS
==================================================

Revisar primero las tablas actuales antes de crear nuevas.

Actualmente existen:

cameras
camera_credentials

NO duplicar información que ya exista.

Crear una tabla equivalente a:

camera_stream_provider

con columnas conceptuales:

id
camera_id
provider
provider_live_input_uid
publish_url_encrypted
playback_url
enabled
created_at
updated_at

camera_id debe tener UNIQUE si cada cámara tendrá un solo stream Cloudflare.

provider inicialmente:

cloudflare

provider_live_input_uid:

UID devuelto por Cloudflare.

publish_url_encrypted:

URL WHIP cifrada.

playback_url:

URL WHEP.

NO almacenar publish_url en texto plano.

Usar el mecanismo de cifrado EXISTENTE del proyecto basado en AES-256-GCM
y CREDENTIAL_ENCRYPTION_KEY.

Revisar:

camera_store.py
apps/api/src/vigilay/security.py

No implementar un segundo mecanismo criptográfico.

También crear una tabla para controlar ejecuciones:

camera_stream_sessions

campos conceptuales:

id
camera_id
user_id
status
started_at
last_heartbeat_at
stopped_at
stop_reason

status:

starting
live
stopping
stopped
error

No guardar PID como identificador permanente de negocio.
El PID puede manejarse en memoria por el agente.

Crear la migración SQL correspondiente utilizando el sistema de migraciones
que ya tenga el proyecto.

==================================================
SERVICIO CLOUDFLARE
==================================================

Crear un servicio, siguiendo las convenciones existentes, por ejemplo:

CloudflareStreamService

Debe contener métodos equivalentes a:

get_or_create_live_input(camera)
create_live_input(camera)
get_live_input(camera)
rotate_live_input_keys(camera) si la API actual lo permite
delete_live_input(camera)

get_or_create_live_input debe:

1. buscar configuración Cloudflare de la cámara;
2. si existe, reutilizarla;
3. si no existe, crear el Live Input;
4. guardar UID;
5. cifrar y guardar WHIP;
6. guardar WHEP;
7. retornar un objeto interno de dominio.

No debe devolver WHIP a controladores destinados al navegador.

Usar timeout HTTP.
Manejar errores Cloudflare.
Implementar reintentos solamente para errores transitorios.
No reintentar infinitamente.

==================================================
VIGILAY AGENT
==================================================

Implementar un StreamManager local.

Debe administrar procesos FFmpeg por camera_id.

Debe impedir dos FFmpeg simultáneos para la misma cámara.

Interfaz conceptual:

start_stream(camera_id, source_url, whip_url)
stop_stream(camera_id)
is_streaming(camera_id)
get_stream_status(camera_id)

Mantener un diccionario seguro/thread-safe similar a:

active_streams[camera_id] = process

Antes de iniciar:

1. verificar que la fuente de cámara esté disponible;
2. verificar que FFmpeg exista;
3. comprobar que no exista otro proceso;
4. iniciar FFmpeg;
5. esperar brevemente para comprobar que el proceso no murió;
6. actualizar estado a live.

==================================================
FUENTES DE CÁMARA
==================================================

NO asumir que todas las cámaras son V380.

Crear o reutilizar una abstracción:

CameraStreamResolver

Ejemplo conceptual:

resolve(camera) -> local_stream_url

Para V380:

- verificar/iniciar V380Decoder;
- esperar hasta que el RTSP local esté disponible;
- devolver su RTSP.

Actualmente una cámara V380 funcional usa un puente similar a:

rtsp://IP_LOCAL:PUERTO/live

NO hardcodear la IP 192.168.100.14.

Obtener la IP/interfaz/configuración desde el agente.

Para cámaras RTSP/ONVIF:

resolver la URL correspondiente utilizando las credenciales cifradas existentes.

Nunca guardar una URL con usuario/password en logs.

Diseñar CameraStreamResolver para agregar después:

V380
Hikvision
Dahua
Ezviz
ONVIF
RTSP genérico
NVR
DVR

sin cambiar StreamManager.

==================================================
FFMPEG
==================================================

Utilizar subprocess directamente desde Python.

NO ejecutar mediante:

cmd /c

NO construir una única cadena de shell.

Usar lista de argumentos y:

shell=False

Comando equivalente al que ya fue probado:

ffmpeg
-rtsp_transport tcp
-i SOURCE_RTSP
-map 0:v:0
-map 0:a:0?
-c:v libx264
-profile:v baseline
-level:v 3.1
-pix_fmt yuv420p
-preset veryfast
-tune zerolatency
-bf 0
-g 30
-maxrate 4000k
-bufsize 1500k
-flags +global_header
-c:a libopus
-b:a 128k
-ar 48000
-ac 2
-ts_buffer_size 16777216
-f whip
WHIP_URL

La pista `0:a:0?` conserva el audio real cuando la fuente RTSP lo ofrece. No sustituirla por `anullsrc`, porque eso hace que Vigilay publique silencio incluso en cámaras con micrófono.

No imprimir el comando completo porque contiene WHIP_URL.

Crear una función para sanitizar logs:

sanitize_secret(value)

Si aparece:

/webRTC/publish

no mostrar el secreto anterior.

Los logs deben poder decir:

Starting Cloudflare stream for camera 15

pero NUNCA:

https://customer-xxx.cloudflarestream.com/SECRET/webRTC/publish

==================================================
COMUNICACIÓN BACKEND ↔ AGENT
==================================================

Revisar cómo se comunica actualmente el backend Vigilay con el agente local.

Reutilizar el mecanismo existente.

Si ya existe WebSocket persistente, usarlo.

No abrir puertos públicos en el PC del cliente.

El agente debe mantener una conexión SALIENTE hacia Vigilay Cloud.

Mensaje conceptual:

{
  "type": "camera.stream.start",
  "camera_id": 15,
  "whip_url": "...",
  "request_id": "..."
}

La whip_url solamente puede viajar:

backend → agente

mediante conexión autenticada y cifrada TLS.

No enviarla al frontend.

Respuesta del agente:

{
  "type": "camera.stream.status",
  "camera_id": 15,
  "status": "live",
  "request_id": "..."
}

==================================================
API VIGILAY
==================================================

Implementar:

POST /api/cameras/{camera_id}/live/start

Debe:

1. autenticar usuario;
2. comprobar autorización sobre cliente/cámara;
3. verificar que cámara esté online;
4. obtener/crear Cloudflare Live Input;
5. crear camera_stream_session;
6. mandar orden al agente;
7. esperar confirmación razonable;
8. responder solamente información segura.

Respuesta:

{
    "cameraId": 15,
    "status": "live",
    "playbackUrl": "WHEP_URL",
    "sessionId": "..."
}

NUNCA devolver publishUrl.

Implementar:

POST /api/cameras/{camera_id}/live/stop

Implementar:

GET /api/cameras/{camera_id}/live/status

Implementar heartbeat del visor, por ejemplo:

POST /api/cameras/{camera_id}/live/heartbeat

==================================================
CONTROL DE CONSUMO
==================================================

No quiero transmitir todas las cámaras 24/7 hacia Cloudflare.

El stream debe ser ON DEMAND.

Flujo:

primer espectador
    ↓
arrancar FFmpeg

más espectadores
    ↓
reutilizar stream existente

último espectador se va
    ↓
esperar período de gracia

sin espectadores
    ↓
detener FFmpeg

Agregar configuración:

STREAM_IDLE_TIMEOUT_SECONDS=60

No crear un proceso FFmpeg por espectador.

Debe existir:

1 cámara
=
máximo 1 proceso de publicación WHIP activo

independientemente del número de espectadores.

==================================================
FRONTEND
==================================================

Crear/reutilizar el componente de cámara en vivo.

Al pulsar:

Ver en vivo

llamar:

POST /api/cameras/{id}/live/start

El frontend recibe playbackUrl.

Implementar reproducción WHEP/WebRTC.

No usar RTSP en navegador.

No consumir directamente direcciones:

192.168.x.x

El navegador solamente debe conocer el endpoint WHEP autorizado.

Estados visuales:

Conectando...
En vivo
Reconectando...
Cámara sin conexión
Error

Al cerrar modal/página:

enviar stop o reducir referencia de espectador.

Implementar heartbeat mientras el visor esté abierto.

==================================================
SEGURIDAD
==================================================

Requisitos obligatorios:

- Cloudflare API token solo backend.
- WHIP cifrado en BD.
- WHIP nunca frontend.
- WHIP nunca logs.
- Credenciales RTSP nunca frontend.
- Credenciales RTSP nunca logs.
- CREDENTIAL_ENCRYPTION_KEY no se modifica.
- No guardar secretos en Git.
- No abrir puertos de cámaras al Internet.
- No exponer Frigate 5000.
- Validar ownership de camera_id.
- No permitir IDOR entre clientes.
- Toda comunicación cloud/agent mediante TLS.
- Aplicar rate limiting a start/stop.
- Sanitizar excepciones.

==================================================
ARRANQUE Y RECUPERACIÓN
==================================================

Cuando Vigilay Agent arranque:

- detectar procesos huérfanos propios si aplica;
- marcar sesiones antiguas como stopped/error;
- NO iniciar automáticamente todos los streams;
- iniciar solo cuando un usuario solicite live.

Si FFmpeg muere mientras existen espectadores:

reintentar con backoff limitado:

2 s
5 s
10 s

y luego marcar error.

No crear bucles infinitos.

==================================================
PRUEBAS
==================================================

Crear pruebas para:

- creación de Live Input;
- reutilización de Live Input;
- cifrado de WHIP;
- nunca retornar WHIP al frontend;
- autorización entre clientes;
- start stream;
- stop stream;
- start doble de la misma cámara;
- error de cámara;
- error Cloudflare;
- FFmpeg inexistente;
- FFmpeg termina inesperadamente;
- timeout;
- heartbeat;
- cierre por inactividad;
- sanitización de logs.

Mockear Cloudflare en tests.
No consumir la API real durante pruebas unitarias.

==================================================
ENTREGABLE
==================================================

Antes de programar:

1. analiza el repositorio;
2. identifica archivos que vas a modificar;
3. explícame la arquitectura actual encontrada;
4. dime qué vas a reutilizar;
5. muestra el plan de implementación.

Después implementa.

Al finalizar entrégame:

- archivos modificados;
- archivos nuevos;
- migración SQL;
- nuevas variables .env;
- endpoints;
- ejemplo request/response;
- cómo iniciar el agente;
- cómo probar una cámara;
- cómo comprobar que FFmpeg fue detenido;
- riesgos o pendientes.

NO me hagas ejecutar manualmente Cloudflare ni copiar WHIP.

La creación del Live Input debe ser automática mediante Cloudflare API.

La experiencia final debe ser:

registrar cámara
→ pulsar "Ver en vivo"
→ Vigilay inicia el streaming
→ aparece el video.

No realizar sobreingeniería.
Respeta la arquitectura actual de Vigilay.
