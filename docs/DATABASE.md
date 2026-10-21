# Modelo de datos

MySQL conserva identidad, permisos, cámaras, credenciales cifradas, sesiones,
auditoría, comandos y coordinación del vivo. Los archivos MP4 y sus metadatos
JSON permanecen en la carpeta configurada en cada sede.

Entidades principales:

- `tenants`, `sites`, `users`, roles y permisos;
- `cameras`, `camera_credentials`, capacidades y configuración;
- `camera_stream_sessions` y proveedores del vivo;
- conexiones autenticadas de Vigilay Recorder por sede;
- auditoría, sesiones, intentos de acceso y heartbeats de servicios.

Por compatibilidad con instalaciones existentes, la tabla física de conexiones
y una columna histórica de cámara conservan sus nombres originales de migración.
El código activo las expone como `RecorderConnection` y no usa alias externos ni
ninguna API de terceros. Renombrarlas en MySQL exige una migración posterior y no
aporta una mejora funcional, por eso esta entrega evita una operación destructiva.

Los eventos se derivan de los JSON contiguos a cada clip. La API consulta el
catálogo autenticado de la sede, aplica empresa/sede/permisos de cámara y transmite
el MP4 con soporte `Range`; no duplica video en MySQL.
