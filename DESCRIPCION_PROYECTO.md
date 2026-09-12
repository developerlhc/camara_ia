# IA Vigilancia

Esta descripción corresponde al prototipo original. La nueva plataforma **Vigilay** y su estado de construcción se documentan en [README.md](README.md) y [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md).

## ¿De qué va este proyecto?

Es una aplicación local de videovigilancia para un negocio. Se conecta a una cámara IP mediante RTSP, analiza el video en tiempo real y muestra un panel web con el número de personas presentes, los rostros detectados y los eventos recientes.

La detección de personas se realiza con el modelo `yolo11n.pt` de Ultralytics/YOLO. El reconocimiento facial es opcional: si se instala `face_recognition` y se agregan fotografías autorizadas en `rostros_conocidos`, la aplicación puede mostrar el nombre de las personas reconocidas. Sin ese paquete o sin rostros registrados, solo identifica rostros como `Desconocido`.

## Flujo principal

1. Abre la cámara RTSP y descarta frames antiguos para reducir la latencia.
2. Ejecuta YOLO para contar objetos de la clase persona.
3. Busca rostros dentro de las personas detectadas.
4. Reconoce los rostros registrados, cuando está habilitado el reconocimiento facial.
5. Dibuja las detecciones sobre el video y lo publica en el navegador.
6. Guarda conteos periódicos en un CSV y fotos de los rostros detectados.
7. Envía una notificación HTTP cuando el local pasa de vacío a ocupado. La alerta se rearma después de varios segundos sin personas.

## Componentes principales

- `camara-ia.py`: servidor Flask y motor de análisis de video.
- `templates/index.html`: panel web de monitoreo.
- `yolo11n.pt`: modelo YOLO utilizado para detectar personas.
- `rostros_conocidos/`: imágenes de referencia para reconocimiento facial.
- `reportes/conteo_personas.csv`: histórico de conteos, rostros y nombres reconocidos.
- `reportes/visitas.csv`: registro de fotos de visitas y coordenadas de los rostros.
- `visitas/`: imágenes guardadas de los rostros detectados.
- `iniciar.ps1`: inicio con una configuración orientada a calidad de imagen.

## Panel web y API

Al iniciar el servidor, el panel queda disponible en `http://localhost:5000`.

- `/`: interfaz de monitoreo.
- `/video_feed`: video MJPEG anotado en vivo.
- `/api/status`: estado de la cámara, conteo actual y personas reconocidas.
- `/api/events`: últimos eventos de conteo.
- `/api/visits`: visitas registradas.
- `/api/clear-history`: limpia el historial y elimina las imágenes de `visitas/`.

## Ejecución

En PowerShell:

```powershell
.\.venv\Scripts\activate
pip install -r requirements.txt
python .\camara-ia.py
```

También se puede ejecutar:

```powershell
.\iniciar.ps1
```

La cámara se configura mediante `RTSP_URL`. También se pueden ajustar por variables de entorno la resolución, FPS, confianza de YOLO, frecuencia de reportes, intervalo de guardado de visitas y tiempo para considerar vacío el local.

## Reconocimiento facial

Para activarlo:

1. Instalar la dependencia opcional `face_recognition`.
2. Colocar imágenes claras y autorizadas en `rostros_conocidos/`.

Ejemplos de estructura:

```text
rostros_conocidos/
  Juan/
    foto1.jpg
  Maria.jpg
```

El nombre de una carpeta o archivo se utiliza como nombre de la persona.

## Consideraciones

- El sistema está pensado para ejecutarse de forma local y no incluye autenticación propia para el panel web.
- El reconocimiento facial y el almacenamiento de imágenes implican datos personales; deben usarse con autorización y conforme a la normativa aplicable.
- Conviene mover la URL RTSP, especialmente si contiene usuario y contraseña, a variables de entorno y cambiar cualquier credencial expuesta.
- La notificación depende de un servicio HTTP externo configurado en `NOTIFY_URL`.
- El histórico y las fotos crecen con el tiempo; se recomienda establecer una política de retención y limpieza.
