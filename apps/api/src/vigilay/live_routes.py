"""Authorized on-demand live-view endpoints."""

import hmac
import secrets
from datetime import timedelta

from cryptography.exceptions import InvalidTag
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import select

from vigilay.auth import Principal, audit, database, rate_limit, require
from vigilay.config import settings
from vigilay.db import system_session
from vigilay.models import (
    Camera,
    CameraStreamProvider,
    CameraStreamSession,
    IntegrationSetting,
    RecorderConnection,
    ServiceHeartbeat,
    utcnow,
)
from vigilay.realtime_hub import notify_site
from vigilay.routes import authorized_camera
from vigilay.schemas import CloudflareIntegrationInput, LiveSessionInput
from vigilay.security import decrypt_credentials, encrypt_credentials, hash_token
from vigilay.streaming import CloudflareStreamService, StreamProviderError

router = APIRouter(prefix="/api/v1", tags=["Video en vivo"])


class SiteAgentInput(BaseModel):
    site_id: str = Field(min_length=36, max_length=36)
    gateway_token: SecretStr = Field(min_length=32, max_length=256)


class SiteAgentStatusInput(SiteAgentInput):
    camera_id: str = Field(min_length=1, max_length=80)
    status: str = Field(pattern="^(starting|live|error|stopped)$")


def _authorize_site_agent(db, data: SiteAgentInput):
    row = db.scalar(select(RecorderConnection).where(RecorderConnection.site_id == data.site_id))
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
    return row


def _touch_site_agent(db, site_id):
    service_name = f"stream-agent:{site_id}"
    heartbeat = db.get(ServiceHeartbeat, service_name)
    if heartbeat is None:
        heartbeat = ServiceHeartbeat(service_name=service_name, last_seen_at=utcnow())
        db.add(heartbeat)
    else:
        heartbeat.last_seen_at = utcnow()
    return heartbeat


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


@router.post("/agent/live/poll")
def poll_site_live_agent(data: SiteAgentInput):
    """Entrega sólo trabajos de la sede autenticada; la fuente RTSP permanece local."""
    with system_session() as db:
        connection = _authorize_site_agent(db, data)
        _touch_site_agent(db, connection.site_id)
        cutoff = utcnow() - timedelta(seconds=settings().stream_idle_timeout_seconds)
        rows = db.execute(
            select(CameraStreamSession, CameraStreamProvider)
            .select_from(CameraStreamSession)
            .join(Camera, Camera.id == CameraStreamSession.camera_id)
            .join(CameraStreamProvider, CameraStreamProvider.camera_id == Camera.id)
            .where(
                Camera.site_id == connection.site_id,
                Camera.enabled.is_(True),
                CameraStreamProvider.enabled.is_(True),
                CameraStreamSession.status.in_(["starting", "live"]),
                CameraStreamSession.last_heartbeat_at >= cutoff,
            )
            .order_by(CameraStreamSession.started_at)
        ).all()
        streams = {}
        for session, provider in rows:
            if session.camera_id in streams:
                continue
            try:
                publish_url = decrypt_credentials(
                    provider.publish_url_encrypted, provider.tenant_id, provider.camera_id
                )["publish_url"]
            except (InvalidTag, KeyError, ValueError):
                continue
            streams[session.camera_id] = {
                "camera_id": session.camera_id,
                "publish_url": publish_url,
            }
        db.commit()
        return {"site_id": connection.site_id, "streams": list(streams.values())}


@router.post("/agent/live/status")
def update_site_live_status(data: SiteAgentStatusInput):
    with system_session() as db:
        connection = _authorize_site_agent(db, data)
        camera = db.scalar(
            select(Camera).where(Camera.id == data.camera_id, Camera.site_id == connection.site_id)
        )
        if camera is None:
            raise HTTPException(404, "Cámara no encontrada")
        _touch_site_agent(db, connection.site_id)
        sessions = list(
            db.scalars(
                select(CameraStreamSession).where(
                    CameraStreamSession.camera_id == camera.id,
                    CameraStreamSession.status.in_(["starting", "live"]),
                )
            )
        )
        for session in sessions:
            session.status = data.status
            if data.status in {"error", "stopped"}:
                session.stopped_at = utcnow()
                session.stop_reason = (
                    "publisher_failed" if data.status == "error" else "agent_stopped"
                )
                session.sanitized_error = (
                    "No se pudo iniciar la transmisión" if data.status == "error" else None
                )
            elif data.status == "live":
                session.sanitized_error = None
        db.commit()
        return {"camera_id": camera.id, "status": data.status, "sessions": len(sessions)}


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
    heartbeat = db.get(ServiceHeartbeat, f"stream-agent:{camera.site_id}")
    if heartbeat is None:
        # Compatibilidad durante la migración desde el agente central anterior.
        heartbeat = db.get(ServiceHeartbeat, "stream-agent")
    if heartbeat is None or heartbeat.last_seen_at < utcnow() - timedelta(seconds=30):
        raise HTTPException(
            503,
            "El agente local de video está apagado. Inícialo en el equipo de la sede.",
        )
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
    notify_site(camera.site_id, "camera.stream.start", session.id)
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
