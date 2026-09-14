import base64
from functools import lru_cache
from urllib.parse import quote_plus

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_env: str = "development"
    database_url: str = ""
    bdmysql: str = ""
    database_pool_size: int = 2
    database_max_overflow: int = 0
    session_secret: str
    internal_proxy_secret: str = ""
    credential_encryption_key: str
    web_origin: str = "http://localhost:3000"
    session_cookie_name: str = "vigilay_session"
    session_cookie_secure: bool = False
    session_ttl_seconds: int = 28800
    enable_simulator: bool = False
    cloudflare_account_id: str = ""
    cloudflare_stream_api_token: str = ""
    ffmpeg_path: str = "ffmpeg"
    v380_decoder_path: str = ".local/v380-bridge/V380Decoder.exe"
    frigate_api_url: str = "http://frigate:5000"
    frigate_timeout_seconds: int = 10
    frigate_gateway_port: int = 8788
    cloudflared_path: str = "cloudflared"
    stream_idle_timeout_seconds: int = 60
    stream_start_timeout_seconds: int = 15

    @model_validator(mode="before")
    @classmethod
    def accept_bdmysql_connection_string(cls, values):
        legacy = str(values.get("bdmysql") or values.get("BDMYSQL") or "").strip()
        if not legacy:
            return values
        parts = {}
        for item in legacy.split(";"):
            if "=" not in item:
                continue
            key, value = item.split("=", 1)
            parts[key.strip().lower()] = value.strip()
        host = parts.get("server") or parts.get("host")
        database = parts.get("database") or parts.get("initial catalog")
        username = parts.get("uid") or parts.get("user id") or parts.get("user")
        password = parts.get("pwd") or parts.get("password")
        port = parts.get("port", "3306")
        if all((host, database, username, password)):
            values["database_url"] = (
                f"mysql+pymysql://{quote_plus(username)}:{quote_plus(password)}"
                f"@{host}:{port}/{database}?charset=utf8mb4"
            )
        return values

    @model_validator(mode="after")
    def validate_security(self):
        if len(self.session_secret) < 32 or "CHANGE_ME" in self.session_secret:
            raise ValueError("SESSION_SECRET debe ser aleatorio y tener al menos 32 caracteres")
        try:
            key = base64.b64decode(self.credential_encryption_key, validate=True)
        except ValueError as exc:
            raise ValueError("CREDENTIAL_ENCRYPTION_KEY debe ser base64") from exc
        if len(key) != 32:
            raise ValueError("CREDENTIAL_ENCRYPTION_KEY debe contener 32 bytes")
        if self.app_env == "production" and (
            not self.session_cookie_secure or not self.web_origin.startswith("https://")
        ):
            raise ValueError("Producción requiere HTTPS y cookies Secure")
        if not self.database_url.startswith("mysql+pymysql://"):
            raise ValueError("Vigilay requiere MySQL mediante mysql+pymysql")
        if not 1 <= self.database_pool_size <= 10:
            raise ValueError("DATABASE_POOL_SIZE debe estar entre 1 y 10")
        if not 0 <= self.database_max_overflow <= 10:
            raise ValueError("DATABASE_MAX_OVERFLOW debe estar entre 0 y 10")
        if bool(self.cloudflare_account_id) != bool(self.cloudflare_stream_api_token):
            raise ValueError(
                "CLOUDFLARE_ACCOUNT_ID y CLOUDFLARE_STREAM_API_TOKEN deben configurarse juntos"
            )
        if not 10 <= self.stream_idle_timeout_seconds <= 3600:
            raise ValueError("STREAM_IDLE_TIMEOUT_SECONDS debe estar entre 10 y 3600")
        if not 3 <= self.stream_start_timeout_seconds <= 60:
            raise ValueError("STREAM_START_TIMEOUT_SECONDS debe estar entre 3 y 60")
        if not 2 <= self.frigate_timeout_seconds <= 60:
            raise ValueError("FRIGATE_TIMEOUT_SECONDS debe estar entre 2 y 60")
        if not 1024 <= self.frigate_gateway_port <= 65535:
            raise ValueError("FRIGATE_GATEWAY_PORT debe ser un puerto no privilegiado")
        return self


@lru_cache
def settings():
    return Settings()
