# Vigilay — configuración

`.env.example` es el catálogo inicial; `.env` es privado de la instalación y está excluido de Git. API y CLI locales lo cargan desde el directorio de trabajo. Compose convierte las direcciones locales de MySQL/Redis a nombres internos de servicio. La web usa un proxy del mismo origen para evitar exponer credenciales o requerir tokens en almacenamiento del navegador.

| Variable | Propósito |
| --- | --- |
| DATABASE_URL | Conexión SQLAlchemy `mysql+pymysql`, esquema UTF8MB4. |
| MYSQL_DATABASE / MYSQL_USER / MYSQL_PASSWORD | Base y usuario de aplicación en Compose. |
| MYSQL_ROOT_PASSWORD | Inicialización/administración de MySQL; no se inyecta en la API. |
| REDIS_URL | Cache y coordinación. |
| SESSION_SECRET | Clave aleatoria de al menos 32 caracteres para CSRF. |
| INTERNAL_PROXY_SECRET | Secreto compartido solo entre web y API para autenticar la IP reenviada. |
| CREDENTIAL_ENCRYPTION_KEY | Clave AES de 32 bytes codificada en base64. No rotar sin migrar credenciales. |
| WEB_ORIGIN | Origen exacto permitido, inicialmente `http://localhost:3000`. |
| SESSION_COOKIE_SECURE | `true` para HTTPS/producción. |
| SESSION_TTL_SECONDS | Vida de sesión, inicialmente 28800. |
| ENABLE_SIMULATOR | Activa únicamente el adaptador de desarrollo. |
| API_INTERNAL_URL | Dirección privada de API que usa el servidor web. |
| ORIGIN | Origen público que usa adapter-node. |
| TEST_DATABASE_URL | Esquema separado cuyo nombre termina en `_test`. |
| TEST_REDIS_URL | Redis de pruebas, DB 1 por defecto. |
| VIGILAY_E2E_EMAIL / VIGILAY_E2E_PASSWORD | Cuenta de desarrollo para pruebas de navegador. |
| PLAYWRIGHT_CHANNEL | Opcional: `msedge` para usar Edge instalado. |

Generación manual de claves:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
python -c "import base64,secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())"
```

Usar claves independientes. Guardar SESSION_SECRET, INTERNAL_PROXY_SECRET, CREDENTIAL_ENCRYPTION_KEY y contraseñas MySQL en el gestor de secretos del entorno de despliegue. Nunca usar prefijos PUBLIC_ para secretos.

GitHub Actions usa GITHUB_TOKEN para GHCR. Las contraseñas CI son sintéticas y solo pertenecen a servicios efímeros. Futuras credenciales Bunny/Imou/EZVIZ se guardarán en GitHub Secrets o variables secretas del proveedor; sus banderas en el ejemplo no habilitan integraciones todavía.
