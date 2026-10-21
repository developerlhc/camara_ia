"""Autorización, streaming Range y liberación de conexiones del medio propio."""

from urllib.parse import quote

import httpx
import pytest
from sqlalchemy import event
from vigilay import media_routes
from vigilay.auth import principal_from_token
from vigilay.config import settings
from vigilay.db import engine, system_session
from vigilay.media import LocalMediaService, MediaError
from vigilay.models import Camera


def test_authentication_uses_one_query_without_caching_revocation(clients):
    statements = []

    def observed(*args):
        statements.append(args[2])

    event.listen(engine(), "before_cursor_execute", observed)
    try:
        token = clients["a"].cookies.get(settings().session_cookie_name)
        actor = principal_from_token(token)
        assert actor.role == "CLIENT_ADMIN"
        assert "cameras.read" in actor.permissions
        assert len(statements) == 1
    finally:
        event.remove(engine(), "before_cursor_execute", observed)
    assert clients["a"].post("/api/v1/auth/logout").status_code == 204
    with pytest.raises(Exception) as exc:
        principal_from_token(token)
    assert exc.value.status_code == 401


@pytest.mark.parametrize("status", [200, 206, 416])
def test_media_keeps_range_headers_and_stream_cleanup(status):
    def respond(request):
        assert request.url.params["id"] == "2026-10-20/cam/clip.mp4"
        assert request.headers["range"] == "bytes=0-3"
        assert request.headers["if-range"] == '"v1"'
        assert request.headers["authorization"] == "Bearer site-token"
        return httpx.Response(
            status,
            headers={
                "content-type": "video/mp4",
                "content-length": "4",
                "content-range": "bytes 0-3/10" if status != 416 else "bytes */10",
                "accept-ranges": "bytes",
                "etag": '"v1"',
            },
            stream=httpx.ByteStream(b"test"),
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        service = LocalMediaService(
            base_url="http://127.0.0.1:8788", gateway_token="site-token", client=client
        )
        stream = service.stream_recording(
            "2026-10-20/cam/clip.mp4", range_header="bytes=0-3", if_range='"v1"'
        )
        assert stream.response.status_code == status
        assert stream.headers["content-length"] == "4"
        assert stream.headers["accept-ranges"] == "bytes"
        assert b"".join(stream.chunks()) == b"test"
        assert stream.response.is_closed
        assert not client.is_closed


def test_missing_recording_closes_upstream():
    response = httpx.Response(404, stream=httpx.ByteStream(b"missing"))
    with httpx.Client(transport=httpx.MockTransport(lambda _: response)) as client:
        service = LocalMediaService(base_url="http://127.0.0.1:8788", client=client)
        with pytest.raises(MediaError, match="ya no existe"):
            service.stream_recording("2026-10-20/cam/missing.mp4")
        assert response.is_closed


def test_download_is_authorized_ranged_and_releases_db(monkeypatch, clients, cameras):
    camera = cameras["a"]
    with system_session() as db:
        db.get(Camera, camera["id"]).integration_type = "RTSP"
        db.commit()
    seen = []

    def respond(request):
        assert engine().pool.checkedout() == 0
        seen.append(request.headers.get("range"))
        return httpx.Response(
            206,
            headers={
                "content-type": "video/mp4",
                "content-range": "bytes 0-3/10",
                "content-length": "4",
                "accept-ranges": "bytes",
            },
            stream=httpx.ByteStream(b"test"),
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as upstream:
        monkeypatch.setattr(
            media_routes,
            "service_for_camera",
            lambda *args: LocalMediaService(base_url="http://127.0.0.1:8788", client=upstream),
        )
        recording_id = f"2026-10-20/{camera['id']}/clip.mp4"
        path = (
            f"/api/v1/media/recordings/{camera['id']}/clip.mp4"
            f"?id={quote(recording_id, safe='')}&download=true"
        )
        denied = clients["b"].get(path)
        assert denied.status_code == 404
        assert not seen
        response = clients["a"].get(path, headers={"range": "bytes=0-3"})
        assert response.status_code == 206
        assert response.content == b"test"
        assert response.headers["content-range"] == "bytes 0-3/10"
        assert response.headers["content-disposition"].startswith("attachment;")
        assert seen == ["bytes=0-3"]


def test_recording_dates_are_validated(monkeypatch, clients, cameras):
    camera = cameras["a"]
    with system_session() as db:
        db.get(Camera, camera["id"]).integration_type = "RTSP"
        db.commit()
    seen = []

    class Service:
        def recordings(self, camera_id, *, after, before):
            seen.append((camera_id, after, before))
            return [{"id": f"2026-10-20/{camera_id}/clip.mp4", "start": 100, "end": 200}]

    monkeypatch.setattr(media_routes, "service_for_camera", lambda *args: Service())
    path = f"/api/v1/media/recordings?camera_id={camera['id']}"
    assert clients["a"].get(path + "&after=200&before=100").status_code == 422
    assert clients["a"].get(path + "&after=0&before=604801").status_code == 422
    response = clients["a"].get(path + "&after=100&before=200")
    assert response.status_code == 200
    assert seen == [(camera["id"], 100, 200)]
    assert response.json()[0]["start"] == 100
