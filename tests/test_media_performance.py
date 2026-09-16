"""No live providers or camera mutations; isolated test schema and HTTP fakes."""

import httpx
import pytest
from sqlalchemy import event
from vigilay import frigate_routes
from vigilay.auth import principal_from_token
from vigilay.config import settings
from vigilay.db import engine, system_session
from vigilay.frigate import FrigateError, FrigateService, recording_windows
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
def test_media_keeps_ranges_headers_and_stream_cleanup(status):
    def respond(request):
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
        service = FrigateService(
            base_url="http://frigate:5000", gateway_token="site-token", client=client
        )
        stream = service.stream_media(
            "/cam/start/1/end/5/clip.mp4", range_header="bytes=0-3", if_range='"v1"'
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
        service = FrigateService(base_url="http://frigate:5000", client=client)
        with pytest.raises(FrigateError, match="ya no existe"):
            service.stream_media("/cam/start/1/end/5/clip.mp4")
        assert response.is_closed


def test_recordings_are_small_windows():
    windows = recording_windows(
        [{"start_time": start, "end_time": start + 10} for start in range(1000, 4600, 10)]
    )
    assert len(windows) == 12
    assert all(window["duration"] == 300 for window in windows)


def test_download_is_authorized_ranged_and_releases_db(monkeypatch, clients, cameras):
    camera = cameras["a"]
    with system_session() as db:
        db.get(Camera, camera["id"]).frigate_camera_name = "imou"
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
            frigate_routes,
            "service_for_camera",
            lambda *args: FrigateService(base_url="http://frigate:5000", client=upstream),
        )
        path = f"/api/v1/frigate/recordings/{camera['id']}/start/100/end/200/clip.mp4?download=true"
        denied = clients["b"].get(path)
        assert denied.status_code == 404
        assert not seen
        response = clients["a"].get(path, headers={"range": "bytes=0-3"})
        assert response.status_code == 206
        assert response.content == b"test"
        assert response.headers["content-range"] == "bytes 0-3/10"
        assert response.headers["content-disposition"].startswith("attachment;")
        assert seen == ["bytes=0-3"]


def test_recording_dates_validated_and_clamped(monkeypatch, clients, cameras):
    camera = cameras["a"]
    with system_session() as db:
        db.get(Camera, camera["id"]).frigate_camera_name = "imou"
        db.commit()
    seen = []

    class Service:
        def recordings(self, name, *, after, before):
            seen.append((name, after, before))
            return [{"start_time": 90, "end_time": 210}]

    monkeypatch.setattr(frigate_routes, "service_for_camera", lambda *args: Service())
    path = f"/api/v1/frigate/recordings?camera_id={camera['id']}"
    assert clients["a"].get(path + "&after=200&before=100").status_code == 422
    assert clients["a"].get(path + "&after=0&before=604801").status_code == 422
    response = clients["a"].get(path + "&after=100&before=200")
    assert response.status_code == 200
    assert seen == [("imou", 100, 200)]
    assert response.json()[0]["start"] == 100
    assert response.json()[0]["end"] == 200
