"""Eventos y grabaciones autorizados del motor propio de Vigilay."""

import hmac
from pathlib import PurePosixPath
from urllib.parse import quote, urlsplit

from cryptography.exceptions import InvalidTag
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, SecretStr, field_validator
from sqlalchemy import select
from starlette.background import BackgroundTask

from vigilay.auth import Principal, audit, database, require
from vigilay.config import settings
from vigilay.db import system_session
from vigilay.media import LocalMediaService, MediaError
from vigilay.models import Camera, RecorderConnection, Site, utcnow
from vigilay.routes import authorized_camera, camera_query
from vigilay.security import decrypt_credentials, encrypt_credentials

router = APIRouter(prefix="/api/v1/media", tags=["Media"])


class RecorderConnectionInput(BaseModel):
    site_id: str = Field(min_length=36, max_length=36)
    endpoint_url: str = Field(default="", max_length=2048)
    gateway_token: SecretStr = Field(min_length=32, max_length=256)
    status: str = Field(pattern="^(ONLINE|OFFLINE|STARTING)$")

    @field_validator("endpoint_url")
    @classmethod
    def valid_endpoint(cls, value):
        if not value:
            return value
        parsed = urlsplit(value)
        local = parsed.hostname in {"127.0.0.1", "localhost"}
        if (
            (parsed.scheme != "https" and not (local and parsed.scheme == "http"))
            or not parsed.hostname
            or (not local and not parsed.hostname.endswith(".trycloudflare.com"))
            or (local and settings().app_env == "production")
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Endpoint inválido")
        return value.rstrip("/")


@router.put("/connection")
def update_connection(
    data: RecorderConnectionInput,
    actor: Principal = Depends(require("cameras.manage")),
    db=Depends(database),
):
    if data.status != "OFFLINE" and not data.endpoint_url:
        raise HTTPException(422, "El grabador activo debe publicar un endpoint")
    site = db.get(Site, data.site_id)
    if site is None or (actor.tenant_id and site.tenant_id != actor.tenant_id):
        raise HTTPException(404, "Sede no encontrada")
    row = db.scalar(select(RecorderConnection).where(RecorderConnection.site_id == site.id))
    if row is None:
        row = RecorderConnection(tenant_id=site.tenant_id, site_id=site.id)
        db.add(row)
        changed = True
    elif row.tenant_id != site.tenant_id:
        raise HTTPException(409, "La conexión pertenece a otra empresa")
    else:
        changed = row.endpoint_url != data.endpoint_url or row.status != data.status
    row.endpoint_url = data.endpoint_url
    row.gateway_token_encrypted = encrypt_credentials(
        {"gateway_token": data.gateway_token.get_secret_value()}, site.tenant_id, site.id
    )
    row.status = data.status
    row.last_seen_at = utcnow()
    if changed:
        audit(db, actor, "VIGILAY_RECORDER_CONNECTED", "site", site.id, site.tenant_id)
    db.commit()
    return {"connected": data.status == "ONLINE", "site_id": site.id}


@router.put("/connection/heartbeat")
def heartbeat_connection(data: RecorderConnectionInput):
    """Renueva el enlace con la credencial de sede, sin depender de una sesión web."""
    if data.status != "OFFLINE" and not data.endpoint_url:
        raise HTTPException(422, "El grabador activo debe publicar un endpoint")
    with system_session() as db:
        row = db.scalar(
            select(RecorderConnection).where(RecorderConnection.site_id == data.site_id)
        )
        if row is None or not row.gateway_token_encrypted:
            raise HTTPException(401, "Sede no autorizada")
        try:
            expected = decrypt_credentials(row.gateway_token_encrypted, row.tenant_id, row.site_id)[
                "gateway_token"
            ]
        except (InvalidTag, KeyError, ValueError) as exc:
            raise HTTPException(401, "Sede no autorizada") from exc
        if not hmac.compare_digest(data.gateway_token.get_secret_value(), expected):
            raise HTTPException(401, "Sede no autorizada")
        row.endpoint_url = data.endpoint_url
        row.status = data.status
        row.last_seen_at = utcnow()
        db.commit()
        return {"connected": data.status == "ONLINE", "site_id": row.site_id}


def safe_call(work):
    try:
        return work()
    except MediaError as exc:
        raise HTTPException(502, str(exc)) from exc


def service_for_camera(db, camera):
    return LocalMediaService.for_site(db, camera.tenant_id, camera.site_id)


def media_response(service, recording_id, request, download, filename):
    stream = safe_call(
        lambda: service.stream_recording(
            recording_id,
            range_header=request.headers.get("range"),
            if_range=request.headers.get("if-range"),
        )
    )
    headers = {**stream.headers, "Cache-Control": "private, no-store"}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return StreamingResponse(
        stream.chunks(),
        status_code=stream.response.status_code,
        headers=headers,
        background=BackgroundTask(stream.close),
    )


@router.get("/events")
def events(
    camera_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    after: int | None = Query(None, ge=0),
    before: int | None = Query(None, ge=1),
    actor: Principal = Depends(require("cameras.read")),
    db=Depends(database),
):
    if after is not None and before is not None:
        if before <= after or before - after > 7776000:
            raise HTTPException(422, "Selecciona un intervalo válido de hasta 90 días")
    if camera_id:
        allowed = [authorized_camera(db, actor, camera_id)]
    else:
        allowed = list(
            db.scalars(camera_query(actor).where(Camera.integration_type != "SIMULATOR"))
        )
    by_site = {}
    for camera in allowed:
        by_site.setdefault((camera.tenant_id, camera.site_id), {})[camera.id] = camera
    services = {}
    for tenant_id, site_id in by_site:
        try:
            services[(tenant_id, site_id)] = LocalMediaService.for_site(db, tenant_id, site_id)
        except MediaError as exc:
            services[(tenant_id, site_id)] = exc
    db.close()
    result, errors = [], []
    for scope, cameras in by_site.items():
        service = services[scope]
        if isinstance(service, MediaError):
            errors.append(str(service))
            continue
        try:
            rows = service.events(after=after, before=before)
        except MediaError as exc:
            errors.append(str(exc))
            continue
        for row in rows:
            camera = cameras.get(str(row.get("camera_id", "")))
            if camera is None:
                continue
            recording_id = str(row.get("id", ""))
            encoded_recording_id = quote(recording_id, safe="")
            result.append(
                {
                    **row,
                    "camera_id": camera.id,
                    "camera_name": camera.name,
                    "tenant_id": camera.tenant_id,
                    "thumbnail_url": None,
                    "clip_url": (
                        f"/api/v1/media/events/{camera.id}/clip.mp4?id={encoded_recording_id}"
                        if row.get("has_clip")
                        else None
                    ),
                }
            )
            if row.get("has_snapshot") and row.get("snapshot_id"):
                snapshot_id = quote(str(row["snapshot_id"]), safe="")
                result[-1]["thumbnail_url"] = (
                    f"/api/v1/media/events/{camera.id}/snapshot.jpg?id={snapshot_id}"
                )
    if not result and errors:
        raise HTTPException(502, errors[0])
    return sorted(result, key=lambda row: row.get("start_time") or 0, reverse=True)[:limit]


@router.get("/recordings")
def recordings(
    camera_id: str,
    after: int = Query(..., ge=0),
    before: int = Query(..., ge=1),
    actor: Principal = Depends(require("cameras.read")),
    db=Depends(database),
):
    if before <= after or before - after > 604800:
        raise HTTPException(422, "Selecciona un intervalo válido de hasta 7 días")
    camera = authorized_camera(db, actor, camera_id)
    if camera.integration_type == "SIMULATOR":
        raise HTTPException(409, "El simulador no genera grabaciones locales")
    service = safe_call(lambda: service_for_camera(db, camera))
    camera_values = camera.id, camera.name
    db.close()
    rows = safe_call(lambda: service.recordings(camera_values[0], after=after, before=before))
    return [
        {
            **row,
            "camera_id": camera_values[0],
            "camera_name": camera_values[1],
            "clip_url": (
                f"/api/v1/media/recordings/{camera_values[0]}/clip.mp4"
                f"?id={quote(str(row.get('id', '')), safe='')}"
            ),
        }
        for row in rows
    ]


def recording_clip_response(request, camera_id, recording_id, download, actor, db):
    if not recording_id or len(recording_id) > 500:
        raise HTTPException(422, "Identificador de grabación inválido")
    camera = authorized_camera(db, actor, camera_id)
    parts = PurePosixPath(recording_id).parts
    if len(parts) != 3 or parts[1] != camera.id or not parts[2].endswith(".mp4"):
        raise HTTPException(404, "Grabación no encontrada")
    service = safe_call(lambda: service_for_camera(db, camera))
    db.close()
    return media_response(
        service,
        recording_id,
        request,
        download,
        f"grabacion-{camera_id}.mp4",
    )


def event_snapshot_response(request, camera_id, recording_id, actor, db):
    if not recording_id or len(recording_id) > 500:
        raise HTTPException(422, "Identificador de evidencia inválido")
    camera = authorized_camera(db, actor, camera_id)
    parts = PurePosixPath(recording_id).parts
    if len(parts) != 3 or parts[1] != camera.id or not parts[2].endswith(".jpg"):
        raise HTTPException(404, "Evidencia no encontrada")
    service = safe_call(lambda: service_for_camera(db, camera))
    db.close()
    return media_response(service, recording_id, request, False, f"evento-{camera_id}.jpg")


@router.get("/recordings/{camera_id}/clip.mp4")
def recording_clip(
    request: Request,
    camera_id: str,
    id: str = Query(..., min_length=1, max_length=500),
    download: bool = False,
    actor: Principal = Depends(require("cameras.read")),
    db=Depends(database),
):
    return recording_clip_response(request, camera_id, id, download, actor, db)


@router.get("/events/{camera_id}/clip.mp4")
def event_clip(
    request: Request,
    camera_id: str,
    id: str = Query(..., min_length=1, max_length=500),
    download: bool = False,
    actor: Principal = Depends(require("cameras.read")),
    db=Depends(database),
):
    return recording_clip_response(request, camera_id, id, download, actor, db)


@router.get("/events/{camera_id}/snapshot.jpg")
def event_snapshot(
    request: Request,
    camera_id: str,
    id: str = Query(..., min_length=1, max_length=500),
    actor: Principal = Depends(require("cameras.read")),
    db=Depends(database),
):
    return event_snapshot_response(request, camera_id, id, actor, db)
