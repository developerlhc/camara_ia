# Vigilay — verificación de la primera entrega

Fecha: 2026-09-14. Entorno: Windows, Python 3.13.5, Node 20.19.3 para herramientas locales; contenedores Python 3.13, Node 22 y MySQL 8.4. Prueba de navegador ejecutada con Microsoft Edge mediante Playwright.

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
| Persistencia | Reiniciados MySQL, API, worker y web. Se conservaron los mismos IDs de clientes, usuarios y cámaras. Cola, rate limits, heartbeats y estado del simulador persisten en MySQL. |
| Prototipo | Compilación sintáctica de camara-ia.py verificada; no se abrió la cámara ni se enviaron notificaciones reales. |
| Exclusiones | git check-ignore confirmó exclusión de .env, accesos locales, configuración privada, entorno Python y CSV. |

Las dos pruebas E2E tardaron 17,1 segundos en la ejecución correcta. El primer intento había fallado al localizar un select por texto de etiqueta; se ajustó a su rol accesible combobox y se repitió el flujo completo.

Capturas locales generadas: `apps/web/test-results/dashboard.png`, `camera-settings.png` y `mobile-dashboard.png` (excluidas de Git). El esquema de pruebas contiene datos sintéticos. El entorno de desarrollo quedó con dos clientes de demostración, una sede, una cámara simulada y un usuario administrador de cliente, además del superadministrador local; uno de los clientes corresponde al primer intento E2E.

## Estado posterior de la integración

Al 14 de septiembre de 2026, el entorno real quedó limitado a Cenfelec, una sede y tres cámaras. Frigate recibe `calle` (V380), `cuarto` (EZVIZ) e `imou`; se verificó imagen y procesamiento de Imou. Frigate es la fuente exclusiva de IA, eventos y grabaciones. Cloudflare se usa sólo para transportar el vivo, mediante sesiones autorizadas creadas por Vigilay.

Vigilay Local administra y valida la identidad empresa/sede, las conexiones LAN y la asignación única de alias Frigate. La web permite asignar varios usuarios a una cámara, controlar PTZ cuando el dispositivo lo soporta, filtrar grabaciones por empresa/sede/cámara, paginarlas y reproducir consecutivamente sus fragmentos.

La publicación remota sigue dependiendo de infraestructura externa: GitHub Actions construye y publica `vigilay-web` en GHCR y puede actualizar Bunny Magic Containers cuando se configuran `BUNNYNET_APP_ID` y `BUNNYNET_API_KEY`. No se afirma un despliegue remoto mientras esas credenciales y un `push` a `main` no existan.

Quedan dos advertencias de deprecación provenientes del cliente de pruebas Starlette/httpx/AnyIO; no causan fallos de las pruebas. La dependencia tzdata se incorporó para que la validación America/Lima también funcione en Windows.

## Corrección EZVIZ (`cuarto`) — 14 de septiembre de 2026

Se investigaron los logs del contenedor `frigate` (0.18.0-77a66e7) y se encontró que `cuarto` era la única cámara con el rol `audio` en `F:\ia\frigate\config\config.yaml` (activa detección de eventos por sonido). Ese rol hacía que su proceso ffmpeg se reiniciara en bucle: 1115 reinicios registrados entre las 02:26 y las 11:40 (hora local), aproximadamente uno cada 30 segundos, por timestamps de audio corruptos (`Queue input is backward in time`, `Non-monotonic DTS`, terminando en `Failed reading RTSP data: End of file`). `calle` e `imou` no presentaron ningún reinicio en el mismo periodo; el problema no estaba en Vigilay.

Se quitó el rol `audio` de `cuarto` (queda `[detect, record]`, igual que `calle`/`imou`) y se reinició el contenedor `frigate`. En los minutos posteriores no se registró ningún reinicio de ffmpeg para `cuarto`, y `calle`/`imou` no se vieron afectados. Detalle completo, comando exacto y respaldo del archivo original en `docs/EZVIZ_FRIGATE.md`.

Esto no se equipara todavía a "imagen y procesamiento verificados" al nivel de Imou: falta observar estabilidad por más tiempo y confirmar eventos/grabaciones reales de `cuarto` desde Vigilay Web antes de igualar esa afirmación.
