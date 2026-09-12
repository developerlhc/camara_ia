import argparse
import getpass
import os
import secrets
from datetime import timedelta

from sqlalchemy import select

from vigilay.db import system_session
from vigilay.models import AuditLog, PasswordReset, User, UserRole, utcnow
from vigilay.security import hash_token, hasher


def main():
    parser = argparse.ArgumentParser(prog="vigilay")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-superadmin", help="Crear superadministrador local")
    create.add_argument("--email", required=True)
    create.add_argument("--username", required=True)
    create.add_argument(
        "--password-env", help="Nombre de una variable para aprovisionamiento no interactivo"
    )
    reset = commands.add_parser(
        "issue-password-reset", help="Emitir token de recuperación de 15 minutos"
    )
    reset.add_argument("--email", required=True)
    args = parser.parse_args()
    with system_session() as db:
        existing = db.scalar(select(User).where(User.email == args.email.lower()))
        if args.command == "create-superadmin":
            if existing:
                parser.error("El usuario ya existe")
            from pydantic import EmailStr, TypeAdapter

            TypeAdapter(EmailStr).validate_python(args.email)
            password = (
                os.environ.get(args.password_env, "")
                if args.password_env
                else getpass.getpass("Contraseña (mínimo 12 caracteres): ")
            )
            confirmation = (
                password if args.password_env else getpass.getpass("Repite la contraseña: ")
            )
            if len(password) < 12 or len(password) > 256 or password != confirmation:
                parser.error("Contraseña inválida o confirmación diferente")
            user = User(
                email=args.email.lower(),
                username=args.username.lower(),
                first_name="Administrador",
                password_hash=hasher.hash(password),
            )
            db.add(user)
            db.flush()
            db.add(UserRole(user_id=user.id, role_name="SUPER_ADMIN"))
            db.add(
                AuditLog(
                    actor_user_id=user.id,
                    action="SUPER_ADMIN_CREATED",
                    resource_type="user",
                    resource_id=user.id,
                )
            )
            db.commit()
            print("Superadministrador creado.")
        elif args.command == "issue-password-reset":
            if existing is None:
                parser.error("Usuario no encontrado")
            for old in db.scalars(
                select(PasswordReset).where(
                    PasswordReset.user_id == existing.id,
                    PasswordReset.used_at.is_(None),
                )
            ):
                old.used_at = utcnow()
            token = secrets.token_urlsafe(48)
            db.add(
                PasswordReset(
                    user_id=existing.id,
                    token_hash=hash_token(token),
                    expires_at=utcnow() + timedelta(minutes=15),
                )
            )
            db.add(
                AuditLog(
                    tenant_id=existing.tenant_id,
                    action="PASSWORD_RESET_ISSUED",
                    resource_type="user",
                    resource_id=existing.id,
                )
            )
            db.commit()
            print("Token de un solo uso; entrégalo por un canal privado:")
            print(token)


if __name__ == "__main__":
    main()
