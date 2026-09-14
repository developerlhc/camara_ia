from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LoginInput(Input):
    identifier: str = Field(min_length=1, max_length=254)
    password: SecretStr = Field(min_length=1, max_length=256)


class TenantInput(Input):
    name: str = Field(min_length=1, max_length=160)
    legal_name: str = Field(default="", max_length=200)
    tax_id: str = Field(default="", max_length=32)
    timezone: str = "America/Lima"

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Zona horaria desconocida") from exc
        return value


class TenantUpdate(TenantInput):
    status: Literal["ACTIVE", "SUSPENDED"] = "ACTIVE"


class SiteInput(Input):
    tenant_id: str = Field(min_length=36, max_length=36)
    name: str = Field(min_length=1, max_length=160)
    address: str = Field(default="", max_length=300)
    description: str = Field(default="", max_length=2000)


class UserInput(Input):
    tenant_id: str = Field(min_length=36, max_length=36)
    email: EmailStr
    username: str = Field(min_length=3, max_length=80, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: SecretStr = Field(min_length=12, max_length=256)
    first_name: str = Field(default="", max_length=100)
    last_name: str = Field(default="", max_length=100)
    role: Literal["CLIENT_ADMIN", "OPERATOR", "VIEWER"] = "VIEWER"


class UserUpdate(Input):
    first_name: str = Field(max_length=100)
    last_name: str = Field(max_length=100)
    status: Literal["ACTIVE", "DISABLED"]
    role: Literal["CLIENT_ADMIN", "OPERATOR", "VIEWER"]


class PasswordChange(Input):
    current_password: SecretStr = Field(max_length=256)
    new_password: SecretStr = Field(min_length=12, max_length=256)


class PasswordResetInput(Input):
    token: SecretStr = Field(min_length=32, max_length=256)
    new_password: SecretStr = Field(min_length=12, max_length=256)


class CameraInput(Input):
    tenant_id: str = Field(min_length=36, max_length=36)
    site_id: str = Field(min_length=36, max_length=36)
    name: str = Field(min_length=1, max_length=160)
    integration_type: Literal["RTSP", "V380", "SIMULATOR"]
    brand: Literal["EZVIZ", "IMOU", "V380", "GENERIC"] = "GENERIC"
    model: str = Field(default="", max_length=120)
    frigate_camera_name: str | None = Field(
        default=None, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$"
    )
    target_fps: int = Field(default=10, ge=1, le=30, strict=True)
    grayscale: bool = False
    rtsp_url: SecretStr | None = Field(default=None, max_length=2048)
    host: str | None = Field(default=None, max_length=253)
    port: int | None = Field(default=None, ge=1, le=65535)
    username: str | None = Field(default=None, max_length=160)
    password: SecretStr | None = Field(default=None, max_length=256)
    device_id: str | None = Field(default=None, max_length=32)


class SettingsInput(Input):
    motion_sensitivity: int = Field(ge=0, le=100, strict=True)


class PermissionInput(Input):
    user_id: str = Field(min_length=36, max_length=36)
    can_view: bool
    can_configure: bool


class PtzInput(Input):
    action: Literal[
        "up",
        "down",
        "left",
        "right",
        "up-left",
        "up-right",
        "down-left",
        "down-right",
        "zoom-in",
        "zoom-out",
    ]
    speed: float = Field(default=0.5, ge=0.1, le=1.0)


class LiveSessionInput(Input):
    session_id: str = Field(min_length=36, max_length=36)
    viewer_key: SecretStr = Field(min_length=32, max_length=256)


class CloudflareIntegrationInput(Input):
    account_id: str = Field(min_length=1, max_length=64)
    api_token: SecretStr = Field(min_length=20, max_length=256)


class FrigateCameraInput(Input):
    frigate_camera_name: str = Field(
        min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$"
    )
