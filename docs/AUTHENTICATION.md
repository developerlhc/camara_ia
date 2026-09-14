# Vigilay — autenticación

Login por correo o usuario, contraseñas Argon2id y sesión aleatoria de 48 bytes. Solo el hash SHA-256 del token se guarda en MySQL. Cookie HttpOnly, SameSite=Lax, vencimiento de ocho horas por defecto. Secure es obligatorio al seleccionar APP_ENV=production y WEB_ORIGIN debe ser HTTPS. Los tokens no se guardan en localStorage.

El navegador envía Origin y un token CSRF derivado con HMAC de la sesión; las escrituras verifican ambos. Login y recuperación verifican Origin y límites persistentes en MySQL. Rotar sesión al autenticar revoca el token previo. Logout, cambio/reset de contraseña y cambios de usuario revocan sesiones. Cada petición verifica estado del usuario, tenant y rol vigente; suspender un cliente corta el acceso inmediatamente.

Límite compartido MySQL: 30 solicitudes de login por IP en 15 minutos; después de cinco intentos fallidos se bloquea la cuenta durante 15 minutos. El proxy SvelteKit pasa la IP del navegador solo con un secreto interno; la API ignora headers de IP sin esa autenticación. La sesión existente también se verifica en MySQL.

Crear administrador:

```powershell
docker compose exec api vigilay create-superadmin --email admin@example.com --username admin
```

Para automatización local se admite `--password-env NOMBRE_VARIABLE`; nunca pasar la contraseña como argumento literal. La CLI requiere acceso al entorno y la base de datos y no se expone por HTTP.

Recuperación inicial: un administrador del entorno emite `vigilay issue-password-reset --email usuario@example.com`. El token dura 15 minutos, se almacena hasheado y se consume una sola vez desde `/reset-password`. Emitir uno nuevo invalida los anteriores. La distribución automática por correo y MFA no están implementados en esta entrega.

Roles fijos: SUPER_ADMIN global, CLIENT_ADMIN de un tenant, OPERATOR con consulta/configuración de cámaras asignadas y VIEWER con consulta de cámaras asignadas. No se acepta SUPER_ADMIN en los endpoints de creación/edición de usuarios.
