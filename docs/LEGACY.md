# Vigilay — prototipo original

App local para contar personas en un negocio con YOLO y mostrar un reporte web en tiempo real.

## Ejecutar

```powershell
.\.venv\Scripts\activate
pip install -r requirements.txt
python .\camara-ia.py
```

Tambien puedes iniciar con la configuracion recomendada:

```powershell
.\iniciar.ps1
```

Abre el panel en:

```text
http://localhost:5000
```

## Camara

El script usa la variable `RTSP_URL`. Si quieres cambiar la camara sin editar codigo:

```powershell
$env:RTSP_URL="rtsp://usuario:clave@IP:554/ch1/main"
python .\camara-ia.py
```

## Reducir retraso

La app prioriza baja latencia y descarta frames viejos antes de procesar. Puedes ajustar estos valores:

```powershell
$env:FRAME_WIDTH="640"
$env:PROCESS_WIDTH="512"
$env:YOLO_IMAGE_SIZE="416"
$env:TARGET_FPS="10"
$env:DROP_BUFFER_FRAMES="12"
python .\camara-ia.py
```

Si se ve entrecortado, baja `TARGET_FPS` a `5` u `8`. Si todavia hay retraso, sube `DROP_BUFFER_FRAMES`.

Para hacerlo todavia mas rapido puedes usar:

```powershell
$env:FRAME_WIDTH="960"
$env:PROCESS_WIDTH="416"
$env:YOLO_IMAGE_SIZE="416"
$env:TARGET_FPS="12"
$env:DROP_BUFFER_FRAMES="18"
python .\camara-ia.py
```

Esto reduce detalle visual, pero baja la latencia.

## Reconocimiento facial

El conteo de personas funciona con YOLO. Para identificar personas por nombre, instala opcionalmente `face_recognition` y coloca fotos claras en `rostros_conocidos`.

Ejemplos:

```text
rostros_conocidos/
  Juan/
    foto1.jpg
  Maria.jpg
```

Usa solo imagenes de personas que hayan autorizado ser registradas, y revisa las normas aplicables a tu negocio.

## Reportes

La app guarda registros cada pocos segundos en:

```text
reportes/conteo_personas.csv
```

Tambien guarda visitas con foto del rostro:

```text
visitas/
reportes/visitas.csv
```

Solo guarda imagen cuando detecta un rostro. Si detecta una persona pero no encuentra rostro claro, no guarda foto en la tabla de visitas.

Por defecto guarda una nueva foto del mismo visitante cada 30 segundos. Para cambiarlo:

```powershell
$env:VISIT_SAVE_SECONDS="15"
python .\camara-ia.py
```

Para subir mas la calidad de foto y video:

```powershell
$env:FRAME_WIDTH="1280"
$env:CAMERA_WIDTH="1920"
$env:CAMERA_HEIGHT="1080"
$env:JPEG_QUALITY="98"
$env:FACE_CONTEXT_SCALE="3.2"
$env:FACE_MIN_CROP_WIDTH="520"
$env:UPSCALE_FACE_CROP="0"
python .\camara-ia.py
```

Las fotos se guardan desde el frame original de la camara. `FRAME_WIDTH` mejora lo que ves en la web. `FACE_CONTEXT_SCALE` y `FACE_MIN_CROP_WIDTH` guardan un recorte mas amplio alrededor del rostro para conservar mas detalle real. `UPSCALE_FACE_CROP=0` evita agrandar digitalmente una cara pequena, porque eso se ve borroso.

`FACE_DETECT_WIDTH` controla la resolucion usada para encontrar rostros. Si tu camara esta lejos de la puerta, subelo:

```powershell
$env:FACE_DETECT_WIDTH="1600"
$env:FACE_MIN_CROP_WIDTH="640"
.\.venv\Scripts\python.exe .\camara-ia.py
```

## Notificaciones

Cuando la tienda pasa de estar vacia a tener una o mas personas, envia un POST a:

```text
https://cenfelec.com/notificarmsg
```

Si la persona se va y luego regresa, vuelve a enviar el aviso. Para evitar falsos avisos por un frame perdido, espera unos segundos continuos sin personas antes de considerar la tienda vacia otra vez.

Puedes ajustar telefono, mensaje y segundos para rearmar la alerta:

```powershell
$env:NOTIFY_PHONE="51XXXXXXXXX"
$env:NOTIFY_MESSAGE="alguien llego a la tienda."
$env:EMPTY_RESET_SECONDS="3"
python .\camara-ia.py
```
