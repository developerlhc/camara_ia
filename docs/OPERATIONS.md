# Vigilay — operación local

Iniciar: `docker compose up -d --build`. Ver estado: `docker compose ps`. Logs: `docker compose logs --tail 100 api worker web`. Detener sin borrar datos: `docker compose stop`. Reiniciar servicios: `docker compose restart api worker web`.

En esta instalación es preferible `.\scripts\iniciar-vigilay.ps1`: además de Compose, conecta el contenedor externo `frigate` a la red privada `vigilay_default` con el alias `frigate` e inicia un único agente dedicado de video en vivo.

MySQL usa un volumen persistente. No ejecutar `docker compose down -v` para una parada normal, porque elimina ese volumen. Las migraciones corren en un contenedor de ejecución única; la API espera su éxito antes de iniciar.

El worker del simulador ejecuta `vigilay-worker`, procesa la cola y publica su heartbeat en MySQL. La web consulta resultados de cámaras cada tres segundos. Si el worker está detenido, los comandos quedan pendientes en la base. La cola solo admite un comando pendiente por cámara.

## Agente local de streaming

Ejecutar `.\scripts\iniciar-agente-stream.ps1` en el equipo Windows conectado a la LAN de cámaras. Debe permanecer como proceso supervisado; al recibir SIGINT/SIGTERM detiene todos los FFmpeg propios. El estado aparece como `media=ok` mientras renueva su heartbeat.

En producción `DATABASE_URL` debe configurar `ssl_ca` o `ssl_verify_cert=true`. El agente realiza únicamente conexiones salientes. No se debe publicar Flask 5000, MySQL, RTSP ni V380Decoder hacia Internet.

`START_STREAM_AGENT_WITH_LOCAL=false` evita que `iniciar.ps1` cree otro agente cuando ya se usa `scripts/iniciar-agente-stream.ps1` o el iniciador completo. Cloudflare sólo transporta el vivo; no es el almacén de grabaciones.

## Identidad de Vigilay Local

El botón **Configurar empresa y sede** permite seleccionar registros existentes, crear una empresa/sede o modificar sus datos. La aplicación rechaza empresas suspendidas, sedes inexistentes y cualquier sede que pertenezca a otra empresa. La selección queda en `.local/vigilay-local.json` y todas las consultas y altas de cámara del visor se limitan a ese par empresa-sede.

La interfaz está disponible en `http://localhost:5000` después de ejecutar `.\iniciar.ps1`. El formulario de cámara consulta los aliases Frigate a través de `VIGILAY_API_URL` y permite asignarlos sin exponer la clave interna en JavaScript.

Si se cambia la identidad con Vigilay Local abierto, reiniciar `iniciar.ps1` para vaciar las conexiones anteriores y cargar únicamente las cámaras de la nueva sede.

## Frigate

Frigate es la fuente de detecciones, eventos y grabaciones. El API de Vigilay accede al puerto interno 5000 por la red Docker y actúa como proxy con permisos por empresa/cámara; el navegador nunca recibe esa dirección interna. El alias Frigate se asigna al crear la cámara o desde su detalle y debe existir realmente en Frigate.

Agregar una conexión en Vigilay no modifica automáticamente el archivo externo de Frigate. Primero se incorpora la fuente en la configuración validada de Frigate y luego se selecciona su alias en Vigilay. Esto evita sobrescribir una configuración externa o guardar nuevamente secretos RTSP en texto plano.

El simulador conserva su estado de dispositivo en MySQL. Modificaciones directas de ese estado se detectan al volver a probar la cámara y producen DRIFTED cuando difieren del valor deseado.

## Copias de seguridad

Respaldar MySQL con un usuario de backup, `mysqldump --single-transaction --routines --triggers`, y verificar restauración en un esquema o servidor separado. Automatizar copias cifradas fuera de la máquina principal, con retención y alertas. No colocar contraseñas en argumentos de proceso ni en archivos versionados; usar un archivo de opciones privado o gestor de secretos.

Respaldar la clave AES por separado y con acceso restringido: perderla impide recuperar credenciales cifradas. Respaldar también el volumen o directorio `/media/frigate` y la configuración/base de Frigate. Los CSV, fotos y rostros heredados sólo se usan si se habilita explícitamente la IA local.

## Alcance del despliegue

El entorno actual es local. El workflow prepara imágenes API y web en GHCR con tags SHA después de checks; el worker usa la imagen API con comando `vigilay-worker`. No se ha publicado un repositorio, imagen ni servicio remoto desde esta instalación.

El despliegue de la imagen web en Bunny Magic Containers está descrito en `docs/MAGIC_CONTAINERS.md`. El workflow lo ejecuta al configurar las credenciales del repositorio; no se ha conectado una cuenta Bunny desde esta instalación local.
