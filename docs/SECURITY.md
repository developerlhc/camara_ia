# Vigilay — controles y límites de esta entrega

Controles implementados: filtros por tenant en ORM, rechazo de escrituras cruzadas, referencias MySQL compuestas, RBAC, permisos por cámara, contraseñas Argon2id, sesiones revocables, CSRF/Origin, rate limits persistentes en MySQL, bloqueo temporal, auditoría y cifrado AES-256-GCM. Cada credencial queda ligada criptográficamente al tenant y la cámara mediante AAD. Las respuestas de validación no incluyen valores de entrada para evitar filtrar contraseñas o URLs RTSP.

El esquema API solo acepta campos declarados. Las operaciones de cámara no abren URLs arbitrarias desde el control plane. RTSP únicamente registra parámetros cifrados; conexiones reales pasarán por un agente autorizado. La interfaz usa interpolación escapada de Svelte, no HTML construido con nombres de usuarios.

Las claves se configuran en variables de entorno y `.env` local excluido de Git/Docker. Se trasladaron los valores sensibles del prototipo a `.local/legacy-config.json`, conservando su funcionamiento local. `.local`, logs, reportes, fotos y modelos no forman parte de los contextos Docker ni del versionado previsto. El contenedor API/worker y el contenedor web ejecutan como usuarios no root.

El análisis de dependencias detectó una versión antigua de cookie y una versión de cryptography con avisos; se ajustaron a cookie 0.7.2 y cryptography 50.0.1 y se repitió el análisis. Referencia de cambios: [changelog oficial de cryptography](https://cryptography.io/en/latest/changelog/).

Esta base no equivale a una certificación de seguridad de todo el producto. Todavía faltan autorización de medios, protección de subidas de imágenes, rotación/versionado de claves, MFA, gestión remota de agentes, pruebas de carga y hardening del despliegue público. No hay endpoints de upload, medios, webhooks ni fabricantes en esta entrega; sus pruebas de seguridad acompañarán su implementación.

Compose publica puertos únicamente en 127.0.0.1 para desarrollo. El gateway de medios se mantiene en red interna y se activa mediante un perfil opcional; no debe exponerse antes de incorporar autorización de sesiones.
