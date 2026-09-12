from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select

from vigilay.auth import (
    Principal,
    audit,
    database,
    principal,
    public_user,
    require,
    revoke_user_sessions,
)
from vigilay.config import settings
from vigilay.models import (
    AuditLog,
    Camera,
    CameraCapability,
    CameraCredential,
    CameraPermission,
    CameraSetting,
    DeviceCommand,
    Role,
    Site,
    Tenant,
    User,
    UserRole,
)
from vigilay.schemas import (
    CameraInput,
    PermissionInput,
    SettingsInput,
    SiteInput,
    TenantInput,
    TenantUpdate,
    UserInput,
    UserUpdate,
)
from vigilay.security import encrypt_credentials, hasher

router = APIRouter(prefix="/api/v1", tags=["Administración"])


def found(db, model, identifier):
    row = db.get(model, identifier)
    if row is None:
        raise HTTPException(404, "Recurso no encontrado")
    return row


def authorize_tenant(actor, tenant_id):
    if not actor.superadmin and actor.tenant_id != tenant_id:
        raise HTTPException(404, "Recurso no encontrado")


def tenant_dict(row):
    return {
        "id": row.id,
        "name": row.name,
        "legal_name": row.legal_name,
        "tax_id": row.tax_id,
        "timezone": row.timezone,
        "status": row.status,
    }


def site_dict(row):
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "name": row.name,
        "address": row.address,
        "description": row.description,
        "timezone": row.timezone,
    }


def camera_dict(row):
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "site_id": row.site_id,
        "name": row.name,
        "integration_type": row.integration_type,
        "status": row.status,
        "enabled": row.enabled,
        "ai_enabled": row.ai_enabled,
    }


def camera_query(actor):
    stmt = select(Camera)
    if actor.role not in {"SUPER_ADMIN", "CLIENT_ADMIN"}:
        stmt = stmt.where(
            Camera.id.in_(
                select(CameraPermission.camera_id).where(
                    CameraPermission.user_id == actor.id,
                    CameraPermission.can_view.is_(True),
                )
            )
        )
    return stmt


def authorized_camera(db, actor, camera_id, *, configure=False):
    row = db.scalar(camera_query(actor).where(Camera.id == camera_id))
    if row is None:
        raise HTTPException(404, "Cámara no encontrada")
    if configure and actor.role not in {"SUPER_ADMIN", "CLIENT_ADMIN"}:
        grant = db.get(CameraPermission, (actor.id, camera_id))
        if grant is None or not grant.can_configure:
            raise HTTPException(403, "No tienes permiso para configurar esta cámara")
    return row


@router.get("/tenants")
def tenants(
    actor: Principal = Depends(principal),
    db=Depends(database),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    stmt = select(Tenant).order_by(Tenant.name)
    if not actor.superadmin:
        stmt = stmt.where(Tenant.id == actor.tenant_id)
    return [tenant_dict(row) for row in db.scalars(stmt.limit(limit).offset(offset))]


@router.post("/tenants", status_code=201)
def create_tenant(
    data: TenantInput,
    request: Request,
    actor: Principal = Depends(require("tenants.manage")),
    db=Depends(database),
):
    row = Tenant(**data.model_dump())
    db.add(row)
    db.flush()
    audit(db, actor, "TENANT_CREATED", "tenant", row.id, row.id, request)
    db.commit()
    return tenant_dict(row)


@router.get("/tenants/{tenant_id}")
def get_tenant(tenant_id: str, actor: Principal = Depends(principal), db=Depends(database)):
    authorize_tenant(actor, tenant_id)
    return tenant_dict(found(db, Tenant, tenant_id))


@router.put("/tenants/{tenant_id}")
def update_tenant(
    tenant_id: str,
    data: TenantUpdate,
    actor: Principal = Depends(require("tenants.manage")),
    db=Depends(database),
):
    row = found(db, Tenant, tenant_id)
    for key, value in data.model_dump().items():
        setattr(row, key, value)
    audit(db, actor, "TENANT_UPDATED", "tenant", row.id, row.id)
    db.commit()
    return tenant_dict(row)


@router.get("/sites")
def sites(
    actor: Principal = Depends(principal),
    db=Depends(database),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    return [
        site_dict(row)
        for row in db.scalars(select(Site).order_by(Site.name).limit(limit).offset(offset))
    ]


@router.get("/sites/{site_id}")
def get_site(site_id: str, actor: Principal = Depends(principal), db=Depends(database)):
    return site_dict(found(db, Site, site_id))


@router.post("/sites", status_code=201)
def create_site(
    data: SiteInput, actor: Principal = Depends(require("sites.manage")), db=Depends(database)
):
    authorize_tenant(actor, data.tenant_id)
    tenant = found(db, Tenant, data.tenant_id)
    row = Site(**data.model_dump(), timezone=tenant.timezone)
    db.add(row)
    db.flush()
    audit(db, actor, "SITE_CREATED", "site", row.id, row.tenant_id)
    db.commit()
    return site_dict(row)


@router.put("/sites/{site_id}")
def update_site(
    site_id: str,
    data: SiteInput,
    actor: Principal = Depends(require("sites.manage")),
    db=Depends(database),
):
    row = found(db, Site, site_id)
    if data.tenant_id != row.tenant_id:
        raise HTTPException(400, "No se permite trasladar una sede entre clientes")
    for key, value in data.model_dump().items():
        setattr(row, key, value)
    audit(db, actor, "SITE_UPDATED", "site", row.id, row.tenant_id)
    db.commit()
    return site_dict(row)


@router.get("/users")
def users(
    actor: Principal = Depends(require("users.manage")),
    db=Depends(database),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    rows = db.execute(
        select(User, UserRole.role_name)
        .join(UserRole, UserRole.user_id == User.id)
        .order_by(User.email)
        .limit(limit)
        .offset(offset)
    )
    return [public_user(user, role) for user, role in rows]


@router.post("/users", status_code=201)
def create_user(
    data: UserInput, actor: Principal = Depends(require("users.manage")), db=Depends(database)
):
    authorize_tenant(actor, data.tenant_id)
    found(db, Tenant, data.tenant_id)
    row = User(
        tenant_id=data.tenant_id,
        email=str(data.email).lower(),
        username=data.username.lower(),
        first_name=data.first_name,
        last_name=data.last_name,
        password_hash=hasher.hash(data.password.get_secret_value()),
    )
    db.add(row)
    db.flush()
    db.add(UserRole(tenant_id=row.tenant_id, user_id=row.id, role_name=data.role))
    audit(db, actor, "USER_CREATED", "user", row.id, row.tenant_id)
    db.commit()
    return public_user(row, data.role)


@router.put("/users/{user_id}")
def update_user(
    user_id: str,
    data: UserUpdate,
    actor: Principal = Depends(require("users.manage")),
    db=Depends(database),
):
    row = found(db, User, user_id)
    if row.tenant_id is None or row.id == actor.id:
        raise HTTPException(400, "Utiliza tu perfil; los superadministradores se gestionan por CLI")
    role = found(db, UserRole, user_id)
    row.first_name, row.last_name, row.status = data.first_name, data.last_name, data.status
    role.role_name = data.role
    revoke_user_sessions(db, row.id)
    audit(db, actor, "USER_UPDATED", "user", row.id, row.tenant_id)
    db.commit()
    return public_user(row, data.role)


@router.get("/roles")
def roles(actor: Principal = Depends(require("users.manage")), db=Depends(database)):
    stmt = select(Role)
    if not actor.superadmin:
        stmt = stmt.where(Role.scope == "TENANT")
    return [
        {"name": r.name, "scope": r.scope, "description": r.description} for r in db.scalars(stmt)
    ]


@router.get("/audit")
def audit_logs(
    actor: Principal = Depends(require("audit.read")),
    db=Depends(database),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    return [
        {
            "id": r.id,
            "tenant_id": r.tenant_id,
            "action": r.action,
            "resource_type": r.resource_type,
            "resource_id": r.resource_id,
            "created_at": r.created_at.isoformat() + "Z",
        }
        for r in db.scalars(
            select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
        )
    ]


@router.get("/dashboard")
def dashboard(actor: Principal = Depends(principal), db=Depends(database)):
    tenant_count = db.scalar(select(func.count()).select_from(Tenant)) if actor.superadmin else 1
    cameras = list(db.scalars(camera_query(actor)))
    return {
        "tenants": tenant_count,
        "sites": db.scalar(select(func.count()).select_from(Site)),
        "cameras": len(cameras),
        "cameras_online": sum(c.status == "ONLINE" for c in cameras),
        "cameras_unverified": sum(c.status == "UNVERIFIED" for c in cameras),
        "cameras_offline": sum(c.status == "OFFLINE" for c in cameras),
    }


@router.get("/cameras")
def cameras(
    actor: Principal = Depends(require("cameras.read")),
    db=Depends(database),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    return [
        camera_dict(row)
        for row in db.scalars(camera_query(actor).order_by(Camera.name).limit(limit).offset(offset))
    ]


@router.get("/cameras/{camera_id}")
def get_camera(
    camera_id: str, actor: Principal = Depends(require("cameras.read")), db=Depends(database)
):
    return camera_dict(authorized_camera(db, actor, camera_id))


@router.post("/cameras", status_code=201)
def create_camera(
    data: CameraInput, actor: Principal = Depends(require("cameras.manage")), db=Depends(database)
):
    authorize_tenant(actor, data.tenant_id)
    site = found(db, Site, data.site_id)
    if site.tenant_id != data.tenant_id:
        raise HTTPException(404, "Sede no encontrada")
    if data.integration_type == "SIMULATOR" and not settings().enable_simulator:
        raise HTTPException(400, "El simulador está deshabilitado en este entorno")
    uri = data.rtsp_url.get_secret_value() if data.rtsp_url else ""
    if data.integration_type == "RTSP":
        try:
            parsed = urlsplit(uri)
            valid = parsed.scheme in {"rtsp", "rtsps"} and parsed.hostname and parsed.port != 0
        except ValueError:
            valid = False
        if not valid:
            raise HTTPException(422, "Introduce una URL RTSP válida")
    row = Camera(
        tenant_id=data.tenant_id,
        site_id=data.site_id,
        name=data.name,
        integration_type=data.integration_type,
    )
    db.add(row)
    db.flush()
    if uri:
        db.add(
            CameraCredential(
                tenant_id=row.tenant_id,
                camera_id=row.id,
                secret_encrypted=encrypt_credentials({"rtsp_url": uri}, row.tenant_id, row.id),
            )
        )
    audit(db, actor, "CAMERA_CREATED", "camera", row.id, row.tenant_id)
    db.commit()
    return camera_dict(row)


@router.put("/cameras/{camera_id}/permissions")
def assign_camera(
    camera_id: str,
    data: PermissionInput,
    actor: Principal = Depends(require("cameras.manage")),
    db=Depends(database),
):
    camera = authorized_camera(db, actor, camera_id, configure=True)
    user = found(db, User, data.user_id)
    if user.tenant_id != camera.tenant_id:
        raise HTTPException(404, "Usuario no encontrado")
    grant = db.get(CameraPermission, (user.id, camera.id))
    if grant is None:
        grant = CameraPermission(tenant_id=camera.tenant_id, user_id=user.id, camera_id=camera.id)
        db.add(grant)
    grant.can_view, grant.can_configure = data.can_view, data.can_configure
    audit(db, actor, "CAMERA_ASSIGNED", "camera", camera.id, camera.tenant_id)
    db.commit()
    return {"ok": True}


@router.get("/cameras/{camera_id}/capabilities")
def capabilities(
    camera_id: str, actor: Principal = Depends(require("cameras.read")), db=Depends(database)
):
    camera = authorized_camera(db, actor, camera_id)
    return [
        {
            "key": c.capability_key,
            "supported": c.supported,
            "readable": c.readable,
            "writable": c.writable,
            "metadata": c.metadata_json,
        }
        for c in db.scalars(select(CameraCapability).where(CameraCapability.camera_id == camera.id))
    ]


def enqueue(db, actor, camera, command, payload):
    if camera.integration_type != "SIMULATOR":
        raise HTTPException(
            409,
            "Esta cámara requiere un Edge Agent; la conexión real está pendiente de integración",
        )
    if not settings().enable_simulator:
        raise HTTPException(409, "Simulador deshabilitado")
    # Serialize enqueue operations per camera so a newer desired value cannot be overwritten.
    db.scalar(select(Camera).where(Camera.id == camera.id).with_for_update())
    pending = db.scalar(
        select(DeviceCommand.id).where(
            DeviceCommand.camera_id == camera.id,
            DeviceCommand.status.in_(["PENDING", "RUNNING"]),
        )
    )
    if pending:
        raise HTTPException(409, "La cámara ya tiene un comando pendiente")
    row = DeviceCommand(
        tenant_id=camera.tenant_id,
        camera_id=camera.id,
        command=command,
        payload_json=payload,
        requested_by=actor.id,
    )
    db.add(row)
    db.flush()
    audit(db, actor, "CAMERA_COMMAND_CREATED", "command", row.id, camera.tenant_id)
    return row


@router.post("/cameras/{camera_id}/probe", status_code=202)
@router.post("/cameras/{camera_id}/test", status_code=202)
def probe(
    camera_id: str, actor: Principal = Depends(require("cameras.configure")), db=Depends(database)
):
    camera = authorized_camera(db, actor, camera_id, configure=True)
    row = enqueue(db, actor, camera, "PROBE", {})
    db.commit()
    return {"id": row.id, "status": row.status}


@router.get("/cameras/{camera_id}/settings")
def get_settings(
    camera_id: str, actor: Principal = Depends(require("cameras.configure")), db=Depends(database)
):
    camera = authorized_camera(db, actor, camera_id, configure=True)
    return [
        {
            "key": s.setting_key,
            "desired": s.desired_value_json,
            "reported": s.reported_value_json,
            "status": s.sync_status,
        }
        for s in db.scalars(select(CameraSetting).where(CameraSetting.camera_id == camera.id))
    ]


@router.put("/cameras/{camera_id}/settings", status_code=202)
def set_settings(
    camera_id: str,
    data: SettingsInput,
    actor: Principal = Depends(require("cameras.configure")),
    db=Depends(database),
):
    camera = authorized_camera(db, actor, camera_id, configure=True)
    capability = db.get(CameraCapability, (camera.id, "motion_sensitivity"))
    if not capability or not capability.supported or not capability.writable:
        raise HTTPException(409, "La cámara no declara esta capacidad de escritura")
    row = enqueue(db, actor, camera, "APPLY_SETTINGS", data.model_dump())
    setting = db.get(CameraSetting, (camera.id, "motion_sensitivity"))
    if setting is None:
        setting = CameraSetting(
            tenant_id=camera.tenant_id, camera_id=camera.id, setting_key="motion_sensitivity"
        )
        db.add(setting)
    setting.desired_value_json = data.motion_sensitivity
    setting.sync_status = "PENDING"
    setting.updated_by = actor.id
    audit(db, actor, "CAMERA_SETTING_CHANGED", "camera", camera.id, camera.tenant_id)
    db.commit()
    return {"id": row.id, "status": row.status}


@router.get("/cameras/{camera_id}/commands")
def commands(
    camera_id: str, actor: Principal = Depends(require("cameras.configure")), db=Depends(database)
):
    camera = authorized_camera(db, actor, camera_id, configure=True)
    return [
        {
            "id": c.id,
            "command": c.command,
            "status": c.status,
            "error": c.sanitized_error,
            "created_at": c.created_at.isoformat() + "Z",
        }
        for c in db.scalars(
            select(DeviceCommand)
            .where(DeviceCommand.camera_id == camera.id)
            .order_by(DeviceCommand.created_at.desc())
            .limit(50)
        )
    ]
