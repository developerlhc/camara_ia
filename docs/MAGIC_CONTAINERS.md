# Despliegue central en Magic Containers

El despliegue central contiene Web, API y worker. MySQL puede ser administrado por
el proveedor. Vigilay Recorder, el agente de vivo y los puentes de cámara se
ejecutan únicamente en la sede porque necesitan acceso a su LAN y almacenamiento.

La web es el único servicio público. `API_INTERNAL_URL` y
`INTERNAL_PROXY_SECRET` protegen la comunicación interna Web → API. Las cookies
son HttpOnly/Secure y `WEB_ORIGIN` debe coincidir con el dominio público.

Desktop crea un Quick Tunnel saliente para el catálogo de grabaciones y registra
su URL con un token aleatorio por sede. La plataforma nunca publica el puerto
local 8788 ni entrega ese token al navegador. Para una operación estable a largo
plazo puede sustituirse el Quick Tunnel por un túnel administrado manteniendo el
mismo contrato HTTPS autenticado.

Las imágenes publicables son `vigilay-api`, `vigilay-web` y `vigilay-local`. La
última es opcional y se instala en la sede, no en el pod central. Los instaladores
de Vigilay Desktop se generan por separado con `npm run desktop:build`.
