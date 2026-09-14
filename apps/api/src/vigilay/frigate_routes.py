"""Tenant-authorized Frigate events, recordings and media proxy."""

import hmac

from cryptography.exceptions import InvalidTag
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select

from vigilay.auth import Principal, audit, database, require
from vigilay.frigate import FrigateError, FrigateService, recording_windows
from vigilay.models import Camera, FrigateConnection, Site
from vigilay.routes import authorized_camera, camera_dict, camera_query
from vigilay.schemas import FrigateCameraInput
from vigilay.security import decrypt_credentials

router = APIRouter(prefix="/api/v1/frigate", tags=["Frigate"])
SAFE_EVENT_ID = r"^[a-zA-Z0-9_.-]+$"


@router.get("/internal/cameras", include_in_schema=False)
def internal_frigate_cameras(request: Request, site_id: str, db=Depends(database)):
    site = db.get(Site, site_id)
    if site is None:
        raise HTTPException(404, "Sede no encontrada")
    connection = db.scalar(
        select(FrigateConnection).where(
            FrigateConnection.tenant_id == site.tenant_id,
            FrigateConnection.site_id == site.id,
        )
    )
    if connection is None or not connection.gateway_token_encrypted:
        raise HTTPException(404, "Recurso no encontrado")
    try:
        expected = decrypt_credentials(
            connection.gateway_token_encrypted, site.tenant_id, site.id
        ).get("gateway_token", "")
    except (InvalidTag, ValueError):
        raise HTTPException(404, "Recurso no encontrado") from None
    supplied = request.headers.get("authorization", "").removeprefix("Bearer ")
    if not expected or not hmac.compare_digest(expected, supplied):
        raise HTTPException(404, "Recurso no encontrado")
    service = safe_call(lambda: FrigateService.for_site(db, site.tenant_id, site.id))
    db.close()  # return the pooled MySQL connection before the outbound Frigate request
    names = safe_call(lambda: service.camera_names())
    return [{"name": name} for name in sorted(names)]


def mapped_camera(db, actor, camera_id):
    camera = authorized_camera(db, actor, camera_id)
    if not camera.frigate_camera_name:
        raise HTTPException(409, "La cámara todavía no está vinculada con Frigate")
    return camera


def safe_call(work):
    try:
        return work()
    except FrigateError as exc:
        raise HTTPException(502, str(exc)) from exc


def service_for_camera(db, camera):
    return FrigateService.for_site(db, camera.tenant_id, camera.site_id)


@router.get("/cameras")
def frigate_cameras(
    site_id: str,
    actor: Principal = Depends(require("cameras.configure")),
    db=Depends(database),
):
    site = db.get(Site, site_id)
    if site is None or (actor.tenant_id and site.tenant_id != actor.tenant_id):
        raise HTTPException(404, "Sede no encontrada")
    service = safe_call(lambda: FrigateService.for_site(db, site.tenant_id, site.id))
    db.close()  # return the pooled MySQL connection before the outbound Frigate request
    names = safe_call(lambda: service.camera_names())
    return [{"name": name} for name in sorted(names)]


@router.put("/cameras/{camera_id}")
def map_frigate_camera(
    camera_id: str,
    data: FrigateCameraInput,
    actor: Principal = Depends(require("cameras.manage")),
    db=Depends(database),
):
    camera = authorized_camera(db, actor, camera_id, configure=True)
    names = safe_call(lambda: service_for_camera(db, camera).camera_names())
    if data.frigate_camera_name not in names:
        raise HTTPException(404, "La cámara indicada no existe en Frigate")
    assigned = db.scalar(
        camera_query(actor).where(
            Camera.site_id == camera.site_id,
            Camera.frigate_camera_name == data.frigate_camera_name,
            Camera.id != camera.id,
        )
    )
    if assigned is not None:
        raise HTTPException(409, "Esa cámara de Frigate ya está asignada en esta sede")
    camera.frigate_camera_name = data.frigate_camera_name
    audit(db, actor, "CAMERA_FRIGATE_LINKED", "camera", camera.id, camera.tenant_id)
    db.commit()
    return camera_dict(camera)


@router.get("/events")
def events(
    camera_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    actor: Principal = Depends(require("cameras.read")),
    db=Depends(database),
):
    if camera_id:
        allowed = [mapped_camera(db, actor, camera_id)]
    else:
        allowed = list(
            db.scalars(camera_query(actor).where(Camera.frigate_camera_name.is_not(None)))
        )
    by_site = {}
    for camera in allowed:
        by_site.setdefault((camera.tenant_id, camera.site_id), {})[camera.frigate_camera_name] = (
            camera
        )
    # Build every FrigateService while the pooled connection is still open, then release it:
    # the calls below reach each site over the internet and must not hold a scarce MySQL
    # connection while they wait, or one slow/offline site stalls every other request.
    services = {}
    for tenant_id, site_id in by_site:
        try:
            services[(tenant_id, site_id)] = FrigateService.for_site(db, tenant_id, site_id)
        except FrigateError as exc:
            services[(tenant_id, site_id)] = exc
    db.close()
    result = []
    errors = []
    for (tenant_id, site_id), by_name in by_site.items():
        service = services[(tenant_id, site_id)]
        if isinstance(service, FrigateError):
            errors.append(str(service))
            continue
        try:
            rows = service.events(limit=200)
        except FrigateError as exc:
            errors.append(str(exc))
            continue
        for row in rows:
            camera = by_name.get(row.get("camera"))
            if camera is None:
                continue
            event_id = str(row.get("id", ""))
            result.append(
                {
                    "id": event_id,
                    "camera_id": camera.id,
                    "camera_name": camera.name,
                    "tenant_id": camera.tenant_id,
                    "label": row.get("label"),
                    "sub_label": row.get("sub_label"),
                    "start_time": row.get("start_time"),
                    "end_time": row.get("end_time"),
                    "has_clip": bool(row.get("has_clip")),
                    "has_snapshot": bool(row.get("has_snapshot")),
                    "thumbnail_url": f"/api/v1/frigate/events/{event_id}/thumbnail.jpg",
                    "clip_url": f"/api/v1/frigate/events/{event_id}/clip.mp4"
                    if row.get("has_clip")
                    else None,
                }
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
    camera = mapped_camera(db, actor, camera_id)
    service = safe_call(lambda: service_for_camera(db, camera))
    camera_id_value, camera_name_value, frigate_name = (
        camera.id,
        camera.name,
        camera.frigate_camera_name,
    )
    db.close()  # return the pooled MySQL connection before the outbound Frigate request
    segments = safe_call(lambda: service.recordings(frigate_name, after=after, before=before))
    return [
        {
            **window,
            "camera_id": camera_id_value,
            "camera_name": camera_name_value,
            "clip_url": (
                f"/api/v1/frigate/recordings/{camera_id_value}/start/{int(window['start'])}"
                f"/end/{int(window['end'])}/clip.mp4"
            ),
        }
        for window in recording_windows(segments)
    ]


@router.get("/events/{event_id}/thumbnail.jpg")
def event_thumbnail(
    event_id: str = Path(pattern=SAFE_EVENT_ID),
    actor: Principal = Depends(require("cameras.read")),
    db=Depends(database),
):
    _, service, _ = locate_event(db, actor, event_id)
    content, media_type = safe_call(lambda: service.media(f"/events/{event_id}/thumbnail.jpg"))
    return Response(
        content, media_type=media_type, headers={"Cache-Control": "private, max-age=30"}
    )


@router.get("/events/{event_id}/clip.mp4")
def event_clip(
    event_id: str = Path(pattern=SAFE_EVENT_ID),
    actor: Principal = Depends(require("cameras.read")),
    db=Depends(database),
):
    _, service, _ = locate_event(db, actor, event_id)
    chunks, media_type = safe_call(lambda: service.stream_media(f"/events/{event_id}/clip.mp4"))
    return StreamingResponse(chunks, media_type=media_type)


@router.get("/recordings/{camera_id}/start/{start}/end/{end}/clip.mp4")
def recording_clip(
    camera_id: str,
    start: int,
    end: int,
    actor: Principal = Depends(require("cameras.read")),
    db=Depends(database),
):
    if end <= start or end - start > 3600:
        raise HTTPException(422, "El fragmento debe durar como máximo una hora")
    camera = mapped_camera(db, actor, camera_id)
    service = safe_call(lambda: service_for_camera(db, camera))
    frigate_name = camera.frigate_camera_name
    db.close()  # return the pooled MySQL connection before streaming the clip from Frigate
    chunks, media_type = safe_call(
        lambda: service.stream_media(f"/{frigate_name}/start/{start}/end/{end}/clip.mp4")
    )
    return StreamingResponse(chunks, media_type=media_type)


def locate_event(db, actor, event_id):
    cameras = list(db.scalars(camera_query(actor).where(Camera.frigate_camera_name.is_not(None))))
    by_scope = {}
    for camera in cameras:
        by_scope.setdefault((camera.tenant_id, camera.site_id), []).append(camera)
    # As above: resolve every site's FrigateService up front so the possibly-slow lookup
    # of the right site (one HTTP round trip per site, until the event is found) never
    # holds the pooled MySQL connection.
    services = {}
    for scope, scope_cameras in by_scope.items():
        try:
            services[scope] = service_for_camera(db, scope_cameras[0])
        except FrigateError:
            services[scope] = None
    db.close()
    for scope, scope_cameras in by_scope.items():
        service = services[scope]
        if service is None:
            continue
        try:
            event = service.event(event_id)
        except FrigateError:
            continue
        matched = next(
            (row for row in scope_cameras if row.frigate_camera_name == event.get("camera")),
            None,
        )
        if matched is not None:
            return matched, service, event
    raise HTTPException(404, "Evento no disponible para este usuario")
