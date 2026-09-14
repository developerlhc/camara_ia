"""Remove the accidental pytest tenants from the configured development database."""

from sqlalchemy import delete, or_, select
from vigilay.db import system_session
from vigilay.models import (
    AuditLog,
    Camera,
    CameraCapability,
    CameraCredential,
    CameraPermission,
    CameraSetting,
    CameraStreamProvider,
    CameraStreamSession,
    DeviceCommand,
    LoginSession,
    NotificationChannel,
    PasswordReset,
    Site,
    Tenant,
    User,
    UserRole,
)


def main():
    with system_session() as db:
        synthetic_tenants = list(
            db.scalars(
                select(Tenant).where(
                    or_(
                        Tenant.name.like("Test A %"),
                        Tenant.name.like("Test B %"),
                        Tenant.name == "Suspendido",
                    )
                )
            )
        )
        if len(synthetic_tenants) != 84:
            raise RuntimeError(
                f"Se esperaban exactamente 84 clientes sintéticos; encontrados: {len(synthetic_tenants)}"
            )
        tenant_ids = [row.id for row in synthetic_tenants]
        user_ids = list(db.scalars(select(User.id).where(User.tenant_id.in_(tenant_ids))))

        counts = {}
        for model in (
            CameraStreamSession,
            CameraStreamProvider,
            DeviceCommand,
            CameraSetting,
            CameraCapability,
            CameraPermission,
            CameraCredential,
            Camera,
            NotificationChannel,
        ):
            counts[model.__tablename__] = db.execute(
                delete(model).where(model.tenant_id.in_(tenant_ids))
            ).rowcount

        counts["audit_logs"] = db.execute(
            delete(AuditLog).where(
                or_(AuditLog.tenant_id.in_(tenant_ids), AuditLog.actor_user_id.in_(user_ids))
            )
        ).rowcount
        for model in (PasswordReset, LoginSession):
            counts[model.__tablename__] = db.execute(
                delete(model).where(model.user_id.in_(user_ids))
            ).rowcount
        counts["user_roles"] = db.execute(
            delete(UserRole).where(UserRole.user_id.in_(user_ids))
        ).rowcount
        counts["users"] = db.execute(delete(User).where(User.id.in_(user_ids))).rowcount
        counts["sites"] = db.execute(delete(Site).where(Site.tenant_id.in_(tenant_ids))).rowcount
        counts["tenants"] = db.execute(delete(Tenant).where(Tenant.id.in_(tenant_ids))).rowcount

        real = list(db.scalars(select(Tenant).where(Tenant.name == "Vigilay local")))
        existing_cenfelec = db.scalar(select(Tenant).where(Tenant.name == "Cenfelec"))
        if len(real) != 1 or existing_cenfelec:
            raise RuntimeError("No se pudo identificar de forma inequívoca el cliente real")
        real[0].name = "Cenfelec"
        real[0].legal_name = "Cenfelec"
        db.commit()

        print("Limpieza confirmada:")
        for table, count in counts.items():
            print(f"{table}={count}")
        print(f"cliente_real={real[0].name}")


if __name__ == "__main__":
    main()
