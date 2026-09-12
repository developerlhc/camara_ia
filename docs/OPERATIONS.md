# Vigilay — operación local

Iniciar: `docker compose up -d --build`. Ver estado: `docker compose ps`. Logs: `docker compose logs --tail 100 api worker web`. Detener sin borrar datos: `docker compose stop`. Reiniciar servicios: `docker compose restart api worker web`.

MySQL y Redis usan volúmenes persistentes. No ejecutar `docker compose down -v` para una parada normal, porque elimina esos volúmenes. Las migraciones corren en un contenedor de ejecución única; la API espera su éxito antes de iniciar.

El worker del simulador ejecuta `vigilay-worker`, procesa la cola MySQL y publica heartbeat en Redis. La web consulta resultados de cámaras cada tres segundos. Si el worker está detenido, los comandos quedan pendientes en la base. La cola solo admite un comando pendiente por cámara.

El simulador conserva su estado de dispositivo en Redis con persistencia AOF. Modificaciones directas de ese estado se detectan al volver a probar la cámara y producen DRIFTED cuando difieren del valor deseado.

## Copias de seguridad

Respaldar MySQL con un usuario de backup, `mysqldump --single-transaction --routines --triggers`, y verificar restauración en un esquema o servidor separado. Automatizar copias cifradas fuera de la máquina principal, con retención y alertas. No colocar contraseñas en argumentos de proceso ni en archivos versionados; usar un archivo de opciones privado o gestor de secretos.

Respaldar la clave AES por separado y con acceso restringido: perderla impide recuperar credenciales cifradas. Respaldar medios y metadatos cuando se incorpore almacenamiento. Los CSV/fotos/rostros del prototipo siguen en sus directorios originales y requieren su propia copia hasta la importación.

## Alcance del despliegue

El entorno actual es local. El workflow prepara imágenes API y web en GHCR con tags SHA después de checks; el worker usa la imagen API con comando `vigilay-worker`. No se ha publicado un repositorio, imagen ni servicio remoto desde esta instalación.

Bunny Magic Containers, MySQL gestionado, balanceo de medios y Terraform se abordarán tras verificar capacidades reales del proveedor. No se ha implementado un supuesto endpoint de despliegue ni conectado cuentas externas.
