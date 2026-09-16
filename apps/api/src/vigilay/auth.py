import hmac
import ipaddress
import secrets
from dataclasses import dataclass
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import or_, select

from vigilay.config import settings
from vigilay.db import system_session, tenant_session
from vigilay.models import (
    AuditLog,
    LoginAttempt,
    LoginSession,
    PasswordReset,
    RateLimitBucket,
    RolePermission,
    Tenant,
    User,
    UserRole,
    utcnow,
)
from vigilay.schemas import LoginInput, PasswordChange, PasswordResetInput
from vigilay.security import DUMMY_HASH, csrf_token, hash_token, hasher, verify_password

router = APIRouter(prefix="/api/v1", tags=["Autenticación"])


@dataclass(frozen=True)
class Principal:
    id: str
    tenant_id: str | None
    email: str
    first_name: str
    role: str
    permissions: frozenset[str]
    session_id: str

    @property
    def superadmin(self):
        return self.role == "SUPER_ADMIN" and self.tenant_id is None


def client_ip(request: Request):
    proxy_secret = settings().internal_proxy_secret
    if proxy_secret and hmac.compare_digest(
        proxy_secret, request.headers.get("x-vigilay-proxy-key", "")
    ):
        try:
            return str(ipaddress.ip_address(request.headers.get("x-vigilay-client-ip", "")))
        except ValueError:
            pass
    return request.client.host if request.client else "unknown"


def rate_limit(request: Request, bucket: str, limit: int, seconds: int):
    # Durable and shared across API replicas. Never trust arbitrary X-Forwarded-For.
    ip = client_ip(request)
    key = hash_token(f"{bucket}:{ip}")
    now = utcnow()
    with system_session() as db:
        row = db.scalar(
            select(RateLimitBucket).where(RateLimitBucket.bucket_key == key).with_for_update()
        )
        if row is None:
            row = RateLimitBucket(
                bucket_key=key,
                request_count=1,
                expires_at=now + timedelta(seconds=seconds),
            )
            db.add(row)
            count = 1
        elif row.expires_at <= now:
            row.request_count = 1
            row.expires_at = now + timedelta(seconds=seconds)
            count = 1
        else:
            row.request_count += 1
            count = row.request_count
        db.commit()
    if count > limit:
        raise HTTPException(
            429, "Demasiados intentos. Inténtalo más tarde.", headers={"Retry-After": str(seconds)}
        )


def principal_from_token(token: str):
    if not token or len(token) > 256:
        raise HTTPException(401, "Inicia sesión para continuar")
    with system_session() as db:
        # One round trip instead of 4–5 sequential reads on the remote database.
        # Do not cache authorization: revocations and tenant suspension remain immediate.
        rows = db.execute(
            select(LoginSession, User, UserRole, Tenant, RolePermission.permission_key)
            .outerjoin(User, User.id == LoginSession.user_id)
            .outerjoin(UserRole, UserRole.user_id == User.id)
            .outerjoin(Tenant, Tenant.id == User.tenant_id)
            .outerjoin(RolePermission, RolePermission.role_name == UserRole.role_name)
            .where(
                LoginSession.token_hash == hash_token(token),
                LoginSession.revoked_at.is_(None),
                LoginSession.expires_at > utcnow(),
            )
        ).all()
        if not rows:
            raise HTTPException(401, "La sesión ha expirado")
        session, user, role, tenant, _ = rows[0]
        if user is None or user.status != "ACTIVE" or role is None:
            raise HTTPException(401, "Cuenta no disponible")
        if role.tenant_id != user.tenant_id or session.tenant_id != user.tenant_id:
            raise HTTPException(403, "Asignación de cliente inválida")
        if (role.role_name == "SUPER_ADMIN") != (user.tenant_id is None):
            raise HTTPException(403, "Asignación de rol inválida")
        if user.tenant_id:
            if tenant is None or tenant.status != "ACTIVE":
                raise HTTPException(403, "Cliente suspendido")
        permissions = frozenset(row[4] for row in rows if row[4] is not None)
        return Principal(
            user.id,
            user.tenant_id,
            user.email,
            user.first_name,
            role.role_name,
            permissions,
            session.id,
        )


def principal(request: Request):
    actor = principal_from_token(request.cookies.get(settings().session_cookie_name, ""))
    token = request.cookies[settings().session_cookie_name]
    if request.method not in {"GET", "HEAD", "OPTIONS"} and not hmac.compare_digest(
        request.headers.get("x-csrf-token", ""), csrf_token(token)
    ):
        raise HTTPException(403, "Token CSRF inválido")
    return actor


def require(permission):
    def check(actor: Principal = Depends(principal)):
        if permission not in actor.permissions:
            raise HTTPException(403, "No tienes permiso para esta acción")
        return actor

    return check


def database(actor: Principal = Depends(principal)):
    with tenant_session(actor.tenant_id, superadmin=actor.superadmin) as db:
        yield db


def audit(db, actor, action, resource_type, resource_id, tenant_id=None, request=None):
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_user_id=actor.id if actor else None,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address=request.client.host if request and request.client else "",
            user_agent=request.headers.get("user-agent", "")[:300] if request else "",
        )
    )


def public_user(user, role):
    return {
        "id": user.id,
        "tenant_id": user.tenant_id,
        "email": user.email,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "status": user.status,
        "role": role,
    }


def revoke_user_sessions(db, user_id):
    for session in db.scalars(
        select(LoginSession).where(
            LoginSession.user_id == user_id,
            LoginSession.revoked_at.is_(None),
        )
    ):
        session.revoked_at = utcnow()


@router.post("/auth/login")
def login(data: LoginInput, request: Request, response: Response):
    rate_limit(request, "login", 30, 900)
    identifier = data.identifier.lower()
    with system_session() as db:
        user = db.scalar(
            select(User)
            .where(
                or_(
                    User.email == identifier,
                    User.username == identifier,
                )
            )
            .with_for_update()
        )
        password_ok = verify_password(
            user.password_hash if user else DUMMY_HASH, data.password.get_secret_value()
        )
        now = utcnow()
        allowed = user is not None and password_ok and user.status == "ACTIVE"
        if user and user.locked_until and user.locked_until > now:
            allowed = False
        if user and user.tenant_id:
            tenant = db.get(Tenant, user.tenant_id)
            allowed = allowed and tenant is not None and tenant.status == "ACTIVE"
        db.add(
            LoginAttempt(
                username_or_email_hash=hash_token(identifier),
                ip_address=request.client.host,
                successful=bool(allowed),
            )
        )
        if not allowed:
            if user:
                user.failed_login_count += 1
                if user.failed_login_count >= 5:
                    user.locked_until = now + timedelta(minutes=15)
            audit(db, None, "LOGIN_FAILED", "user", None, user.tenant_id if user else None, request)
            db.commit()
            raise HTTPException(401, "Credenciales inválidas o cuenta temporalmente bloqueada")
        role = db.get(UserRole, user.id)
        if role is None or (role.role_name == "SUPER_ADMIN") != (user.tenant_id is None):
            raise HTTPException(403, "Asignación de rol inválida")
        previous = request.cookies.get(settings().session_cookie_name)
        if previous:
            old = db.scalar(
                select(LoginSession).where(LoginSession.token_hash == hash_token(previous))
            )
            if old:
                old.revoked_at = now
        token = secrets.token_urlsafe(48)
        db.add(
            LoginSession(
                tenant_id=user.tenant_id,
                user_id=user.id,
                token_hash=hash_token(token),
                ip_address=request.client.host,
                user_agent=request.headers.get("user-agent", "")[:300],
                expires_at=now + timedelta(seconds=settings().session_ttl_seconds),
            )
        )
        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = now
        audit(db, user, "LOGIN", "user", user.id, user.tenant_id, request)
        db.commit()
        response.set_cookie(
            settings().session_cookie_name,
            token,
            httponly=True,
            secure=settings().session_cookie_secure,
            samesite="lax",
            path="/",
            max_age=settings().session_ttl_seconds,
        )
        return {"user": public_user(user, role.role_name), "csrf_token": csrf_token(token)}


@router.get("/me")
def me(request: Request, actor: Principal = Depends(principal)):
    return {
        "id": actor.id,
        "tenant_id": actor.tenant_id,
        "email": actor.email,
        "first_name": actor.first_name,
        "role": actor.role,
        "permissions": sorted(actor.permissions),
        "csrf_token": csrf_token(request.cookies[settings().session_cookie_name]),
    }


@router.post("/auth/logout", status_code=204)
def logout(response: Response, actor: Principal = Depends(principal), db=Depends(database)):
    db.get(LoginSession, actor.session_id).revoked_at = utcnow()
    audit(db, actor, "LOGOUT", "user", actor.id, actor.tenant_id)
    db.commit()
    response.delete_cookie(settings().session_cookie_name, path="/")


@router.post("/auth/change-password", status_code=204)
def change_password(
    data: PasswordChange, actor: Principal = Depends(principal), db=Depends(database)
):
    user = db.get(User, actor.id)
    if not verify_password(user.password_hash, data.current_password.get_secret_value()):
        raise HTTPException(400, "La contraseña actual no es correcta")
    user.password_hash = hasher.hash(data.new_password.get_secret_value())
    revoke_user_sessions(db, user.id)
    audit(db, actor, "PASSWORD_CHANGED", "user", user.id, user.tenant_id)
    db.commit()


@router.post("/auth/reset-password", status_code=204)
def reset_password(data: PasswordResetInput, request: Request):
    rate_limit(request, "reset", 10, 900)
    with system_session() as db:
        token = db.scalar(
            select(PasswordReset)
            .where(
                PasswordReset.token_hash == hash_token(data.token.get_secret_value()),
                PasswordReset.used_at.is_(None),
                PasswordReset.expires_at > utcnow(),
            )
            .with_for_update()
        )
        if token is None:
            raise HTTPException(400, "Enlace inválido o caducado")
        user = db.get(User, token.user_id)
        user.password_hash = hasher.hash(data.new_password.get_secret_value())
        user.failed_login_count = 0
        user.locked_until = None
        token.used_at = utcnow()
        revoke_user_sessions(db, user.id)
        audit(db, user, "PASSWORD_RESET", "user", user.id, user.tenant_id, request)
        db.commit()
