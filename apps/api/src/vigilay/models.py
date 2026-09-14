from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow():
    # MySQL DATETIME stores UTC without an offset. API serializers append Z.
    return datetime.now(UTC).replace(tzinfo=None)


def new_id():
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Identity:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TenantScoped:
    tenant_id: Mapped[str | None] = mapped_column(String(36), index=True)


class Tenant(Identity, Base):
    __tablename__ = "tenants"
    name: Mapped[str] = mapped_column(String(160))
    legal_name: Mapped[str] = mapped_column(String(200), default="")
    tax_id: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    timezone: Mapped[str] = mapped_column(String(64), default="America/Lima")
    settings_json: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Site(TenantScoped, Identity, Base):
    __tablename__ = "sites"
    __table_args__ = (UniqueConstraint("id", "tenant_id"),)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    address: Mapped[str] = mapped_column(String(300), default="")
    timezone: Mapped[str] = mapped_column(String(64), default="America/Lima")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class User(TenantScoped, Identity, Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("id", "tenant_id", name="uq_users_id_tenant"),)
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id"), index=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    first_name: Mapped[str] = mapped_column(String(100), default="")
    last_name: Mapped[str] = mapped_column(String(100), default="")
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Role(Base):
    __tablename__ = "roles"
    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    scope: Mapped[str] = mapped_column(String(16))
    description: Mapped[str] = mapped_column(String(200))


class Permission(Base):
    __tablename__ = "permissions"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    description: Mapped[str] = mapped_column(String(200))


class RolePermission(Base):
    __tablename__ = "role_permissions"
    role_name: Mapped[str] = mapped_column(ForeignKey("roles.name"), primary_key=True)
    permission_key: Mapped[str] = mapped_column(ForeignKey("permissions.key"), primary_key=True)


class UserRole(TenantScoped, Base):
    __tablename__ = "user_roles"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "tenant_id"], ["users.id", "users.tenant_id"], name="fk_role_user_tenant"
        ),
        CheckConstraint(
            "(role_name = 'SUPER_ADMIN' AND tenant_id IS NULL) OR (role_name <> 'SUPER_ADMIN' AND tenant_id IS NOT NULL)",
            name="ck_role_scope",
        ),
    )
    # Initial policy: one role per user, with the tenant inherited from users.
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    role_name: Mapped[str] = mapped_column(ForeignKey("roles.name"))


class LoginSession(TenantScoped, Identity, Base):
    __tablename__ = "sessions"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    ip_address: Mapped[str] = mapped_column(String(64))
    user_agent: Mapped[str] = mapped_column(String(300))
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)


class LoginAttempt(Identity, Base):
    __tablename__ = "login_attempts"
    __table_args__ = (Index("ix_login_window", "ip_address", "created_at"),)
    username_or_email_hash: Mapped[str] = mapped_column(String(64), index=True)
    ip_address: Mapped[str] = mapped_column(String(64))
    successful: Mapped[bool] = mapped_column(Boolean)


class RateLimitBucket(Base):
    __tablename__ = "rate_limit_buckets"
    bucket_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ServiceHeartbeat(Base):
    __tablename__ = "service_heartbeats"
    service_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class SimulatorState(TenantScoped, Base):
    __tablename__ = "simulator_states"
    __table_args__ = (
        ForeignKeyConstraint(
            ["camera_id", "tenant_id"],
            ["cameras.id", "cameras.tenant_id"],
            name="fk_simulator_state_camera_tenant",
        ),
    )
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    camera_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    motion_sensitivity: Mapped[int] = mapped_column(Integer, default=50)
    offline: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class PasswordReset(Identity, Base):
    __tablename__ = "password_reset_tokens"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)


class IntegrationSetting(Identity, Base):
    __tablename__ = "integration_settings"
    provider: Mapped[str] = mapped_column(String(32), unique=True)
    config_encrypted: Mapped[bytes] = mapped_column(LargeBinary)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class AuditLog(TenantScoped, Identity, Base):
    __tablename__ = "audit_logs"
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id"), index=True)
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(64), index=True)
    resource_type: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[str | None] = mapped_column(String(36))
    ip_address: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(300), default="")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)


class Camera(TenantScoped, Identity, Base):
    __tablename__ = "cameras"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id"),
        UniqueConstraint("site_id", "frigate_camera_name", name="uq_camera_site_frigate_name"),
        ForeignKeyConstraint(["site_id", "tenant_id"], ["sites.id", "sites.tenant_id"]),
    )
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    site_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(160))
    integration_type: Mapped[str] = mapped_column(String(32))
    brand: Mapped[str] = mapped_column(String(32), default="GENERIC")
    model: Mapped[str] = mapped_column(String(120), default="")
    frigate_camera_name: Mapped[str | None] = mapped_column(String(80))
    target_fps: Mapped[int] = mapped_column(Integer, default=10)
    grayscale: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="UNVERIFIED")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class CameraCredential(TenantScoped, Identity, Base):
    __tablename__ = "camera_credentials"
    __table_args__ = (
        UniqueConstraint("camera_id"),
        ForeignKeyConstraint(["camera_id", "tenant_id"], ["cameras.id", "cameras.tenant_id"]),
    )
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    camera_id: Mapped[str] = mapped_column(String(36))
    secret_encrypted: Mapped[bytes] = mapped_column(LargeBinary)


class CameraStreamProvider(TenantScoped, Identity, Base):
    __tablename__ = "camera_stream_providers"
    __table_args__ = (
        UniqueConstraint("camera_id"),
        ForeignKeyConstraint(
            ["camera_id", "tenant_id"],
            ["cameras.id", "cameras.tenant_id"],
            name="fk_stream_provider_camera_tenant",
        ),
    )
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    camera_id: Mapped[str] = mapped_column(String(36), index=True)
    provider: Mapped[str] = mapped_column(String(32), default="cloudflare")
    provider_live_input_uid: Mapped[str] = mapped_column(String(64), unique=True)
    publish_url_encrypted: Mapped[bytes] = mapped_column(LargeBinary)
    playback_url: Mapped[str] = mapped_column(String(2048))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class CameraStreamSession(TenantScoped, Identity, Base):
    __tablename__ = "camera_stream_sessions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["camera_id", "tenant_id"],
            ["cameras.id", "cameras.tenant_id"],
            name="fk_stream_session_camera_tenant",
        ),
        Index("ix_stream_session_camera_status", "camera_id", "status"),
        CheckConstraint(
            "status IN ('starting','live','stopping','stopped','error')",
            name="ck_stream_session_status",
        ),
    )
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    camera_id: Mapped[str] = mapped_column(String(36), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    viewer_key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="starting")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime)
    stop_reason: Mapped[str | None] = mapped_column(String(64))
    sanitized_error: Mapped[str | None] = mapped_column(String(300))


class NotificationChannel(TenantScoped, Identity, Base):
    __tablename__ = "notification_channels"
    __table_args__ = (UniqueConstraint("tenant_id", "channel"),)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    channel: Mapped[str] = mapped_column(String(32))
    config_encrypted: Mapped[bytes] = mapped_column(LargeBinary)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class CameraPermission(TenantScoped, Base):
    __tablename__ = "user_camera_permissions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_permission_user_tenant",
        ),
        ForeignKeyConstraint(
            ["camera_id", "tenant_id"],
            ["cameras.id", "cameras.tenant_id"],
            name="fk_permission_camera_tenant",
        ),
    )
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    camera_id: Mapped[str] = mapped_column(ForeignKey("cameras.id"), primary_key=True)
    can_view: Mapped[bool] = mapped_column(Boolean, default=False)
    can_configure: Mapped[bool] = mapped_column(Boolean, default=False)


class CameraCapability(TenantScoped, Base):
    __tablename__ = "camera_capabilities"
    __table_args__ = (
        ForeignKeyConstraint(
            ["camera_id", "tenant_id"],
            ["cameras.id", "cameras.tenant_id"],
            name="fk_capability_camera_tenant",
        ),
    )
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    camera_id: Mapped[str] = mapped_column(ForeignKey("cameras.id"), primary_key=True)
    capability_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    supported: Mapped[bool] = mapped_column(Boolean, default=False)
    readable: Mapped[bool] = mapped_column(Boolean, default=False)
    writable: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CameraSetting(TenantScoped, Base):
    __tablename__ = "camera_settings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["camera_id", "tenant_id"],
            ["cameras.id", "cameras.tenant_id"],
            name="fk_setting_camera_tenant",
        ),
    )
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    camera_id: Mapped[str] = mapped_column(ForeignKey("cameras.id"), primary_key=True)
    setting_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    desired_value_json: Mapped[object | None] = mapped_column(JSON)
    reported_value_json: Mapped[object | None] = mapped_column(JSON)
    sync_status: Mapped[str] = mapped_column(String(20), default="PENDING")
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class DeviceCommand(TenantScoped, Identity, Base):
    __tablename__ = "device_commands"
    __table_args__ = (
        ForeignKeyConstraint(
            ["camera_id", "tenant_id"],
            ["cameras.id", "cameras.tenant_id"],
            name="fk_command_camera_tenant",
        ),
        Index("ix_command_queue", "status", "created_at"),
        CheckConstraint(
            "status IN ('PENDING','RUNNING','SUCCEEDED','FAILED','TIMEOUT','CANCELLED')"
        ),
    )
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    camera_id: Mapped[str] = mapped_column(ForeignKey("cameras.id"), index=True)
    command: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    sanitized_error: Mapped[str | None] = mapped_column(String(300))
