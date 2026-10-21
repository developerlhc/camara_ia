# Grabador V380 por movimiento

Servicio independiente de Frigate que consume el RTSP publicado por
`V380Decoder.exe` y genera clips MP4 cuando detecta movimiento.

## Uso

La forma recomendada es hacer doble clic en `Abrir Grabador V380.cmd`. También
puede abrirse desde PowerShell con:

```powershell
.\abrir_grabador_v380.ps1
```

Pulsa **Iniciar grabación**. La aplicación inicia el puente V380 si es necesario,
carga YOLO y graba automáticamente partes de 20 segundos mientras detecta personas.
No hace falta iniciar Frigate ni ejecutar otros comandos.

El script de consola continúa disponible para diagnóstico:

```powershell
.\tools\v380_motion_recorder\iniciar.ps1 --detector yolo --max-clip 20
```

Los clips se guardan en `grabaciones_v380/AAAA-MM-DD/calle/`. Cada MP4 tiene
un JSON contiguo con sus horas, número de fotogramas y motivo de cierre.

Para cambiar sensibilidad y duración:

```powershell
& .\.venv\Scripts\python.exe -m tools.v380_motion_recorder.recorder `
  --detector motion --min-area-percent 0.25 --pre-roll 5 --post-roll 20
```

- Baja `--min-area-percent` para detectar movimientos más pequeños.
- Sube ese valor si hay falsas alarmas por ruido, árboles o cambios de luz.
- `--max-clip` divide automáticamente una actividad prolongada.
- El proceso se niega a iniciar un clip si quedan menos de 2 GB libres.

Este servicio graba únicamente desde que está ejecutándose. No puede recuperar
archivos históricos guardados solamente en la microSD de la cámara.
