# Vigilay Mobile y Vigilay Desktop

Son dos aplicaciones diferentes: Mobile sirve al usuario del negocio; Desktop
sirve al técnico que instala una sede. No se distribuyen claves MySQL dentro del
APK ni se publica Frigate directamente en Internet.

## Vigilay Mobile — Android primero

Proyecto Capacitor 8 en `apps/mobile`, aplicación `com.vigilay.mobile`.
La interfaz empaquetada permite configurar **sólo el origen HTTPS** de Vigilay y
abrir cámaras, grabaciones, eventos y administración. Funciona con el dominio
gratuito `bunny.run`; no exige comprar un dominio.

Reutiliza la web publicada con `@capacitor/inappbrowser`: por defecto, una pestaña
segura del navegador del sistema; opcionalmente, una vista nativa aislada dentro
de la app. No da acceso al puente Capacitor al sitio remoto.
No usa `server.url` de desarrollo para cargar código remoto con permisos nativos.
Login, cookies, permisos multiempresa, PTZ, filtros, WebRTC y grabaciones siguen
en la web: no hay una segunda implementación de negocio que se desactualice.
Sólo se guarda el origen elegido, nunca contraseñas en localStorage.

El modo navegador del sistema evita limitaciones del WebView con WebRTC,
micrófono y descargas. **Hay que probar estas funciones en un teléfono real**;
compilar un APK no demuestra compatibilidad de audio bidireccional con una cámara.
La aplicación conserva las limitaciones funcionales de la web actual; no añade
notificaciones push, funcionamiento sin Internet ni funcionalidades nuevas del
hardware. iPhone queda para la siguiente fase (requiere macOS/Xcode y firma).

```powershell
cd apps/mobile
npm ci
npm test
npm run native:android
npx cap open android
```

Requisitos de compilación: Node 22, JDK 21, SDK Android 36. Android mínimo 8
(API 26). Opcional: `VITE_VIGILAY_ORIGIN=https://TU-VIGILAY.bunny.run` al compilar;
si se omite, el usuario configura la dirección. No incluyas secretos en `VITE_*`.
Para distribución pública falta una clave de firma release bajo tu control;
el workflow entrega un APK **debug**, no una publicación en Google Play.

## Vigilay Desktop — Windows / Tauri 2

Proyecto en `apps/desktop`. Rust administra comandos Docker asíncronos y limitados;
WebView2 muestra el asistente. No incluye Chromium ni reimplementa FFmpeg/go2rtc.
Python se ejecuta **dentro de la imagen Local existente**, únicamente para acceder
a las funciones probadas de identidad, MySQL y cifrado. No exige instalar Python
en la PC del técnico. Frigate sigue haciendo grabación e IA.

Requiere Docker Desktop con WSL2 y contenedores Linux. El asistente comprueba el
motor y enlaza las instrucciones oficiales; no acepta licencias ni instala WSL
silenciosamente. Para compilar: Rust 1.94, MSVC Build Tools, WebView2 y Node 22.

```powershell
cd apps/desktop
npm ci
npm run desktop:dev
# Instalador Windows NSIS (no firmado):
npm run desktop:build
```

### Flujo del técnico

1. Comprobar Docker y preparar usando **BDMYSQL existente**, la clave de cifrado
   original y el origen HTTPS de Vigilay Web. No se crea ni sustituye la base.
2. Iniciar Local y actualizar el catálogo. Seleccionar empresa y sede o escribir
   sus nombres para crearlas/modificarlas. La sede debe pertenecer a la empresa;
   los nombres existentes se reutilizan. Se valida el ámbito antes de operar.
3. Registrar o editar cámaras RTSP. Se admite un substream opcional para detección
   de menor resolución; las credenciales se cifran en MySQL y no vuelven al visor.
   V380 se configura desde «Abrir gestor local» y necesita su puente Windows.
4. Revisar el plan, elegir retención, exportar y luego instalar/aplicar Frigate.
   La configuración JSON/YAML usa go2rtc, detección a 5 fps, grabación original y
   autenticación habilitada. No se añade una conexión RTSP por cada espectador.
   Sin substream se comparte la fuente principal; considera el coste de decodificarla.
5. Cuando Frigate esté listo, verificar/vincular: sólo se actualizan aliases que
   Frigate confirmó y cámaras que aún pertenecen a esa empresa/sede.
6. Generar o introducir una contraseña de 12–128 caracteres para `admin`, guardarla
   en un gestor y establecerla. La API interna de Frigate recibe el cambio dentro
   de la red Docker privada, por una orden explícita del técnico.
7. Opcionalmente activar el gateway autenticado por sede. Usa Quick Tunnel sin
   dominio y actualiza la conexión de esa sede en Vigilay Web. Si existía otro
   gateway para esa sede, detenerlo de forma coordinada para evitar que ambos
   publiquen endpoints alternadamente; el asistente solicita confirmación.

**Live remoto:** requiere el agente de streaming existente y su FFmpeg compatible
con WHIP. Esta primera aplicación Desktop no instala V380Decoder ni el agente
Windows como servicio. No debe presentarse como instalador autónomo de todos los
componentes del live. Para Frigate creado aquí, el restream desde Windows está en
`rtsp://127.0.0.1:18554`; configura ese valor en el agente, no 8554 de otro NVR.

### Archivos, red y seguridad

- Proyecto Docker fijo `vigilay-desktop`, dentro del directorio de datos de la app.
  No usa el Compose del repositorio ni el contenedor `frigate` instalado previamente.
- Local sólo loopback `15000`; Frigate autenticado `18971`; RTSP `18554`; WebRTC
  `18555`, anunciado explícitamente como candidato WebRTC local. La API interna
  5000 de Frigate **no se publica**. No se montan sockets Docker.
- Frigate está fijado a `0.18.0`; Local/API a `v0.2.1-build-62`. Las versiones se
  cambian explícitamente en `deployment.rs`, tras probar la combinación.
- `compose.private.json` y la configuración de Frigate contienen secretos de la
  instalación. Windows restringe la carpeta al usuario y SYSTEM antes de escribir.
  **No están cifrados en disco**: protege y cifra el volumen, respalda de forma
  segura y no adjuntes esos archivos a soporte ni los subas a Git.
- Las URLs y contraseñas no se pasan como argumentos de procesos. El puente usa
  stdin; las respuestas, planes y errores de Docker se filtran. No hay una API
  HTTP nueva para extraer credenciales de cámaras.
- Antes de actualizar una configuración administrada se guarda una copia. Si
  cambió manualmente, pertenece a otra sede o no tiene marcador Desktop, se rechaza
  sobrescribirla. Las grabaciones nunca se eliminan desde el asistente.
- Una instalación con Frigate exportado queda ligada a su sede. Renombrar empresa
  o sede es válido; mover el NVR a otra identidad requiere una migración planificada.
- No hay autoupdater remoto ni permisos de comandos nativos para páginas externas.
  El instalador inicial no está firmado y Windows puede mostrar SmartScreen.

## Validación y entrega

Validación local inicial (17-09-2026): 105 pruebas Python aprobadas, Ruff sin
errores, interfaces Mobile/Desktop compiladas y auditorías npm sin vulnerabilidades
reportadas. Android `assembleDebug`, `testDebugUnitTest` y `lint` completados
(lint conserva avisos del proyecto/dependencias). APK de prueba:
`apps/mobile/android/app/build/outputs/apk/debug/app-debug.apk`.

La configuración exportada también fue aceptada por el modelo de configuración
de Frigate 0.18 dentro de un contenedor aislado, sin red ni cámaras reales.
**El ejecutable Windows no está compilado todavía:** esta PC carece de `link.exe`
de MSVC. La compilación/pruebas Rust y el instalador quedan pendientes del runner
Windows de GitHub Actions o de instalar los Build Tools en la PC. No se han
validado aún cámaras reales desde Android ni el asistente completo en una PC limpia.

La prueba API reproduce la cuadrícula de cuatro cámaras, dos páginas, límites e
identidad por empresa. Las pruebas del exportador cubren fuentes, aliases, copias,
credenciales y rechazo de sobrescritura. El workflow `Vigilay Mobile and Desktop`
compila Android y Windows y adjunta artefactos; no publica en tiendas ni modifica
instalaciones reales. La construcción nativa necesita dependencias de sus SDKs.

Antes de entregar al técnico, probar en una PC limpia: preparar → seleccionar
sede → registrar cámara → exportar → iniciar Frigate → establecer contraseña →
ver grabación → vincular gateway. Usar cámaras de prueba identificadas y no
reconfigurar una sede productiva como prueba automática.

Referencias: [Capacitor InAppBrowser](https://capacitorjs.com/docs/apis/inappbrowser),
[seguridad de Tauri](https://v2.tauri.app/security/),
[autenticación de Frigate](https://docs.frigate.video/configuration/authentication/).
