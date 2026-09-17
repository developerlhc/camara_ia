# V380 Pro y Frigate: estado y operación

Última comprobación: 16 de septiembre de 2026.

Este documento describe la instalación actual, cómo fluye el video desde la cámara V380 Pro hasta Frigate y cómo acceder desde otros equipos. No contiene contraseñas, claves de cifrado ni URLs con credenciales.

## Estado actual verificado

| Componente | Estado | Dirección o dato relevante |
| --- | --- | --- |
| Cámara V380 Pro | Registrada y activa | `192.168.100.59`, protocolo V380 en TCP `8800` |
| Puente V380 local | Operativo | Publica `rtsp://192.168.100.14:8556/live`; usa relay V380 mientras la IP LAN no responde |
| Video del puente | Verificado | Se recibió un fotograma de `640x1080` |
| Frigate | Operativo en Docker | Contenedor `frigate`, imagen `ghcr.io/blakeblackshear/frigate:stable` |
| Cámara `calle` en Frigate | Configurada | Fuente `rtsp://192.168.100.14:8556/live`; roles `detect` y `record` |
| Acceso web de Frigate | Publicado en la LAN | `https://192.168.100.14:8971` |
| Autenticación de Frigate | Activa por defecto | Usar usuarios creados en Frigate |

Frigate también tiene configuradas `cuarto` e `imou`. Sus credenciales no se documentan aquí.

Vigilay Web mantiene estas vinculaciones reales: `calle` con **V380 Pro**, `cuarto` con **EZVIZ principal** e `imou` con **Imou**. El 14 de septiembre de 2026 se verificó que Frigate recibe imagen real de Imou y procesa su fuente. Sus grabaciones y eventos aparecen en Vigilay cuando Frigate conserva segmentos o genera un evento según su política de retención; no se crean eventos sintéticos.

## Flujo de video

```text
V380 Pro (relay del fabricante; respaldo temporal)
        |
        | protocolo propietario V380
        v
V380Decoder.exe en Windows
        |
        | RTSP: 192.168.100.14:8556/live
        v
Frigate en Docker (cámara "calle", IA y grabación)
        |
        | API interna privada: Vigilay API
        v
Vigilay Web (eventos y grabaciones autorizados)
```

La cámara no respondió mediante RTSP directo en `192.168.100.59:554`. Por eso no se debe configurar en Frigate una URL como `rtsp://usuario:contraseña@192.168.100.59:554/...`. El puente local es obligatorio para este modelo y configuración.

## Datos de la V380 almacenados por Vigilay

La cámara se encuentra en MySQL, en las tablas `cameras` y `camera_credentials`. La credencial se almacena cifrada con AES-256-GCM y queda vinculada criptográficamente al identificador del cliente y de la cámara.

La variable `CREDENTIAL_ENCRYPTION_KEY` de `.env` es necesaria para descifrar las credenciales. No debe cambiarse ni perderse sin ejecutar antes una migración de claves.

Reglas de seguridad:

- No colocar contraseñas reales en `.env.example`.
- No guardar URLs RTSP con credenciales en documentación o Git.
- No copiar `CREDENTIAL_ENCRYPTION_KEY` a `.env.example`.
- Si una contraseña aparece en una captura, chat o commit, cambiarla en la cámara y actualizar la credencial almacenada.

La implementación correspondiente está en `camera_store.py` y `apps/api/src/vigilay/security.py`.

## Puente local V380

El visor inicia `.local/v380-bridge/V380Decoder.exe` con los siguientes valores no secretos:

| Parámetro | Valor actual |
| --- | --- |
| IP LAN registrada | `192.168.100.59` (actualmente sin respuesta) |
| Fuente activa | `cloud`, relay V380 |
| Calidad | `sd` |
| Puerto RTSP local | `8556` |
| Puerto HTTP/API local | `8081` |
| Ruta RTSP publicada | `/live` |

La contraseña se entrega al proceso mediante la variable temporal `V380_CAMERA_PASSWORD`; no se incluye como argumento del proceso.

El 16 de septiembre la dirección LAN registrada dejó de responder. Se verificó
la misma identidad por el relay V380 y se obtuvo un fotograma real, por lo que
la fuente cifrada de esta cámara quedó en modo `cloud`. Esto no utiliza
Cloudflare Stream, pero sí depende del relay del fabricante. Al reservar una IP
LAN estable para la cámara se puede volver a `lan` con
`python scripts/set_v380_source.py <camera-id> lan` y reiniciar Vigilay Local.

Para iniciar Vigilay y el puente:

```powershell
.\iniciar.ps1
```

El proceso debe permanecer activo. Si se cierra Vigilay o falla `V380Decoder.exe`, Frigate deja de recibir la cámara `calle`.

Comprobación rápida del puerto del puente:

```powershell
Test-NetConnection 192.168.100.14 -Port 8556
```

El resultado esperado es `TcpTestSucceeded : True`.

## Configuración actual de Frigate

La instalación persistente de Frigate está fuera de este repositorio:

| Uso | Ruta de Windows | Ruta en el contenedor |
| --- | --- | --- |
| Configuración y base de datos | `F:\ia\frigate\config` | `/config` |
| Grabaciones y medios | `F:\ia\frigate\storage` | `/media/frigate` |

El archivo principal es:

```text
F:\ia\frigate\config\config.yaml
```

La cámara V380 aparece en Frigate con el nombre `calle`, usa el stream del puente y tiene los roles `detect` y `record`. Las modificaciones realizadas desde la interfaz de Frigate quedan persistidas en ese archivo/directorio.

Comandos útiles:

```powershell
docker ps --filter "name=frigate"
docker logs --tail 100 frigate
docker restart frigate
```

El contenedor tiene la política de reinicio `unless-stopped`.

## Acceso desde la red local

Desde un equipo conectado a la misma red, abrir:

```text
https://192.168.100.14:8971
```

Frigate usa actualmente un certificado TLS autofirmado. El navegador puede presentar una advertencia la primera vez. Se debe iniciar sesión con un usuario de Frigate.

El puerto `8971` es la interfaz autenticada. No se debe publicar el puerto interno `5000`, ya que está pensado para integraciones confiables y no exige la misma autenticación.

Si Windows bloquea el acceso desde otros equipos, ejecutar PowerShell como administrador:

```powershell
New-NetFirewallRule `
  -DisplayName "Frigate 8971 LAN" `
  -Direction Inbound `
  -Action Allow `
  -Protocol TCP `
  -LocalPort 8971 `
  -RemoteAddress LocalSubnet `
  -Profile Private
```

Conviene reservar `192.168.100.14` para este PC mediante DHCP estático en el router. Si cambia la IP del PC, se deben actualizar la fuente `calle` en Frigate y la dirección usada por los navegadores.

## Acceso desde Internet

No abrir directamente en el router los puertos `8971`, `8554` o `8555`.

La opción recomendada es una VPN privada como Tailscale o WireGuard. Cada equipo autorizado entra a la VPN y accede al puerto autenticado `8971` usando la dirección privada asignada al servidor.

Si se requiere un dominio público, usar un proxy inverso con HTTPS, autenticación y destino interno `https://192.168.100.14:8971`. Esta opción requiere administrar correctamente certificados, actualizaciones, usuarios y registros de acceso.

## Puertos relevantes

| Puerto | Servicio | Exposición recomendada |
| --- | --- | --- |
| `8800/TCP` | Protocolo de la cámara V380 | Solo red local |
| `8081/TCP` | API local del puente V380 | Solo host/red local confiable |
| `8556/TCP` | RTSP generado por el puente | Solo red local; Frigate lo consume |
| `8971/TCP` | Interfaz autenticada de Frigate | LAN o VPN |
| `5000/TCP` | Interfaz interna sin autenticación de Frigate | No publicar |
| `8554/TCP` | Restream RTSP de Frigate | No publicar en Internet |

Frigate reserva `8555/TCP/UDP` para WebRTC. El puente V380 utiliza ahora `8556/TCP`: se comprobó que ambos procesos escuchaban simultáneamente en `8555`, provocando conflictos. No vuelvas a asignar ese puerto al puente. La entrada de `calle` en Frigate usa `-use_wallclock_as_timestamps 1` para corregir las marcas de tiempo repetidas del puente. Ver [diagnóstico del live](LIVE_RECUPERACION_2026-09-17.md).

## Orden recomendado de arranque

1. Encender y conectar la cámara V380 Pro a la red.
2. Iniciar Vigilay Local con `.\iniciar.ps1` para levantar el puente V380.
3. Confirmar que `192.168.100.14:8556` responde.
4. Iniciar o comprobar el contenedor `frigate`.
5. Abrir `https://192.168.100.14:8971` y verificar la cámara `calle`.
6. Iniciar la plataforma con `.\scripts\iniciar-vigilay.ps1`; el script conecta Frigate a la red privada de Vigilay.

## Diagnóstico rápido

Si `calle` no muestra video:

1. Comprobar que la cámara responde en la red y conserva la IP `192.168.100.59`.
2. Confirmar que Vigilay y `V380Decoder.exe` están ejecutándose.
3. Ejecutar `Test-NetConnection 192.168.100.14 -Port 8556`.
4. Revisar los logs del puente en `.local/v380-bridge/` sin publicar su contenido si contiene datos sensibles.
5. Revisar `docker logs --tail 100 frigate`.
6. Verificar que la fuente de `calle` siga siendo `rtsp://192.168.100.14:8556/live`.
7. Reiniciar primero el puente y luego Frigate si el stream quedó desconectado.
