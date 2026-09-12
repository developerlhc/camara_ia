# Vigilay — plan de implementación

El Master Prompt es la especificación de producto. Esta primera entrega desarrolla la fase 1 y una porción verificable del dominio de cámaras; no representa la aceptación del MVP completo.

Estado de la primera entrega: fase 0 documentada y base de fase 1 ejecutada en Docker/MySQL, con interfaz conectada y pruebas. Fase 2 iniciada con registro RTSP cifrado, permisos, capacidades y simulador. La cola local y verificación de ajustes adelantan una parte de fase 3, pero todavía no hay un Edge Agent. Evidencia y límites en [VALIDATION.md](VALIDATION.md).

| Fase | Entregable / criterio |
| --- | --- |
| 0 | Inspección y arquitectura documentadas. |
| 1 | MySQL, migraciones, login/logout, sesiones, CSRF, roles, clientes, sedes, usuarios, auditoría y panel conectado. Pruebas contra MySQL. |
| 2 | Cámaras, credenciales cifradas, permisos, capacidades y simulador; después ONVIF y RTSP reales. |
| 3 | Tokens de provisión, identidad de agentes, heartbeat, cola persistente y comandos con verificación desired/reported. |
| 4 | WebRTC/HLS autorizado, gateway, on-demand y pruebas de aislamiento de medios. |
| 5 | Extraer YOLO del prototipo, pipeline por cámara, eventos y snapshots aislados. |
| 6 | Reglas, in-app, email y webhooks firmados con reintentos. |
| 7 | Personas conocidas, muestras, embeddings, retención, auditoría e importación opcional. |
| 8–10 | Documentación oficial Imou/EZVIZ, validación real de dispositivos y compatibilidad V380. |
| 11 | Reportes MySQL, almacenamiento abstraído y Bunny Storage. |
| 12 | Imágenes GHCR y despliegue Bunny tras verificar red/persistencia y credenciales. |
| 13 | Hardening, carga, fallos, pruebas cruzadas y aceptación completa del flujo MVP. |

No se eliminan CSV ni fotos existentes. Las pruebas automatizadas utilizan datos sintéticos y el adaptador SIMULATOR; ninguna marca se etiqueta VERIFIED sin evidencia. El estado y las comprobaciones efectivamente ejecutadas se registrarán en `docs/VALIDATION.md`.
