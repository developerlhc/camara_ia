"""Ejecuta una sesión breve de diagnóstico para una cámara de Cenfelec."""

from __future__ import annotations

import secrets
import sys
import time

from sqlalchemy import select
from vigilay.db import system_session
from vigilay.models import Camera, CameraStreamSession, Tenant, User, utcnow
from vigilay.security import hash_token


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Uso: test-live-pipeline.py <nombre-camara>")
    camera_name = sys.argv[1]
    session_id: str | None = None
    try:
        with system_session() as db:
            tenant = db.scalar(select(Tenant).where(Tenant.name == "Cenfelec"))
            if tenant is None:
                raise RuntimeError("No existe la empresa Cenfelec")
            camera = db.scalar(
                select(Camera).where(
                    Camera.tenant_id == tenant.id, Camera.name == camera_name
                )
            )
            user = db.scalar(
                select(User).where(
                    User.tenant_id == tenant.id, User.status == "ACTIVE"
                )
            )
            if camera is None or user is None:
                raise RuntimeError("No se encontró la cámara o un usuario activo")
            row = CameraStreamSession(
                tenant_id=tenant.id,
                camera_id=camera.id,
                user_id=user.id,
                viewer_key_hash=hash_token(secrets.token_urlsafe(32)),
                status="starting",
            )
            db.add(row)
            db.commit()
            session_id = row.id
            print(f"{camera_name}: sesión diagnóstica {session_id} iniciada", flush=True)

        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            with system_session() as db:
                row = db.get(CameraStreamSession, session_id)
                if row is None:
                    raise RuntimeError("La sesión diagnóstica desapareció")
                row.last_heartbeat_at = utcnow()
                status = row.status
                error = row.sanitized_error or ""
                db.commit()
            print(f"{camera_name}: estado={status} {error}".rstrip(), flush=True)
            if status in {"live", "error"}:
                return
            time.sleep(1)
        raise RuntimeError("La transmisión no alcanzó estado live en 30 segundos")
    finally:
        if session_id:
            with system_session() as db:
                row = db.get(CameraStreamSession, session_id)
                if row is not None and row.status not in {"stopped", "error"}:
                    row.status = "stopped"
                    row.stopped_at = utcnow()
                    row.stop_reason = "diagnostic_complete"
                    db.commit()


if __name__ == "__main__":
    main()
