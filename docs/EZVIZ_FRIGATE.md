# EZVIZ (`cuarto`) y Frigate: causa confirmada y corrección

Última revisión: 14 de septiembre de 2026, con acceso directo a los logs del contenedor `frigate` y a `F:\ia\frigate\config\config.yaml` (fuera de este repositorio).

`docs/VALIDATION.md` registraba que Frigate tenía configurada la cámara `cuarto` (EZVIZ) sin confirmar que llegara imagen real. Se investigó directamente contra el Frigate en ejecución (versión `0.18.0-77a66e7`) y se encontró la causa exacta. Vigilay Web y la API no tienen ningún caso especial por marca: `cuarto` se comporta igual que `calle` o `imou` una vez que Frigate la recibe de forma estable, así que el problema nunca estuvo en este repositorio.

## Causa confirmada

`F:\ia\frigate\config\config.yaml` define las tres cámaras. `cuarto` es la única con el rol `audio` además de `detect`/`record`:

```yaml
cameras:
  cuarto:
    ffmpeg:
      inputs:
      - path: rtsp://admin:********@192.168.100.21:554/cam/realmonitor?channel=1&subtype=0
        roles:
        - detect
        - record
        - audio        # ← única diferencia real frente a calle e imou
  calle:
    ffmpeg:
      inputs:
      - path: rtsp://192.168.100.14:8555/live
        roles: [detect, record]
  imou:
    ffmpeg:
      inputs:
      - path: rtsp://admin:********@192.168.100.58:554/cam/realmonitor?channel=1&subtype=0
        roles: [detect, record]
```

El rol `audio` activa en Frigate 0.18 la detección de eventos por sonido y obliga a procesar la pista de audio de la cámara. La pista de audio que entrega esta EZVIZ trae timestamps corruptos, y eso tumba el proceso ffmpeg de `cuarto` en bucle:

```text
ffmpeg.cuarto.detect  ERROR : [aac @ ...] Queue input is backward in time
ffmpeg.cuarto.detect  ERROR : [aost#0:1/aac @ ...] Non-monotonic DTS; previous: 216292, current: 216290; changing to 216293.
ffmpeg.cuarto.detect  ERROR : [in#0/rtsp @ ...] Failed reading RTSP data: End of file
watchdog.cuarto       ERROR : Ffmpeg process crashed unexpectedly for cuarto.
watchdog.cuarto       INFO  : Restarting ffmpeg...
```

En los logs actuales del contenedor esto se repitió **1115 veces entre las 02:26 y las 11:40 (hora local)**, es decir, un reinicio cada ~30 segundos de forma sostenida. `calle` e `imou` no tienen ni un solo reinicio de este tipo en el mismo periodo. Por eso `cuarto` nunca logra mantener video estable: el video, la detección y la vista en vivo se cortan antes de que alguien alcance a verlos desde Vigilay.

## Corrección aplicada (14 de septiembre de 2026)

Se quitó el rol `audio` de `cuarto` en `F:\ia\frigate\config\config.yaml` (el video sigue grabándose y detectándose igual; solo se dejó de intentar procesar su audio, que es lo que fallaba):

```diff
   cuarto:
     ffmpeg:
       inputs:
       - path: rtsp://admin:********@192.168.100.21:554/cam/realmonitor?channel=1&subtype=0
         roles:
         - detect
         - record
-        - audio
```

Antes de editar se guardó una copia del archivo original en `F:\ia\frigate\config\config.yaml.bak-20260914-pre-audio-fix` (fuera de Git, junto al `config.yaml` real) por si hiciera falta revertir. Se confirmó que el YAML resultante es válido y que `cuarto` quedó con exactamente los mismos roles que `calle`/`imou` (`[detect, record]`) antes de reiniciar.

Se aplicó con:

```powershell
docker restart frigate
docker logs -f frigate
```

**Resultado observado:** en los minutos posteriores al reinicio no se registró ningún `watchdog.cuarto ERROR : Ffmpeg process crashed`, frente al reinicio cada ~30 segundos que había antes. Los tres procesos de `cuarto` (`frigate.process`, `frigate.capture`, `ffmpeg`) quedaron activos, y `calle`/`imou` siguieron funcionando sin errores nuevos. `docker exec frigate ... /api/config` sigue reportando las tres cámaras.

Esto es evidencia de los primeros minutos, no una estabilidad de largo plazo. Antes de marcar `cuarto` como verificado en `docs/VALIDATION.md` al mismo nivel que Imou, conviene:

1. Dejarlo funcionando un periodo más largo (varias horas) y volver a revisar `docker logs frigate | grep cuarto` en busca de nuevos reinicios.
2. Confirmar en Vigilay Web (**Eventos de IA** o el detalle de la cámara) que llegan eventos y grabaciones reales de `cuarto` cuando hay movimiento frente al lente.

Si más adelante se quiere recuperar la detección de eventos por audio en esta cámara puntual, hay que resolver primero el timestamp corrupto en el origen — Frigate ya aplica `-use_wallclock_as_timestamps 1` y `-fflags +genpts+discardcorrupt` en la captura principal, pero el pipeline separado que activa el rol `audio` volvió a fallar igual — y probarlo de forma aislada antes de reactivar ese rol, porque el mismo patrón (`Queue input is backward in time` / `Non-monotonic DTS`) puede repetirse.

## Si el video tampoco es estable después de quitar `audio`

Esto no se observó en los logs revisados (con `audio` fue lo único que crasheó), pero por si el retiro del rol no basta:

1. Repetir la prueba directa fuera de Frigate: `Test-NetConnection 192.168.100.21 -Port 554` y luego `ffprobe "rtsp://admin:CONTRASEÑA@192.168.100.21:554/cam/realmonitor?channel=1&subtype=0"` desde el mismo servidor.
2. Revisar si la contraseña sigue vigente (algunas EZVIZ obligan a rotar la contraseña RTSP periódicamente desde la app) y si la IP `192.168.100.21` sigue siendo la de esta cámara (reservarla por DHCP estático evita que cambie).
3. Revisar `docker logs --tail 200 frigate | grep cuarto` en busca de "Connection timed out" o "401 Unauthorized" en vez del patrón de audio de este documento.

## No hacer

- No copiar la contraseña real de la cámara a este repositorio, a `.env.example` ni a la documentación (la de arriba está enmascarada intencionalmente).
- No asumir que `EZVIZ_ENABLED` en `.env` cambia algo: `apps/api/src/vigilay/config.py` no lee esa variable; no está conectada a ningún código.
- No marcar `cuarto` como VERIFIED en `docs/VALIDATION.md` sin haber visto, después del cambio, varios minutos sin reinicios de ffmpeg y video real en `https://192.168.100.14:8971`.
