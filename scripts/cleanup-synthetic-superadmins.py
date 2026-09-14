"""Remove accidental pytest superadmins while preserving the real local admin."""

from sqlalchemy import delete, select
from vigilay.db import system_session
from vigilay.models import AuditLog, LoginSession, PasswordReset, User, UserRole

ADMIN_EMAIL = "admin@vigilay.example.com"


def main():
    with system_session() as db:
        real = db.scalar(
            select(User).where(User.tenant_id.is_(None), User.email == ADMIN_EMAIL)
        )
        if real is None:
            raise RuntimeError("No se encontró el superadministrador real")
        synthetic_ids = list(
            db.scalars(
                select(User.id).where(
                    User.tenant_id.is_(None), User.id != real.id
                )
            )
        )
        if len(synthetic_ids) != 42:
            raise RuntimeError(
                f"Se esperaban 42 superadministradores sintéticos; encontrados: {len(synthetic_ids)}"
            )
        counts = {
            "audit_logs": db.execute(
                delete(AuditLog).where(AuditLog.actor_user_id.in_(synthetic_ids))
            ).rowcount,
            "password_reset_tokens": db.execute(
                delete(PasswordReset).where(PasswordReset.user_id.in_(synthetic_ids))
            ).rowcount,
            "sessions": db.execute(
                delete(LoginSession).where(LoginSession.user_id.in_(synthetic_ids))
            ).rowcount,
            "user_roles": db.execute(
                delete(UserRole).where(UserRole.user_id.in_(synthetic_ids))
            ).rowcount,
            "users": db.execute(delete(User).where(User.id.in_(synthetic_ids))).rowcount,
        }
        db.commit()
        print("Limpieza de administradores confirmada:")
        for table, count in counts.items():
            print(f"{table}={count}")
        print(f"administrador_real={real.email}")


if __name__ == "__main__":
    main()
