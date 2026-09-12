# Vigilay — adaptadores actuales

`services/camera-adapters/src/vigilay_adapters/base.py` define la interfaz inicial de probe, capacidades, lectura y escritura de ajustes. El único adaptador ejecutable actualmente es SIMULATOR. RTSP permite registrar la URL cifrada, pero la API responde 409 al solicitar conexión hasta que exista un Edge Agent; nunca muestra una comprobación ficticia de hardware.

El simulador devuelve una capacidad real de su implementación: sensibilidad de movimiento, legible/escribible de 0 a 100. Estado Redis separado de MySQL permite probar drift y desconexión. La UI genera el control únicamente cuando el probe detecta la capacidad.

La fase siguiente debe incorporar RTSP/ONVIF en el agente, claves de identidad por sitio, límites de red solicitados explícitamente y evidencia de modelo/firmware probado. Imou, EZVIZ y V380 permanecen sin integración y no se etiquetan VERIFIED. La interfaz se ampliará con streams, snapshots, PTZ y operaciones soportadas conforme se incorporen protocolos reales.
