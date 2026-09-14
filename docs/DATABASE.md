# Vigilay — datos y migraciones

MySQL 8.4, InnoDB, UTF8MB4. La API almacena fechas UTC y las serializa con sufijo Z; la interfaz muestra America/Lima. Identificadores UUID representados como VARCHAR(36). Un cliente puede tener varias sedes, usuarios y cámaras.

Migraciones:

- `0001`: identidad, administración, auditoría y dominio inicial de cámaras.
- `0002`: cuatro roles, catálogo de permisos y asignaciones iniciales.
- `0003`: referencias compuestas entre usuario/cámara y tenant, más CHECK del ámbito de roles.

Tablas actuales: tenants, sites, users, roles, permissions, role_permissions, user_roles, sessions, password_reset_tokens, login_attempts, rate_limit_buckets, service_heartbeats, simulator_states, audit_logs, cameras, camera_credentials, user_camera_permissions, camera_capabilities, camera_settings, device_commands, notification_channels, camera_stream_providers, camera_stream_sessions y global_integration_settings. Alembic mantiene su tabla de versión. Los eventos y medios permanecen en Frigate y se consultan mediante su API; no se duplican en MySQL.

Cada User tiene inicialmente un único rol. El ámbito de la asignación debe coincidir con su tenant; solo SUPER_ADMIN puede tener tenant nulo. OPERATOR y VIEWER requieren permisos específicos de cámara. Los administradores del cliente acceden a sus cámaras. TenantScoped aplica filtros automáticos y verifica escrituras. SQL directo y cambios masivos se rechazan en sesiones de clientes.

Los valores deseados y reportados son JSON porque cada ajuste puede tener tipos distintos. Las relaciones entre recursos son claves foráneas, no documentos JSON. La URL RTSP se cifra como credencial; no existe un endpoint público para descifrarla.

La cola inicial usa filas MySQL, bloqueo de cámara al encolar y `FOR UPDATE SKIP LOCKED` en el worker. Una transacción procesa un comando de simulador; la operación es idempotente. Si el worker muere antes del commit, MySQL revierte y permite reintentar. Para comandos de hardware de larga duración se implementarán leases, timeouts, identidad del agente y estados intermedios en la fase 3.

`alembic upgrade head` aplica cambios; `alembic check` comprueba diferencias entre modelos y migraciones. No usar `create_all()` en el arranque de producción. La revisión RBAC no tiene downgrade destructivo: los cambios de política se realizan con una migración explícita.
