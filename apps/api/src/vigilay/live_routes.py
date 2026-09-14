"""Authorized on-demand live-view endpoints."""

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from vigilay.auth import Principal, audit, database, rate_limit, require
from vigilay.config import settings
from vigilay.models import (
    Camera,
    CameraStreamProvider,
    CameraStreamSession,
    IntegrationSetting,
    utcnow,
)
from vigilay.routes import authorized_camera
from vigilay.schemas import CloudflareIntegrationInput, LiveSessionInput
from vigilay.security import encrypt_credentials, hash_token
from vigilay.streaming import CloudflareStreamService, StreamProviderError

router = APIRouter(prefix="/api/v1", tags=["Video en vivo"])


def _superadmin(actor):
    if not actor.superadmin:
        raise HTTPException(403, "Sólo el superadministrador puede configurar Cloudflare")


@router.get("/admin/integrations/cloudflare")
def cloudflare_integration_status(
    actor: Principal = Depends(require("system.read")), db=Depends(database)
):
    _superadmin(actor)
    row = db.scalar(select(IntegrationSetting).where(IntegrationSetting.provider == "cloudflare"))
    configured_from_environment = bool(
        settings().cloudflare_account_id and settings().cloudflare_stream_api_token
    )
    return {
        "configured": bool((row and row.enabled) or configured_from_environment),
        "source": "vigilay"
        if row and row.enabled
        else "environment"
        if configured_from_environment
        else "none",
        "tokenStored": bool(row),
    }


@router.put("/admin/integrations/cloudflare")
def configure_cloudflare_integration(
    data: CloudflareIntegrationInput,
    request: Request,
    actor: Principal = Depends(require("system.read")),
    db=Depends(database),
):
    _superadmin(actor)
    rate_limit(request, "cloudflare-config", 5, 300)
    account_id = data.account_id.strip()
    api_token = data.api_token.get_secret_value()
    try:
        CloudflareStreamService(db, account_id=account_id, api_token=api_token).verify_credentials()
    except StreamProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    row = db.scalar(select(IntegrationSetting).where(IntegrationSetting.provider == "cloudflare"))
    encrypted = encrypt_credentials(
        {"account_id": account_id, "api_token": api_token}, "__system__", "cloudflare"
    )
    if row:
        row.config_encrypted = encrypted
        row.enabled = True
    else:
        row = IntegrationSetting(provider="cloudflare", config_encrypted=encrypted, enabled=True)
        db.add(row)
    db.flush()
    audit(db, actor, "CLOUDFLARE_CONFIGURED", "integration_setting", row.id, request=request)
    db.commit()
    return {"configured": True, "source": "vigilay", "tokenStored": True}


def _session(db, actor, camera_id, data: LiveSessionInput):
    row = db.scalar(
        select(CameraStreamSession).where(
            CameraStreamSession.id == data.session_id,
            CameraStreamSession.camera_id == camera_id,
            CameraStreamSession.user_id == actor.id,
        )
    )
    if row is None or not secrets.compare_digest(
        row.viewer_key_hash, hash_token(data.viewer_key.get_secret_value())
    ):
        raise HTTPException(404, "Sesión de video no encontrada")
    return row


def _safe_response(session, provider, *, viewer_key=None):
    result = {
        "cameraId": session.camera_id,
        "status": session.status,
        "playbackUrl": provider.playback_url if provider else "",
        "sessionId": session.id,
    }
    if viewer_key:
        result["viewerKey"] = viewer_key
    if session.sanitized_error:
        result["error"] = session.sanitized_error
    return result


@router.post("/cameras/{camera_id}/live/start")
def start_live(
    camera_id: str,
    request: Request,
    actor: Principal = Depends(require("cameras.read")),
    db=Depends(database),
):
    rate_limit(request, f"live-start:{camera_id}", 20, 60)
    camera = authorized_camera(db, actor, camera_id)
    if not camera.enabled or camera.integration_type == "SIMULATOR":
        raise HTTPException(409, "Esta cámara no puede transmitir video")
    db.scalar(select(Camera).where(Camera.id == camera.id).with_for_update())
    try:
        live_input = CloudflareStreamService(db).get_or_create_live_input(camera)
    except StreamProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    viewer_key = secrets.token_urlsafe(32)
    session = CameraStreamSession(
        tenant_id=camera.tenant_id,
        camera_id=camera.id,
        user_id=actor.id,
        viewer_key_hash=hash_token(viewer_key),
        status="starting",
    )
    db.add(session)
    db.flush()
    audit(db, actor, "CAMERA_LIVE_STARTED", "camera_stream_session", session.id, camera.tenant_id)
    db.commit()
    return _safe_response(session, live_input, viewer_key=viewer_key)


@router.post("/cameras/{camera_id}/live/stop")
def stop_live(
    camera_id: str,
    data: LiveSessionInput,
    request: Request,
    actor: Principal = Depends(require("cameras.read")),
    db=Depends(database),
):
    rate_limit(request, f"live-stop:{camera_id}", 40, 60)
    camera = authorized_camera(db, actor, camera_id)
    session = _session(db, actor, camera_id, data)
    if session.status not in {"stopped", "error"}:
        session.status = "stopped"
        session.stopped_at = utcnow()
        session.stop_reason = "viewer_closed"
        audit(
            db, actor, "CAMERA_LIVE_STOPPED", "camera_stream_session", session.id, camera.tenant_id
        )
        db.commit()
    provider = db.scalar(
        select(CameraStreamProvider).where(CameraStreamProvider.camera_id == camera.id)
    )
    return _safe_response(session, provider)


@router.post("/cameras/{camera_id}/live/heartbeat")
def heartbeat_live(
    camera_id: str,
    data: LiveSessionInput,
    request: Request,
    actor: Principal = Depends(require("cameras.read")),
    db=Depends(database),
):
    rate_limit(request, f"live-heartbeat:{camera_id}", 120, 60)
    authorized_camera(db, actor, camera_id)
    session = _session(db, actor, camera_id, data)
    if session.status in {"stopped", "error"}:
        raise HTTPException(409, "La sesión de video terminó")
    session.last_heartbeat_at = utcnow()
    db.commit()
    provider = db.scalar(
        select(CameraStreamProvider).where(CameraStreamProvider.camera_id == camera_id)
    )
    return _safe_response(session, provider)


@router.get("/cameras/{camera_id}/live/status")
def live_status(
    camera_id: str,
    session_id: str,
    actor: Principal = Depends(require("cameras.read")),
    db=Depends(database),
):
    authorized_camera(db, actor, camera_id)
    session = db.scalar(
        select(CameraStreamSession).where(
            CameraStreamSession.id == session_id,
            CameraStreamSession.camera_id == camera_id,
            CameraStreamSession.user_id == actor.id,
        )
    )
    if session is None:
        raise HTTPException(404, "Sesión de video no encontrada")
    provider = db.scalar(
        select(CameraStreamProvider).where(CameraStreamProvider.camera_id == camera_id)
    )
    return _safe_response(session, provider)
