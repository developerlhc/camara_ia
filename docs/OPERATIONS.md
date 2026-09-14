# Vigilay — operación local

Iniciar: `docker compose up -d --build`. Ver estado: `docker compose ps`. Logs: `docker compose logs --tail 100 api worker web`. Detener sin borrar datos: `docker compose stop`. Reiniciar servicios: `docker compose restart api worker web`.

En esta instalación es preferible `.\scripts\iniciar-vigilay.ps1`: además de Compose, conecta el contenedor externo `frigate` a la red privada `vigilay_default` con el alias `frigate` e inicia un único agente dedicado de video en vivo.

MySQL usa un volumen persistente. No ejecutar `docker compose down -v` para una parada normal, porque elimina ese volumen. Las migraciones corren en un contenedor de ejecución única; la API espera su éxito antes de iniciar.

El worker del simulador ejecuta `vigilay-worker`, procesa la cola y publica su heartbeat en MySQL. La web consulta resultados de cámaras cada tres segundos. Si el worker está detenido, los comandos quedan pendientes en la base. La cola solo admite un comando pendiente por cámara.

## Agente local de streaming

Ejecutar `.\scripts\iniciar-agente-stream.ps1` en el equipo Windows conectado a la LAN de cámaras. Debe permanecer como proceso supervisado; al recibir SIGINT/SIGTERM detiene todos los FFmpeg propios. El estado aparece como `media=ok` mientras renueva su heartbeat.

En producción `DATABASE_URL` debe configurar `ssl_ca` o `ssl_verify_cert=true`. El agente realiza únicamente conexiones salientes. No se debe publicar Flask 5000, MySQL, RTSP ni V380Decoder hacia Internet.

`START_STREAM_AGENT_WITH_LOCAL=false` evita que `iniciar.ps1` cree otro agente cuando ya se usa `scripts/iniciar-agente-stream.ps1` o el iniciador completo. Cloudflare sólo transporta el vivo; no es el almacén de grabaciones.

Cuando la cámara tiene `frigate_camera_name`, el agente prueba primero
`FRIGATE_RESTREAM_URL/<alias>` (go2rtc). De esta forma Frigate, sus grabaciones/IA y el vivo
remoto comparten una sola conexión con la cámara. Si el alias todavía no existe en go2rtc,
el agente vuelve automáticamente a la conexión RTSP registrada en Vigilay.

Los Live Inputs de Cloudflare son recursos de transporte reutilizables, uno por cámara. No
representan cámaras adicionales ni almacenan grabaciones en esta arquitectura: se crean con
`recording.mode=off` y se publican únicamente mientras existe una sesión de visualización.

El agente publica la primera pista de audio del RTSP junto con el video y la convierte a Opus para WebRTC. El reproductor inicia silenciado para cumplir las reglas de reproducción automática del navegador; el usuario debe pulsar **Activar sonido**. Una cámara con micrófono permite escuchar. Enviar voz exige además un altavoz y un canal de retorno específico del fabricante/ONVIF; no se ofrece como control funcional mientras esa capacidad no haya sido detectada e implementada por el adaptador.

## Identidad de Vigilay Local

El botón **Configurar empresa y sede** permite seleccionar registros existentes, crear una empresa/sede o modificar sus datos. La aplicación rechaza empresas suspendidas, sedes inexistentes y cualquier sede que pertenezca a otra empresa. La selección queda en `.local/vigilay-local.json` y todas las consultas y altas de cámara del visor se limitan a ese par empresa-sede.

La interfaz está disponible en `http://localhost:5000` después de ejecutar `.\iniciar.ps1`. El formulario de cámara consulta los aliases Frigate a través de `VIGILAY_API_URL` y permite asignarlos sin exponer la clave interna en JavaScript.

Si se cambia la identidad con Vigilay Local abierto, reiniciar `iniciar.ps1` para vaciar las conexiones anteriores y cargar únicamente las cámaras de la nueva sede.

## Frigate

Frigate es la fuente de detecciones, eventos y grabaciones. El contenedor local `frigate-gateway` accede al puerto interno 5000 por la red Docker y abre una conexión saliente autenticada; el navegador nunca recibe la dirección de Frigate, el endpoint del túnel ni su credencial. Cada conexión se registra contra una empresa y sede validadas.

Sin dominio propio, `docker compose up -d frigate-gateway` crea automáticamente un Quick Tunnel aleatorio `*.trycloudflare.com`. El endpoint cambia si reinicia el túnel y el gateway actualiza MySQL sin intervención. Al vincular una sede, Vigilay Local genera una credencial aleatoria exclusiva, la guarda cifrada y la reutiliza en sus reconexiones. Una sede no comparte la credencial de otra y puede renovarse de forma independiente.

`INTERNAL_PROXY_SECRET` pertenece únicamente al despliegue central: autentica el proxy interno entre `vigilay-web` y `api` dentro del mismo pod. No se configura ni se transmite a los equipos de clientes. Quick Tunnel es válido para la prueba actual; para producción con SLA se debe migrar a un túnel administrado y dominio propio.

Comprobación:

```powershell
docker compose ps frigate-gateway
docker compose logs --tail 50 frigate-gateway
```

Debe aparecer `Frigate gateway connected for site ...`. No se debe publicar el puerto 5000 de Frigate.

Agregar una conexión en Vigilay no modifica automáticamente el archivo externo de Frigate. Primero se incorpora la fuente en la configuración validada de Frigate y luego se selecciona su alias en Vigilay. Esto evita sobrescribir una configuración externa o guardar nuevamente secretos RTSP en texto plano.

El simulador conserva su estado de dispositivo en MySQL. Modificaciones directas de ese estado se detectan al volver a probar la cámara y producen DRIFTED cuando difieren del valor deseado.

## Copias de seguridad

Respaldar MySQL con un usuario de backup, `mysqldump --single-transaction --routines --triggers`, y verificar restauración en un esquema o servidor separado. Automatizar copias cifradas fuera de la máquina principal, con retención y alertas. No colocar contraseñas en argumentos de proceso ni en archivos versionados; usar un archivo de opciones privado o gestor de secretos.

Respaldar la clave AES por separado y con acceso restringido: perderla impide recuperar credenciales cifradas. Respaldar también el volumen o directorio `/media/frigate` y la configuración/base de Frigate. Los CSV, fotos y rostros heredados sólo se usan si se habilita explícitamente la IA local.

## Alcance del despliegue

El entorno actual es local. El workflow prepara imágenes API y web en GHCR con tags SHA después de checks; el worker usa la imagen API con comando `vigilay-worker`. No se ha publicado un repositorio, imagen ni servicio remoto desde esta instalación.

El despliegue de las imágenes en Bunny Magic Containers está descrito en `docs/MAGIC_CONTAINERS.md`. El workflow publica versiones en GHCR, pero la selección de versión y el rollout se ejecutan manualmente en Bunny.
