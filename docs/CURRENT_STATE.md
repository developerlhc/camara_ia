# Vigilay — estado inicial

Inspección: 2026-09-11. Fuente funcional: `Vigilay — Master Prompt para Astra.md`.

## Aplicación existente

`camara-ia.py` contiene un servidor Flask, una instancia global de CameraAnalytics y un hilo de captura RTSP. YOLO11n cuenta personas por frame; OpenCV detecta rostros y `face_recognition`, si está instalado y hay referencias, compara embeddings. El modelo se carga al importar el módulo. El video se entrega como MJPEG y el panel consulta tres endpoints cada 1,5 segundos.

El conteo mide presencia en la imagen; no implementa seguimiento de identidades ni conteo de entradas/salidas. Los recortes se extraen del frame original y usan un cooldown por nombre o posición aproximada. Los CSV persisten, pero el historial web de hasta 50 elementos se pierde al reiniciar porque no se recarga. La notificación HTTP se dispara al pasar de vacío a ocupado, con tres segundos de espera para rearmar; los errores de entrega se descartan.

Se inspeccionaron el script completo, la plantilla, requirements, iniciar.ps1, cabeceras de ambos CSV y directorios de imágenes. Hay fotos de visitas y un modelo local; `rostros_conocidos` solo contiene `.gitkeep`. No hay migraciones, pruebas, autenticación, aislamiento por cliente, framework frontend ni repositorio Git inicializado. Hay Python 3.13, Node 20 y Docker operativo en el equipo.

## Reutilización y deuda

- Reutilizar YOLO por pipeline, selección de clase persona, transformaciones de coordenadas, recorte contextual y reconocimiento facial por referencias.
- Extraer captura, IA, almacenamiento y notificación del servidor web antes de integrarlos con varios clientes.
- Sustituir el CSV como base primaria por MySQL; conservar originales para importación explícita.
- Eliminar credenciales de cámara y destinatarios codificados al preparar la migración del prototipo; nunca copiarlos al nuevo servicio o a imágenes Docker.
- Añadir sesiones, CSRF, RBAC, cifrado autenticado, filtros de tenant, auditoría y pruebas cruzadas.
- Sustituir MJPEG por sesiones MediaMTX/WebRTC autorizadas en una fase posterior.

Los archivos e imágenes originales se conservan. La nueva plataforma usa directorios y servicios propios; no se importa ni ejecuta el módulo Flask desde la API nueva.

Durante la implementación inicial se retiraron los valores RTSP y teléfono codificados del script y se conservaron en `.local/legacy-config.json`, excluido de Git y Docker. `camara-ia.py` los carga como alternativa a variables de entorno. La descripción anterior corresponde al estado previo a ese cambio.
