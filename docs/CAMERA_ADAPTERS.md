# Vigilay — adaptadores actuales

`services/camera-adapters/src/vigilay_adapters/base.py` conserva la interfaz inicial de probe, capacidades, lectura y escritura. En la plataforma actual, las conexiones reales RTSP y V380 se ejecutan desde el agente local; Frigate realiza IA, eventos y grabaciones, y Cloudflare transporta exclusivamente el vivo al navegador.

El simulador devuelve una capacidad real de su implementación: sensibilidad de movimiento, legible/escribible de 0 a 100. Su estado persistente en MySQL permite probar drift y desconexión. La UI genera el control únicamente cuando el probe detecta la capacidad.

Vigilay Local valida una identidad de empresa/sede y administra la asignación de cada cámara a un alias existente de Frigate. En la instalación actual, Frigate está configurado con fuentes Imou, EZVIZ y V380 (ver `docs/VALIDATION.md`), pero solo se verificó imagen y procesamiento real dentro de Frigate para Imou; V380 tiene video real confirmado hasta el puente local (`docs/V380_FRIGATE.md`) y EZVIZ (`cuarto`) todavía no se confirma en absoluto — ver `docs/EZVIZ_FRIGATE.md` para el diagnóstico. PTZ usa ONVIF para cámaras compatibles y la API local del puente para V380; el resultado exacto depende de las capacidades y firmware de cada cámara.
