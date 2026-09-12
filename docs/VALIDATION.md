# Vigilay — verificación de la primera entrega

Fecha: 2026-09-11. Entorno: Windows, Python 3.13.5, Node 20.19.3 para herramientas locales; contenedores Python 3.13, Node 22, MySQL 8.4 y Redis 7.4. Prueba de navegador ejecutada con Microsoft Edge mediante Playwright.

## Resultados observados

| Comprobación | Resultado |
| --- | --- |
| Migraciones 0001, 0002 y 0003 | Aplicadas en MySQL de desarrollo y esquema separado vigilay_test. |
| `alembic check` | Sin diferencias pendientes entre modelos y base. |
| Backend | 23 casos verificados. La ejecución integral confirmó 22; el caso adicional de CHECK SQL rechazó correctamente el rol inválido, pero esperaba IntegrityError. Se corrigió para comprobar OperationalError/MySQL 3819 y pasó al reejecutarlo. |
| Aislamiento | Consultas y escrituras cruzadas, sedes, usuarios, auditoría, cámaras, capacidades, ajustes y comandos bloqueados. |
| Permisos | Operadores y observadores requieren asignación; sin permiso de configuración se rechaza el comando. |
| Autenticación | Login/logout, sesión hasheada, rotación, revocación, CSRF, Origin, rate limit, bloqueo y recuperación de un solo uso verificados. |
| Cifrado | Credenciales no serializadas y AES-GCM ligado a tenant/cámara; manipulación rechazada. |
| Simulador | Probe, capacidad detectada, escritura, lectura posterior, sincronización, drift y fallo offline verificados. |
| Frontend | `svelte-check`: cero errores y cero advertencias. Build de producción completado dentro de Docker. |
| Navegador | 2 E2E aprobados: flujo de administración/configuración y rechazo de acceso anónimo. |
| Responsive | Comprobado a 1440 px y 390 px; sin desbordamiento horizontal del documento. |
| Dependencias | npm audit y pip-audit sin vulnerabilidades conocidas en sus ejecuciones finales; pip check sin incompatibilidades. |
| Contenedores | API, web y worker construidos; cinco servicios principales reportan healthy. |
| Persistencia | Reiniciados MySQL, Redis, API, worker y web. Se conservaron los mismos IDs de clientes, usuarios y cámaras, y sensibilidad deseada/reportada 70 con estado SYNCED. |
| Prototipo | Compilación sintáctica de camara-ia.py verificada; no se abrió la cámara ni se enviaron notificaciones reales. |
| Exclusiones | git check-ignore confirmó exclusión de .env, accesos locales, configuración privada, entorno Python y CSV. |

Las dos pruebas E2E tardaron 17,1 segundos en la ejecución correcta. El primer intento había fallado al localizar un select por texto de etiqueta; se ajustó a su rol accesible combobox y se repitió el flujo completo.

Capturas locales generadas: `apps/web/test-results/dashboard.png`, `camera-settings.png` y `mobile-dashboard.png` (excluidas de Git). El esquema de pruebas contiene datos sintéticos. El entorno de desarrollo quedó con dos clientes de demostración, una sede, una cámara simulada y un usuario administrador de cliente, además del superadministrador local; uno de los clientes corresponde al primer intento E2E.

## Pendiente de verificación e implementación

Esta entrega inicia el producto y no cumple todavía la definición de MVP completo del Master Prompt. No se verificaron cámaras físicas, ONVIF, RTSP operativo, PTZ, video WebRTC/HLS, Edge Agent, YOLO dentro de la nueva plataforma, eventos, medios, reconocimiento facial multiempresa, notificaciones, Imou, EZVIZ, V380 ni Bunny. El código antiguo conserva la IA y la cámara para su extracción posterior.

El gateway MediaMTX está configurado en un perfil privado opcional; su imagen se comprobó disponible, pero no se inició ni se verificó una sesión de medios. GitHub Actions y GHCR quedaron preparados en archivos; no se ejecutaron en GitHub ni se publicaron imágenes. Se inicializó Git local sin commits ni remotos.

Quedan dos advertencias de deprecación provenientes del cliente de pruebas Starlette/httpx/AnyIO; no causan fallos de las pruebas. La dependencia tzdata se incorporó para que la validación America/Lima también funcione en Windows.
