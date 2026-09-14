Sí. Con la información de estas capturas ya podemos plantear una conexión local correcta para esa V380 Pro.

De tus pantallas tenemos:

ID V380: 120767501
Modelo mostrado: HsAKTQWQ
Hardware: HW_HsAKQQXG_WIFI_20230421
Firmware: AppKN_VACL4_V1.5.3.0_20250611
Keep-alive: AppV380E2201_LP_V1.2.5_20240416

El QR grande de la última captura no es la contraseña RTSP. Es un código temporal para compartir/autorización dentro del ecosistema V380; la propia pantalla indica que caduca y que se invalida al reiniciar el dispositivo.

Para Vigilay, no necesitamos ese QR.

1. Lo primero: activar ONVIF

V380 documenta oficialmente que las cámaras compatibles pueden conectarse localmente a NVR mediante ONVIF, usando normalmente el puerto 8899. En la app V380 Pro debes buscar:

Cámara → Configuración → Configuración avanzada → ONVIF / Onvif setting

y activarlo. V380 también advierte que, si el firmware no soporta ONVIF, esa opción simplemente no aparece.

Esto es exactamente lo que necesitamos comprobar en tu cámara.

Busca algo parecido a:
Configuración
   ↓
Configuración avanzada
   ↓
ONVIF
   [ ACTIVADO ]

Si puedes mandarme una captura de Configuración avanzada, podremos confirmar inmediatamente si este firmware lo permite.

2. Necesitamos la IP local

El 120767501 es el ID de V380, no la dirección IP. V380 confirma que ese número de 8/9 dígitos es el identificador único del dispositivo.

Necesitamos algo como:

192.168.1.37

o:

192.168.0.105

La forma más fiable es entrar al router y buscar:

Dispositivos conectados
DHCP Clients
Clientes LAN
Dispositivos WiFi

Encontrarás la cámara entre los dispositivos.

V380 recomienda que cámara y equipo/NVR estén en la misma LAN y el mismo gateway. También hay que evitar una red de invitados o aislamiento entre dispositivos.

3. Una vez encontrada la IP, tenemos dos formas de conectarnos

Para Vigilay yo implementaría ONVIF primero y RTSP después.

El flujo sería:

              RED LOCAL DEL CLIENTE
                      
┌──────────────────────────────────────┐
│                                      │
│ V380 Pro                             │
│ 192.168.1.37                         │
│                                      │
│   ONVIF :8899                        │
│       │                              │
│       │ descubre cámara/perfiles     │
│       ▼                              │
│ Vigilay Gateway                      │
│       │                              │
│       │ obtiene stream RTSP          │
│       ▼                              │
│ RTSP :554                            │
│ /live/ch00_1                         │
│                                      │
└──────────────────────────────────────┘

Eso es mucho mejor que intentar depender del sistema cloud de V380.

4. ONVIF

Según la documentación oficial de V380, la configuración manual es:

Protocolo:        ONVIF
Puerto:           8899
Formato:          H.264
Transporte:       TCP
Usuario:          admin (opcional)
Contraseña:       vacía (opcional)
Ruta de vídeo:    /live/ch00_1

Así que inicialmente probaríamos:

V380_IP=192.168.1.37
V380_ONVIF_PORT=8899
V380_USER=admin
V380_PASSWORD=

Sustituyendo obviamente 192.168.1.37 por la IP real.

5. RTSP de esta familia V380

V380 documenta estas dos rutas:

Alta calidad / stream principal

/live/ch00_1

Baja calidad / substream

/live/ch00_0

Así que si la IP fuera 192.168.1.37, probaríamos primero:

rtsp://192.168.1.37/live/ch00_1

RTSP usa normalmente el puerto 554, por lo que equivale a:

rtsp://192.168.1.37:554/live/ch00_1

Para el stream de menor calidad:

rtsp://192.168.1.37:554/live/ch00_0
6. ¿Y el usuario/contraseña?

Aquí hay que tener cuidado porque depende de cómo esté configurado este firmware.

V380 especifica que admin y contraseña vacía pueden ser opcionales en la conexión NVR, pero también permite establecer una contraseña propia para la cámara desde la aplicación.

Yo te recomiendo establecer una contraseña específica para acceso local.

En V380 Pro busca:

Configuración
    ↓
Contraseña
    ↓
Cambiar contraseña del dispositivo

Entonces tendríamos:

V380_USER=admin
V380_PASSWORD=UnaClaveSegura

Y RTSP:

rtsp://admin:UnaClaveSegura@192.168.1.37:554/live/ch00_1

Para Vigilay sería mucho mejor que dejarla sin contraseña.

7. Cómo comprobarlo desde tu PC

Si estás en Windows y conoces la IP:

Test-NetConnection 192.168.1.37 -Port 8899

y:

Test-NetConnection 192.168.1.37 -Port 554

Si aparece:

TcpTestSucceeded : True

tenemos muy buenas noticias.

Idealmente queremos:

8899  OPEN    ONVIF
554   OPEN    RTSP
8. Probar el vídeo

Con FFmpeg instalado:

ffplay -rtsp_transport tcp "rtsp://192.168.1.37:554/live/ch00_1"

Si necesita autenticación:

ffplay -rtsp_transport tcp "rtsp://admin:TU_PASSWORD@192.168.1.37:554/live/ch00_1"

Para comprobarlo sin abrir una ventana de vídeo:

ffprobe -rtsp_transport tcp "rtsp://admin:TU_PASSWORD@192.168.1.37:554/live/ch00_1"

Si funciona deberíamos obtener algo parecido a:

Video: h264
1920x1080
25 fps

V380 indica oficialmente que la conexión NVR local utiliza H.264.

9. No pondría únicamente RTSP_URL en Vigilay

Para el prototipo puede valer:

RTSP_URL=rtsp://admin:password@192.168.1.37:554/live/ch00_1

Pero para lo que estás construyendo sería mejor guardar:

CAMERA_VENDOR=v380
CAMERA_IP=192.168.1.37

CAMERA_ONVIF_ENABLED=true
CAMERA_ONVIF_PORT=8899

CAMERA_RTSP_PORT=554

CAMERA_USERNAME=admin
CAMERA_PASSWORD=xxxxxxx

CAMERA_MAIN_STREAM=/live/ch00_1
CAMERA_SUB_STREAM=/live/ch00_0

Y que Vigilay construya internamente las URL.

10. Incluso podemos evitar pedir la URL RTSP al usuario

Esta es la parte interesante para tu proyecto.

Cuando alguien agregue una cámara:

Agregar cámara
─────────────────────────

Marca
[V380 Pro ▼]

Dirección IP
[192.168.1.37]

Usuario
[admin]

Contraseña
[••••••••]

        [ Detectar cámara ]

Vigilay haría:

                 Detectar
                    │
                    ▼
          ¿responde puerto 8899?
              │            │
             Sí            No
              │            │
              ▼            ▼
         probar ONVIF    probar RTSP
              │
              ▼
       obtener perfiles
              │
              ▼
        obtener streams
          │         │
          ▼         ▼
        MAIN       SUB
          │         │
          ▼         ▼
      ch00_1     ch00_0

Eso permitiría mostrar:

✓ Cámara encontrada

Fabricante: V380
Modelo: HsAKTQWQ
Dirección: 192.168.1.37
ONVIF: Disponible
RTSP: Disponible
Codec: H.264

Stream principal    ✓
Stream secundario   ✓

[ Guardar cámara ]
Y ONVIF nos da algo adicional

No solamente vídeo.

La documentación oficial de V380 señala que mediante la conexión NVR soporta visualización en tiempo real, PTZ y almacenamiento en NVR. No soporta todas las funciones propietarias de la app, como intercomunicador, alarmas push o control de luces.

Eso significa que para Vigilay podríamos potencialmente tener:

        V380
          │
      ┌───┴────┐
      │ ONVIF  │
      └───┬────┘
          │
 ┌────────┼────────┐
 │        │        │
 ▼        ▼        ▼
VIDEO    PTZ    PERFILES
 │        │
 ▼        ▼
Vigilay  ← ↑ → ↓

Y eso ya empieza a ser exactamente la plataforma centralizada que quieres construir.

11. Hay una limitación importante

El navegador no reproduce directamente:

rtsp://...

Así que SvelteKit no debe enviar la URL RTSP directamente al <video> del navegador.

Necesitaremos:

V380
   │
   │ RTSP
   ▼
Vigilay Gateway
   │
   ├── WebRTC ─────► navegador
   │
   └── HLS ────────► navegador

Ahí podemos utilizar un gateway como MediaMTX o go2rtc, mientras SvelteKit maneja usuarios, permisos, clientes, cámaras, eventos, configuraciones, etc.

Lo siguiente que haría con esta cámara

No necesitamos más QR ni más ID.

Haz estas dos comprobaciones:

En V380 Pro entra a Configuración → Configuración avanzada y busca ONVIF.
En tu router busca la IP de la cámara.

Después pásame algo así:

ONVIF: sí aparece / no aparece
IP: 192.168.x.x

Con esos dos datos te doy directamente los comandos exactos para comprobar ONVIF + RTSP + PTZ en esta HsAKTQWQ/HsAKQQXG, y podremos saber si esta V380 sirve como primera cámara real para Vigilay.



El ONVIF virtual publica video pero no anuncia PTZ de forma compatible con la librería actual. Lo resolveré usando la API local del puente para los botones de movimiento; la contraseña seguirá fuera del navegador y de la línea de comandos. Después dejaré la V380 como tercera cámara automática.