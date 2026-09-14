from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_, select

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
from vigilay.frigate import FrigateError, FrigateService
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
    PtzInput,
    SettingsInput,
    SiteInput,
    TenantInput,
    TenantUpdate,
    UserInput,
    UserUpdate,
)
from vigilay.security import encrypt_credentials, hasher

router = APIRouter(prefix="/api/v1", tags=["Administración"])


def paginated(db, stmt, serializer, *, paged, page, page_size, limit, offset):
    if not paged:
        return [serializer(row) for row in db.execute(stmt.limit(limit).offset(offset)).all()]
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.execute(stmt.limit(page_size).offset((page - 1) * page_size)).all()
    return {
        "items": [serializer(row) for row in rows],
        "total": total,
        "page": page,
        "pageSize": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
    }


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
        "brand": row.brand,
        "model": row.model,
        "frigate_camera_name": row.frigate_camera_name,
        "target_fps": row.target_fps,
        "grayscale": row.grayscale,
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
    paged: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=5, le=100),
    q: str = Query("", max_length=100),
    status: str | None = Query(None, pattern="^(ACTIVE|SUSPENDED)$"),
):
    stmt = select(Tenant).order_by(Tenant.name)
    if not actor.superadmin:
        stmt = stmt.where(Tenant.id == actor.tenant_id)
    if q:
        term = f"%{q}%"
        stmt = stmt.where(
            or_(Tenant.name.like(term), Tenant.legal_name.like(term), Tenant.tax_id.like(term))
        )
    if status:
        stmt = stmt.where(Tenant.status == status)
    return paginated(
        db,
        stmt,
        lambda row: tenant_dict(row[0]),
        paged=paged,
        page=page,
        page_size=page_size,
        limit=limit,
        offset=offset,
    )


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
    paged: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=5, le=100),
    q: str = Query("", max_length=100),
    tenant_id: str | None = None,
):
    stmt = select(Site).order_by(Site.name)
    if q:
        term = f"%{q}%"
        stmt = stmt.where(or_(Site.name.like(term), Site.address.like(term)))
    if tenant_id:
        authorize_tenant(actor, tenant_id)
        stmt = stmt.where(Site.tenant_id == tenant_id)
    return paginated(
        db,
        stmt,
        lambda row: site_dict(row[0]),
        paged=paged,
        page=page,
        page_size=page_size,
        limit=limit,
        offset=offset,
    )


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
    paged: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=5, le=100),
    q: str = Query("", max_length=100),
    tenant_id: str | None = None,
    status: str | None = Query(None, pattern="^(ACTIVE|DISABLED)$"),
    role: str | None = Query(None, pattern="^(CLIENT_ADMIN|OPERATOR|VIEWER)$"),
):
    stmt = (
        select(User, UserRole.role_name)
        .join(UserRole, UserRole.user_id == User.id)
        .order_by(User.email)
    )
    if q:
        term = f"%{q}%"
        stmt = stmt.where(
            or_(
                User.email.like(term),
                User.username.like(term),
                User.first_name.like(term),
                User.last_name.like(term),
            )
        )
    if tenant_id:
        authorize_tenant(actor, tenant_id)
        stmt = stmt.where(User.tenant_id == tenant_id)
    if status:
        stmt = stmt.where(User.status == status)
    if role:
        stmt = stmt.where(UserRole.role_name == role)
    return paginated(
        db,
        stmt,
        lambda row: public_user(row[0], row[1]),
        paged=paged,
        page=page,
        page_size=page_size,
        limit=limit,
        offset=offset,
    )


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
    paged: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=5, le=100),
    q: str = Query("", max_length=100),
    tenant_id: str | None = None,
):
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc())
    if q:
        term = f"%{q}%"
        stmt = stmt.where(
            or_(
                AuditLog.action.like(term),
                AuditLog.resource_type.like(term),
                AuditLog.resource_id.like(term),
            )
        )
    if tenant_id:
        authorize_tenant(actor, tenant_id)
        stmt = stmt.where(AuditLog.tenant_id == tenant_id)

    def serialize(row):
        r = row[0]
        return {
            "id": r.id,
            "tenant_id": r.tenant_id,
            "action": r.action,
            "resource_type": r.resource_type,
            "resource_id": r.resource_id,
            "created_at": r.created_at.isoformat() + "Z",
        }

    return paginated(
        db, stmt, serialize, paged=paged, page=page, page_size=page_size, limit=limit, offset=offset
    )


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
    paged: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=5, le=100),
    q: str = Query("", max_length=100),
    tenant_id: str | None = None,
    site_id: str | None = None,
    status: str | None = Query(None, pattern="^(ONLINE|OFFLINE|UNVERIFIED)$"),
    integration_type: str | None = Query(None, pattern="^(RTSP|V380|SIMULATOR)$"),
):
    stmt = camera_query(actor).order_by(Camera.name)
    if q:
        term = f"%{q}%"
        stmt = stmt.where(
            or_(Camera.name.like(term), Camera.brand.like(term), Camera.model.like(term))
        )
    if tenant_id:
        authorize_tenant(actor, tenant_id)
        stmt = stmt.where(Camera.tenant_id == tenant_id)
    if site_id:
        stmt = stmt.where(Camera.site_id == site_id)
    if status:
        stmt = stmt.where(Camera.status == status)
    if integration_type:
        stmt = stmt.where(Camera.integration_type == integration_type)
    return paginated(
        db,
        stmt,
        lambda row: camera_dict(row[0]),
        paged=paged,
        page=page,
        page_size=page_size,
        limit=limit,
        offset=offset,
    )


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
    if data.integration_type == "V380":
        if data.brand != "V380":
            raise HTTPException(422, "La integración V380 requiere la marca V380")
        if not all((data.host, data.port, data.username, data.password, data.device_id)):
            raise HTTPException(422, "Completa IP, puerto, ID, usuario y contraseña V380")
    if data.frigate_camera_name:
        try:
            frigate_names = FrigateService().camera_names()
        except FrigateError as exc:
            raise HTTPException(502, str(exc)) from exc
        if data.frigate_camera_name not in frigate_names:
            raise HTTPException(404, "La cámara indicada no existe en Frigate")
        assigned = db.scalar(
            select(Camera).where(
                Camera.site_id == data.site_id,
                Camera.frigate_camera_name == data.frigate_camera_name,
            )
        )
        if assigned is not None:
            raise HTTPException(409, "Esa cámara de Frigate ya está asignada en esta sede")
    row = Camera(
        tenant_id=data.tenant_id,
        site_id=data.site_id,
        name=data.name,
        integration_type=data.integration_type,
        brand=data.brand,
        model=data.model,
        frigate_camera_name=data.frigate_camera_name,
        target_fps=data.target_fps,
        grayscale=data.grayscale,
    )
    db.add(row)
    db.flush()
    credentials = None
    if uri:
        credentials = {"rtsp_url": uri}
    elif data.integration_type == "V380":
        credentials = {
            "host": data.host,
            "port": data.port,
            "username": data.username,
            "password": data.password.get_secret_value(),
            "device_id": data.device_id,
            "rtsp_port": 8555,
            "http_port": 8081,
        }
    if credentials:
        db.add(
            CameraCredential(
                tenant_id=row.tenant_id,
                camera_id=row.id,
                secret_encrypted=encrypt_credentials(credentials, row.tenant_id, row.id),
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
    grant.can_configure = data.can_configure
    grant.can_view = data.can_view or data.can_configure
    audit(db, actor, "CAMERA_ASSIGNED", "camera", camera.id, camera.tenant_id)
    db.commit()
    return {"ok": True}


@router.get("/cameras/{camera_id}/permissions")
def camera_permissions(
    camera_id: str,
    actor: Principal = Depends(require("cameras.manage")),
    db=Depends(database),
):
    camera = authorized_camera(db, actor, camera_id, configure=True)
    grants = {
        grant.user_id: grant
        for grant in db.scalars(
            select(CameraPermission).where(CameraPermission.camera_id == camera.id)
        )
    }
    return [
        {
            "user_id": user.id,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "can_view": bool(grants.get(user.id) and grants[user.id].can_view),
            "can_configure": bool(grants.get(user.id) and grants[user.id].can_configure),
        }
        for user in db.scalars(
            select(User)
            .join(UserRole, UserRole.user_id == User.id)
            .where(
                User.tenant_id == camera.tenant_id,
                User.status == "ACTIVE",
                UserRole.role_name.in_(["OPERATOR", "VIEWER"]),
            )
            .order_by(User.email)
        )
    ]


@router.post("/cameras/{camera_id}/ptz", status_code=202)
def camera_ptz(
    camera_id: str,
    data: PtzInput,
    actor: Principal = Depends(require("cameras.configure")),
    db=Depends(database),
):
    camera = authorized_camera(db, actor, camera_id, configure=True)
    if camera.integration_type == "SIMULATOR":
        raise HTTPException(409, "El simulador no ofrece control PTZ real")
    row = enqueue(db, actor, camera, "PTZ", data.model_dump())
    db.commit()
    return {"id": row.id, "status": row.status}


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
    if camera.integration_type != "SIMULATOR" and command not in {"PROBE", "PTZ"}:
        raise HTTPException(
            409,
            "Esta configuración todavía no está disponible para cámaras reales",
        )
    if camera.integration_type == "SIMULATOR" and not settings().enable_simulator:
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
