"""Restaura de forma idempotente el acceso a las tres cámaras de Cenfelec."""

from urllib.parse import urlsplit

from sqlalchemy import select
from vigilay.db import system_session
from vigilay.models import (
    AuditLog,
    Camera,
    CameraCredential,
    CameraPermission,
    Tenant,
    User,
    UserRole,
)
from vigilay.security import decrypt_credentials

EXPECTED_CAMERAS = {"EZVIZ principal", "Imou", "V380 Pro"}


def main() -> None:
    with system_session() as db:
        tenant = db.scalar(select(Tenant).where(Tenant.name == "Cenfelec"))
        if tenant is None:
            raise RuntimeError("No existe la empresa Cenfelec")

        cameras = list(
            db.scalars(
                select(Camera).where(
                    Camera.tenant_id == tenant.id,
                    Camera.name.in_(EXPECTED_CAMERAS),
                )
            )
        )
        found_names = {camera.name for camera in cameras}
        if found_names != EXPECTED_CAMERAS:
            missing = sorted(EXPECTED_CAMERAS - found_names)
            raise RuntimeError(f"Faltan cámaras de Cenfelec: {', '.join(missing)}")

        viewers = list(
            db.scalars(
                select(User)
                .join(UserRole, UserRole.user_id == User.id)
                .where(
                    User.tenant_id == tenant.id,
                    User.status == "ACTIVE",
                    UserRole.role_name.in_(["OPERATOR", "VIEWER"]),
                )
            )
        )
        if len(viewers) != 1:
            raise RuntimeError(
                "La restauración automática requiere exactamente un visor/operador activo "
                f"en Cenfelec; se encontraron {len(viewers)}"
            )

        user = viewers[0]
        restored: list[str] = []
        recorder_ready = 0
        for camera in cameras:
            credential = db.scalar(
                select(CameraCredential).where(CameraCredential.camera_id == camera.id)
            )
            if credential is None:
                raise RuntimeError(f"La cámara {camera.name} no conserva credenciales")
            secret = decrypt_credentials(
                credential.secret_encrypted, camera.tenant_id, camera.id
            )
            source = secret.get("rtsp_url", "")
            if not source and camera.integration_type == "V380":
                source = (
                    f"rtsp://127.0.0.1:{int(secret.get('rtsp_port', 8556))}/live"
                )
            parsed = urlsplit(source)
            if parsed.scheme not in {"rtsp", "rtsps", "http", "https"} or not parsed.hostname:
                raise RuntimeError(f"La cámara {camera.name} no tiene una fuente válida")
            recorder_ready += 1

            grant = db.get(CameraPermission, (user.id, camera.id))
            if grant is None:
                grant = CameraPermission(
                    tenant_id=tenant.id,
                    user_id=user.id,
                    camera_id=camera.id,
                    can_view=True,
                    can_configure=False,
                )
                db.add(grant)
                restored.append(camera.name)
            elif not grant.can_view:
                grant.can_view = True
                restored.append(camera.name)

        if restored:
            db.add(
                AuditLog(
                    tenant_id=tenant.id,
                    actor_user_id=None,
                    action="CAMERA_ACCESS_RESTORED",
                    resource_type="camera_permission",
                    resource_id=user.id,
                    metadata_json={
                        "source": "maintenance_script",
                        "username": user.username,
                        "cameras": sorted(restored),
                    },
                )
            )
        db.commit()
        print(
            f"Cenfelec: {user.username} tiene acceso de visualización a "
            f"{len(cameras)} cámaras; fuentes listas={recorder_ready}; "
            f"restauradas={','.join(sorted(restored)) or 'ninguna'}"
        )


if __name__ == "__main__":
    main()
