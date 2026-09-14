"""Persistencia MySQL y ámbito de la instalación de Vigilay Local."""

import json
import sys
from pathlib import Path
from urllib.parse import quote, urlsplit
from uuid import uuid4

from sqlalchemy import func, select

BASE_DIR = Path(__file__).resolve().parent
API_SRC = BASE_DIR / "apps" / "api" / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))

from vigilay.db import system_session  # noqa: E402
from vigilay.models import (  # noqa: E402
    Camera,
    CameraCredential,
    FrigateConnection,
    NotificationChannel,
    Site,
    Tenant,
)
from vigilay.security import decrypt_credentials, encrypt_credentials  # noqa: E402

LOCAL_IDENTITY_PATH = BASE_DIR / ".local" / "vigilay-local.json"


def _read_local_identity():
    try:
        value = json.loads(LOCAL_IDENTITY_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_local_identity(*, tenant_id, site_id):
    current = _read_local_identity()
    value = {
        "installation_id": current.get("installation_id") or str(uuid4()),
        "tenant_id": tenant_id,
        "site_id": site_id,
    }
    LOCAL_IDENTITY_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = LOCAL_IDENTITY_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(LOCAL_IDENTITY_PATH)
    return value


def _validated_scope(db, tenant_id, site_id):
    tenant = db.get(Tenant, tenant_id) if tenant_id else None
    if tenant is None or tenant.status != "ACTIVE":
        raise ValueError("La empresa configurada no existe o no está activa.")
    site = db.get(Site, site_id) if site_id else None
    if site is None:
        raise ValueError("La sede configurada no existe.")
    if site.tenant_id != tenant.id:
        raise ValueError("La sede seleccionada no pertenece a la empresa.")
    return tenant, site


def get_local_scope(db, *, required=True):
    identity = _read_local_identity()
    if identity.get("tenant_id") and identity.get("site_id"):
        return _validated_scope(db, identity["tenant_id"], identity["site_id"])

    # Primera instalación: si sólo existe una combinación válida, se adopta sin
    # inventar ni duplicar registros. En cualquier otro caso el usuario debe elegir.
    rows = list(
        db.execute(
            select(Tenant, Site)
            .join(Site, Site.tenant_id == Tenant.id)
            .where(Tenant.status == "ACTIVE")
            .order_by(Tenant.name, Site.name)
            .limit(2)
        )
    )
    if len(rows) == 1:
        tenant, site = rows[0]
        _write_local_identity(tenant_id=tenant.id, site_id=site.id)
        return tenant, site
    if required:
        raise RuntimeError("Configura la empresa y la sede de esta instalación.")
    return None, None


def get_local_frigate_gateway_token():
    """Return only this installation's credential for local-to-cloud calls."""
    with system_session() as db:
        tenant, site = get_local_scope(db)
        connection = db.scalar(
            select(FrigateConnection).where(
                FrigateConnection.tenant_id == tenant.id,
                FrigateConnection.site_id == site.id,
            )
        )
        if connection is None or not connection.gateway_token_encrypted:
            raise RuntimeError("Inicia frigate-gateway para provisionar esta sede.")
        return decrypt_credentials(
            connection.gateway_token_encrypted, tenant.id, site.id
        )["gateway_token"]


def local_scope_catalog():
    with system_session() as db:
        identity = _read_local_identity()
        tenants = list(db.scalars(select(Tenant).order_by(Tenant.name)))
        sites = list(db.scalars(select(Site).order_by(Site.name)))
        configured = None
        if identity.get("tenant_id") and identity.get("site_id"):
            try:
                tenant, site = _validated_scope(db, identity["tenant_id"], identity["site_id"])
                configured = {
                    "installation_id": identity.get("installation_id"),
                    "tenant_id": tenant.id,
                    "tenant_name": tenant.name,
                    "site_id": site.id,
                    "site_name": site.name,
                }
            except ValueError:
                configured = None
        return {
            "configured": configured,
            "tenants": [
                {"id": row.id, "name": row.name, "status": row.status} for row in tenants
            ],
            "sites": [
                {"id": row.id, "tenant_id": row.tenant_id, "name": row.name, "address": row.address}
                for row in sites
            ],
        }


def configure_local_scope(*, tenant_id=None, tenant_name="", site_id=None, site_name="", address=""):
    tenant_name = tenant_name.strip()
    site_name = site_name.strip()
    with system_session() as db:
        if tenant_id:
            tenant = db.get(Tenant, tenant_id)
            if tenant is None:
                raise ValueError("La empresa seleccionada no existe.")
            if tenant.status != "ACTIVE":
                raise ValueError("La empresa seleccionada está suspendida.")
            if tenant_name:
                duplicate = db.scalar(
                    select(Tenant).where(
                        func.lower(Tenant.name) == tenant_name.lower(), Tenant.id != tenant.id
                    )
                )
                if duplicate:
                    raise ValueError("Ya existe otra empresa con ese nombre.")
                tenant.name = tenant_name
        else:
            if not tenant_name:
                raise ValueError("Indica el nombre de la empresa.")
            tenant = db.scalar(select(Tenant).where(func.lower(Tenant.name) == tenant_name.lower()))
            if tenant is None:
                tenant = Tenant(name=tenant_name, legal_name=tenant_name)
                db.add(tenant)
                db.flush()
            elif tenant.status != "ACTIVE":
                raise ValueError("La empresa ya existe, pero está suspendida.")

        if site_id:
            site = db.get(Site, site_id)
            if site is None:
                raise ValueError("La sede seleccionada no existe.")
            if site.tenant_id != tenant.id:
                raise ValueError("La sede seleccionada no pertenece a la empresa.")
            if site_name:
                duplicate = db.scalar(
                    select(Site).where(
                        Site.tenant_id == tenant.id,
                        func.lower(Site.name) == site_name.lower(),
                        Site.id != site.id,
                    )
                )
                if duplicate:
                    raise ValueError("Ya existe otra sede con ese nombre en la empresa.")
                site.name = site_name
            if address:
                site.address = address.strip()[:300]
        else:
            if not site_name:
                raise ValueError("Indica el nombre de la sede.")
            site = db.scalar(
                select(Site).where(
                    Site.tenant_id == tenant.id, func.lower(Site.name) == site_name.lower()
                )
            )
            if site is None:
                site = Site(
                    tenant_id=tenant.id,
                    name=site_name,
                    address=address.strip()[:300],
                    timezone=tenant.timezone,
                )
                db.add(site)
                db.flush()
        db.commit()
        identity = _write_local_identity(tenant_id=tenant.id, site_id=site.id)
        return {
            **identity,
            "tenant_name": tenant.name,
            "site_name": site.name,
            "address": site.address,
        }


def get_active_camera_id():
    with system_session() as db:
        tenant, _ = get_local_scope(db)
        return (tenant.settings_json or {}).get("active_camera_id")


def save_active_camera_id(camera_id):
    with system_session() as db:
        tenant, site = get_local_scope(db)
        camera = db.get(Camera, camera_id)
        if camera is None or camera.tenant_id != tenant.id or camera.site_id != site.id:
            raise ValueError("La cámara no pertenece a esta instalación.")
        settings_value = dict(tenant.settings_json or {})
        settings_value["active_camera_id"] = camera_id
        tenant.settings_json = settings_value
        db.commit()


def _runtime_camera(camera, secret):
    result = {
        "id": camera.id,
        "name": camera.name,
        "brand": camera.brand,
        "model": camera.model,
        "target_fps": camera.target_fps,
        "grayscale": camera.grayscale,
        "integration_type": camera.integration_type,
        "frigate_camera_name": camera.frigate_camera_name or "",
    }
    if camera.integration_type == "V380":
        result.update(secret)
        result["host"] = secret["host"]
        return result
    uri = secret["rtsp_url"]
    parsed = urlsplit(uri)
    result.update(
        {
            "host": parsed.hostname or "",
            "rtsp_url": uri,
            "username": parsed.username or "",
            "password": parsed.password or "",
            "onvif_port": int(secret.get("onvif_port", 80)),
        }
    )
    return result


def _validate_frigate_assignment(db, site_id, frigate_camera_name, *, camera_id=None):
    if not frigate_camera_name:
        return
    statement = select(Camera.id).where(
        Camera.site_id == site_id,
        Camera.frigate_camera_name == frigate_camera_name,
    )
    if camera_id:
        statement = statement.where(Camera.id != camera_id)
    if db.scalar(statement):
        raise ValueError("Esa cámara de Frigate ya está asignada en esta sede.")


def list_runtime_cameras():
    with system_session() as db:
        tenant, site = get_local_scope(db, required=False)
        if tenant is None or site is None:
            return []
        rows = list(
            db.scalars(
                select(Camera)
                .where(
                    Camera.tenant_id == tenant.id,
                    Camera.site_id == site.id,
                    Camera.enabled.is_(True),
                    Camera.integration_type.in_(["RTSP", "V380"]),
                )
                .order_by(Camera.created_at, Camera.name)
            )
        )
        credentials = {
            row.camera_id: row
            for row in db.scalars(
                select(CameraCredential).where(
                    CameraCredential.camera_id.in_([camera.id for camera in rows])
                )
            )
        } if rows else {}
        result = []
        for camera in rows:
            credential = credentials.get(camera.id)
            if credential is None:
                continue
            secret = decrypt_credentials(
                credential.secret_encrypted, camera.tenant_id, camera.id
            )
            result.append(_runtime_camera(camera, secret))
        return result


def save_camera(
    *,
    name,
    brand,
    model,
    integration_type,
    secret,
    frigate_camera_name=None,
    target_fps=10,
    grayscale=False,
):
    with system_session() as db:
        tenant, site = get_local_scope(db)
        _validate_frigate_assignment(db, site.id, frigate_camera_name)
        row = Camera(
            tenant_id=tenant.id,
            site_id=site.id,
            name=name,
            brand=brand,
            model=model,
            target_fps=target_fps,
            grayscale=grayscale,
            integration_type=integration_type,
            frigate_camera_name=frigate_camera_name or None,
        )
        db.add(row)
        db.flush()
        db.add(
            CameraCredential(
                tenant_id=tenant.id,
                camera_id=row.id,
                secret_encrypted=encrypt_credentials(secret, tenant.id, row.id),
            )
        )
        db.commit()
        return _runtime_camera(row, secret)


def get_runtime_camera(camera_id):
    """Obtiene una cámara con su secreto sólo para uso interno del servidor."""
    with system_session() as db:
        row = db.get(Camera, camera_id)
        if row is None:
            raise KeyError(camera_id)
        tenant, site = get_local_scope(db)
        if row.tenant_id != tenant.id or row.site_id != site.id:
            raise KeyError(camera_id)
        credential = db.scalar(
            select(CameraCredential).where(CameraCredential.camera_id == camera_id)
        )
        if credential is None:
            raise RuntimeError("La cámara no tiene credenciales almacenadas.")
        secret = decrypt_credentials(
            credential.secret_encrypted, row.tenant_id, row.id
        )
        return _runtime_camera(row, secret)


def get_notification_config(channel="WHATSAPP"):
    with system_session() as db:
        tenant, _ = get_local_scope(db)
        row = db.scalar(
            select(NotificationChannel).where(
                NotificationChannel.tenant_id == tenant.id,
                NotificationChannel.channel == channel,
            )
        )
        if row is None:
            return None
        if not row.enabled:
            return {"enabled": False}
        return {
            "enabled": True,
            **decrypt_credentials(row.config_encrypted, tenant.id, row.id),
        }


def save_notification_config(*, phone, url, message, channel="WHATSAPP"):
    with system_session() as db:
        tenant, _ = get_local_scope(db)
        row = db.scalar(
            select(NotificationChannel).where(
                NotificationChannel.tenant_id == tenant.id,
                NotificationChannel.channel == channel,
            )
        )
        if row is None:
            row = NotificationChannel(
                tenant_id=tenant.id,
                channel=channel,
                config_encrypted=b"",
                enabled=True,
            )
            db.add(row)
            db.flush()
        row.enabled = True
        row.config_encrypted = encrypt_credentials(
            {"phone": phone, "url": url, "message": message}, tenant.id, row.id
        )
        db.commit()


def set_notification_enabled(enabled, channel="WHATSAPP"):
    with system_session() as db:
        tenant, _ = get_local_scope(db)
        row = db.scalar(
            select(NotificationChannel).where(
                NotificationChannel.tenant_id == tenant.id,
                NotificationChannel.channel == channel,
            )
        )
        if row is not None:
            row.enabled = bool(enabled)
            db.commit()
        return row is not None


def update_camera(
    camera_id,
    *,
    name,
    model,
    secret=None,
    frigate_camera_name=None,
    target_fps=None,
    grayscale=None,
):
    with system_session() as db:
        row = db.get(Camera, camera_id)
        if row is None:
            raise KeyError(camera_id)
        tenant, site = get_local_scope(db)
        if row.tenant_id != tenant.id or row.site_id != site.id:
            raise KeyError(camera_id)
        _validate_frigate_assignment(
            db, site.id, frigate_camera_name, camera_id=camera_id
        )
        row.name = name
        row.model = model
        row.frigate_camera_name = frigate_camera_name or None
        if target_fps is not None:
            row.target_fps = target_fps
        if grayscale is not None:
            row.grayscale = grayscale
        if secret is not None:
            credential = db.scalar(
                select(CameraCredential).where(CameraCredential.camera_id == camera_id)
            )
            if credential is None:
                raise RuntimeError("La cámara no tiene credenciales almacenadas.")
            credential.secret_encrypted = encrypt_credentials(
                secret, row.tenant_id, row.id
            )
        db.commit()
        if secret is None:
            credential = db.scalar(
                select(CameraCredential).where(CameraCredential.camera_id == camera_id)
            )
            secret = decrypt_credentials(
                credential.secret_encrypted, row.tenant_id, row.id
            )
        return _runtime_camera(row, secret)


def migrate_environment_cameras(values):
    """Importa una sola vez las cámaras antiguas; nunca imprime secretos."""
    with system_session() as db:
        tenant, site = get_local_scope(db)
        existing = {
            (row.brand, row.name)
            for row in db.scalars(
                select(Camera).where(Camera.tenant_id == tenant.id, Camera.site_id == site.id)
            )
        }
        candidates = []
        first_uri = values.get("RTSP_URL", "")
        if first_uri:
            candidates.append(
                (
                    values.get("CAMERA_NAME", "EZVIZ principal"),
                    values.get("CAMERA_BRAND", "EZVIZ").upper(),
                    values.get("CAMERA_MODEL", ""),
                    "RTSP",
                    {"rtsp_url": first_uri, "onvif_port": int(values.get("CAMERA_ONVIF_PORT", 80))},
                )
            )
        for index in range(2, 9):
            uri = values.get(f"CAMERA_{index}_RTSP_URL", "")
            if uri:
                candidates.append(
                    (
                        values.get(f"CAMERA_{index}_NAME", f"Cámara {index}"),
                        values.get(f"CAMERA_{index}_BRAND", "GENERIC").split("/")[0].strip().upper(),
                        values.get(f"CAMERA_{index}_MODEL", ""),
                        "RTSP",
                        {"rtsp_url": uri, "onvif_port": int(values.get(f"CAMERA_{index}_ONVIF_PORT", 80))},
                    )
                )
        if values.get("V380_ENABLED") == "1" and values.get("V380_PASSWORD"):
            candidates.append(
                (
                    values.get("V380_CAMERA_NAME", "V380 Pro"),
                    "V380",
                    values.get("V380_MODEL", "HsAKTQWQ"),
                    "V380",
                    {
                        "device_id": values["V380_DEVICE_ID"],
                        "username": values["V380_USERNAME"],
                        "password": values["V380_PASSWORD"],
                        "host": values["V380_IP"],
                        "port": int(values.get("V380_PORT", 8800)),
                        "quality": values.get("V380_QUALITY", "sd"),
                        "rtsp_port": int(values.get("V380_RTSP_PORT", 8555)),
                        "http_port": int(values.get("V380_HTTP_PORT", 8081)),
                    },
                )
            )
        imported = 0
        for name, brand, model, integration_type, secret in candidates:
            brand = "IMOU" if brand == "IMOU" else brand
            if (brand, name) in existing:
                continue
            row = Camera(
                tenant_id=tenant.id,
                site_id=site.id,
                name=name,
                brand=brand,
                model=model,
                integration_type=integration_type,
            )
            db.add(row)
            db.flush()
            db.add(
                CameraCredential(
                    tenant_id=tenant.id,
                    camera_id=row.id,
                    secret_encrypted=encrypt_credentials(secret, tenant.id, row.id),
                )
            )
            existing.add((brand, name))
            imported += 1
        db.commit()
        return imported


def rtsp_secret(host, username, password, path, onvif_port=80):
    path = path.strip()
    if not path.startswith("/"):
        path = "/" + path
    uri = (
        f"rtsp://{quote(username, safe='')}:{quote(password, safe='')}"
        f"@{host}:554{path}"
    )
    return {"rtsp_url": uri, "onvif_port": int(onvif_port)}
