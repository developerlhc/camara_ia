"""Comprueba requisitos locales de video sin iniciar ni publicar transmisiones."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import select
from vigilay.config import settings
from vigilay.db import system_session
from vigilay.models import (
    Camera,
    CameraCredential,
    CameraStreamProvider,
    ServiceHeartbeat,
    Tenant,
    utcnow,
)
from vigilay.security import decrypt_credentials
from vigilay.stream_agent import _port_open


def main() -> None:
    config = settings()
    print(
        json.dumps(
            {
                "component": "local_tools",
                "ffmpeg": bool(shutil.which(config.ffmpeg_path) or Path(config.ffmpeg_path).is_file()),
                "v380_decoder": Path(config.v380_decoder_path).is_file(),
            }
        )
    )
    with system_session() as db:
        heartbeat = db.get(ServiceHeartbeat, "stream-agent")
        print(
            json.dumps(
                {
                    "component": "stream_agent",
                    "heartbeat_age_seconds": (
                        round((utcnow() - heartbeat.last_seen_at).total_seconds(), 1)
                        if heartbeat
                        else None
                    ),
                }
            )
        )
        tenant = db.scalar(select(Tenant).where(Tenant.name == "Cenfelec"))
        if tenant is None:
            raise RuntimeError("No existe la empresa Cenfelec")
        rows = db.execute(
            select(Camera, CameraCredential, CameraStreamProvider)
            .join(CameraCredential, CameraCredential.camera_id == Camera.id)
            .outerjoin(CameraStreamProvider, CameraStreamProvider.camera_id == Camera.id)
            .where(Camera.tenant_id == tenant.id)
        ).all()
        for camera, credential, provider in rows:
            secret = decrypt_credentials(
                credential.secret_encrypted, camera.tenant_id, camera.id
            )
            if camera.integration_type == "V380":
                source_mode = str(secret.get("source", "lan")).lower()
                if source_mode == "cloud":
                    reachable = None
                else:
                    host = str(secret.get("host", ""))
                    port = int(secret.get("port", 8800))
                    reachable = bool(host and _port_open(host, port, 2.0))
            else:
                source_mode = "rtsp"
                source = urlsplit(str(secret.get("rtsp_url", "")))
                host = source.hostname or ""
                port = source.port or 554
                reachable = bool(host and _port_open(host, port, 2.0))
            print(
                json.dumps(
                    {
                        "component": "camera",
                        "camera": camera.name,
                        "type": camera.integration_type,
                        "source_mode": source_mode,
                        "endpoint": f"{host}:{port}" if source_mode != "cloud" else "cloud",
                        "reachable": reachable,
                        "live_input": bool(provider and provider.enabled),
                    }
                )
            )


if __name__ == "__main__":
    main()
