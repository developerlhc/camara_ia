import base64
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_env: str = "development"
    database_url: str
    redis_url: str = "redis://localhost:6379/0"
    session_secret: str
    internal_proxy_secret: str = ""
    credential_encryption_key: str
    web_origin: str = "http://localhost:3000"
    session_cookie_name: str = "vigilay_session"
    session_cookie_secure: bool = False
    session_ttl_seconds: int = 28800
    enable_simulator: bool = False

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
        return self


@lru_cache
def settings():
    return Settings()
