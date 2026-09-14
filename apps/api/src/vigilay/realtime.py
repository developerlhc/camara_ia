"""Authenticated real-time camera, command and live-session updates."""

import asyncio
import json
import secrets
import time

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from vigilay.auth import Principal, principal_from_token
from vigilay.config import settings
from vigilay.db import system_session, tenant_session
from vigilay.models import (
    Camera,
    CameraStreamSession,
    DeviceCommand,
    FrigateConnection,
    Site,
    Tenant,
    utcnow,
)
from vigilay.realtime_hub import agent_hub
from vigilay.routes import authorized_camera
from vigilay.security import decrypt_credentials, hash_token

router = APIRouter(prefix="/api/v1", tags=["Tiempo real"])


def _authenticate(token: str) -> Principal:
    actor = principal_from_token(token)
    if "cameras.read" not in actor.permissions:
        raise HTTPException(403, "No tienes permiso para consultar cámaras")
    return actor


def _authorize_camera(actor: Principal, camera_id: str) -> bool:
    with tenant_session(actor.tenant_id, superadmin=actor.superadmin) as db:
        authorized_camera(db, actor, camera_id)
        if "cameras.configure" not in actor.permissions:
            return False
        try:
            authorized_camera(db, actor, camera_id, configure=True)
        except HTTPException:
            return False
        return True


def _snapshot(actor: Principal, subscription: dict, *, touch_live: bool) -> dict:
    camera_id = subscription["camera_id"]
    with tenant_session(actor.tenant_id, superadmin=actor.superadmin) as db:
        camera = db.get(Camera, camera_id)
        if camera is None:
            raise HTTPException(404, "Cámara no encontrada")
        result = {
            "type": "snapshot",
            "camera": {"id": camera.id, "status": camera.status, "enabled": camera.enabled},
            "commands": [],
            "live": None,
        }
        if subscription["can_configure"]:
            result["commands"] = [
                {
                    "id": command.id,
                    "command": command.command,
                    "status": command.status,
                    "error": command.sanitized_error,
                    "created_at": command.created_at.isoformat() + "Z",
                }
                for command in db.scalars(
                    select(DeviceCommand)
                    .where(DeviceCommand.camera_id == camera_id)
                    .order_by(DeviceCommand.created_at.desc())
                    .limit(20)
                )
            ]
        session_id = subscription.get("session_id")
        viewer_key = subscription.get("viewer_key")
        if session_id and viewer_key:
            session = db.scalar(
                select(CameraStreamSession).where(
                    CameraStreamSession.id == session_id,
                    CameraStreamSession.camera_id == camera_id,
                    CameraStreamSession.user_id == actor.id,
                )
            )
            if session is None or not secrets.compare_digest(
                session.viewer_key_hash, hash_token(viewer_key)
            ):
                raise HTTPException(404, "Sesión de video no encontrada")
            if touch_live and session.status not in {"stopped", "error"}:
                session.last_heartbeat_at = utcnow()
                db.commit()
            result["live"] = {
                "sessionId": session.id,
                "status": session.status,
                "error": session.sanitized_error,
            }
        return result


def _subscription(actor: Principal, payload: dict) -> dict:
    camera_id = payload.get("cameraId")
    if not isinstance(camera_id, str) or not camera_id or len(camera_id) > 64:
        raise HTTPException(422, "Cámara inválida")
    session_id = payload.get("sessionId") or ""
    viewer_key = payload.get("viewerKey") or ""
    if not isinstance(session_id, str) or len(session_id) > 64:
        raise HTTPException(422, "Sesión inválida")
    if not isinstance(viewer_key, str) or len(viewer_key) > 256:
        raise HTTPException(422, "Credencial de visualización inválida")
    return {
        "camera_id": camera_id,
        "session_id": session_id,
        "viewer_key": viewer_key,
        "can_configure": _authorize_camera(actor, camera_id),
    }


@router.websocket("/realtime")
async def realtime(websocket: WebSocket):
    config = settings()
    if websocket.headers.get("origin") != config.web_origin:
        await websocket.close(code=4403, reason="Origen no permitido")
        return
    try:
        actor = await asyncio.to_thread(
            _authenticate, websocket.cookies.get(config.session_cookie_name, "")
        )
    except HTTPException as exc:
        await websocket.close(code=4401 if exc.status_code == 401 else 4403)
        return
    await websocket.accept()
    await websocket.send_json({"type": "ready"})
    subscription = None
    previous = ""
    last_sent = 0.0
    last_touch = 0.0
    try:
        while True:
            poll_delay = 30.0
            if subscription:
                now = time.monotonic()
                touch_live = now - last_touch >= 10
                snapshot = await asyncio.to_thread(
                    _snapshot, actor, subscription, touch_live=touch_live
                )
                encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
                if encoded != previous or now - last_sent >= 20:
                    await websocket.send_text(encoded)
                    previous = encoded
                    last_sent = now
                if touch_live:
                    last_touch = now
                command_active = any(
                    command["status"] in {"PENDING", "RUNNING"} for command in snapshot["commands"]
                )
                live_starting = bool(snapshot["live"] and snapshot["live"]["status"] == "starting")
                poll_delay = 0.25 if command_active or live_starting else 2.0
            try:
                payload = await asyncio.wait_for(websocket.receive_json(), timeout=poll_delay)
            except TimeoutError:
                continue
            if not isinstance(payload, dict):
                await websocket.send_json({"type": "error", "detail": "Mensaje inválido"})
                continue
            if payload.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
            elif payload.get("type") == "subscribe":
                subscription = await asyncio.to_thread(_subscription, actor, payload)
                previous = ""
                last_touch = 0.0
            else:
                await websocket.send_json({"type": "error", "detail": "Mensaje no admitido"})
    except WebSocketDisconnect:
        return
    except HTTPException as exc:
        await websocket.send_json({"type": "error", "detail": str(exc.detail)})
        await websocket.close(code=4404)


def _authenticate_agent(payload: dict) -> tuple[str, str]:
    tenant_id = payload.get("tenantId")
    site_id = payload.get("siteId")
    token = payload.get("token")
    if not all(isinstance(value, str) and value for value in (tenant_id, site_id, token)):
        raise HTTPException(401, "Credencial de sede incompleta")
    with system_session() as db:
        tenant = db.get(Tenant, tenant_id)
        site = db.get(Site, site_id)
        connection = db.scalar(
            select(FrigateConnection).where(
                FrigateConnection.tenant_id == tenant_id,
                FrigateConnection.site_id == site_id,
            )
        )
        if (
            tenant is None
            or tenant.status != "ACTIVE"
            or site is None
            or site.tenant_id != tenant_id
            or connection is None
            or not connection.gateway_token_encrypted
        ):
            raise HTTPException(401, "Sede no autorizada")
        expected = decrypt_credentials(connection.gateway_token_encrypted, tenant_id, site_id).get(
            "gateway_token", ""
        )
        if not secrets.compare_digest(token, expected):
            raise HTTPException(401, "Sede no autorizada")
    return tenant_id, site_id


@router.websocket("/agent/realtime")
async def agent_realtime(websocket: WebSocket):
    await websocket.accept()
    try:
        payload = await asyncio.wait_for(websocket.receive_json(), timeout=5)
        tenant_id, site_id = await asyncio.to_thread(_authenticate_agent, payload)
    except (HTTPException, TimeoutError, ValueError):
        await websocket.close(code=4401, reason="Sede no autorizada")
        return
    listener = agent_hub.register(site_id)
    _, queue = listener
    try:
        await websocket.send_json({"type": "ready", "tenantId": tenant_id, "siteId": site_id})
        await websocket.send_json({"type": "wake", "event": "connected"})
        while True:
            try:
                message = await asyncio.wait_for(queue.get(), timeout=20)
            except TimeoutError:
                message = {"type": "ping"}
            await websocket.send_json(message)
    except WebSocketDisconnect:
        return
    finally:
        agent_hub.unregister(site_id, listener)
