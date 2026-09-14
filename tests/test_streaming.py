import subprocess
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select
from vigilay.db import system_session
from vigilay.models import (
    Camera,
    CameraCapability,
    CameraCredential,
    CameraStreamProvider,
    CameraStreamSession,
    DeviceCommand,
    IntegrationSetting,
)
from vigilay.security import decrypt_credentials, encrypt_credentials
from vigilay.stream_agent import (
    CameraStreamResolver,
    LocalStreamAgent,
    StreamAgentError,
    StreamManager,
)
from vigilay.streaming import CloudflareStreamService, LiveInput, sanitize_secret

PUBLISH_URL = "https://customer.example/very-secret-value/webRTC/publish"
PLAYBACK_URL = "https://customer.example/live-input-id/webRTC/play"


class FakeResponse:
    status_code = 200
    content = b"response"

    def __init__(self, uid):
        self.uid = uid

    def json(self):
        return {
            "success": True,
            "result": {
                "uid": self.uid,
                "webRTC": {"url": PUBLISH_URL},
                "webRTCPlayback": {"url": PLAYBACK_URL},
            },
        }


class FakeClient:
    def __init__(self):
        self.calls = []
        self.uid = uuid4().hex

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return FakeResponse(self.uid)


def configured(service):
    service.account_id = "account-id"
    service.api_token = "api-token"
    return service


def test_cloudflare_live_input_is_created_encrypted_and_reused(cameras):
    camera_id = cameras["a"]["id"]
    client = FakeClient()
    with system_session() as db:
        camera = db.get(Camera, camera_id)
        service = configured(CloudflareStreamService(db, client=client, sleep=lambda _: None))
        created = service.get_or_create_live_input(camera)
        db.commit()
        row = db.scalar(
            select(CameraStreamProvider).where(CameraStreamProvider.camera_id == camera_id)
        )
        assert created.playback_url == PLAYBACK_URL
        assert PUBLISH_URL.encode() not in row.publish_url_encrypted
        assert decrypt_credentials(row.publish_url_encrypted, camera.tenant_id, camera.id) == {
            "publish_url": PUBLISH_URL
        }
        assert service.get_or_create_live_input(camera).publish_url == PUBLISH_URL
        assert len(client.calls) == 1


def test_sanitizer_removes_whip_and_rtsp_credentials():
    assert "very-secret-value" not in sanitize_secret(PUBLISH_URL)
    sanitized = sanitize_secret("rtsp://admin:secret@192.0.2.1/live")
    assert "admin" not in sanitized
    assert "secret" not in sanitized


class FakeProcess:
    def __init__(self, *, dies=False):
        self.dies = dies
        self.running = True
        self.terminated = False

    def wait(self, timeout=None):
        if self.dies:
            self.running = False
            return 9
        if self.running:
            raise subprocess.TimeoutExpired("ffmpeg", timeout)
        return 0

    def poll(self):
        return None if self.running else 0

    def terminate(self):
        self.terminated = True
        self.running = False

    def kill(self):
        self.running = False


def test_stream_manager_prevents_duplicate_and_stops(tmp_path):
    executable = tmp_path / "ffmpeg.exe"
    executable.write_bytes(b"test")
    processes = []

    def popen(arguments, **kwargs):
        assert isinstance(arguments, list)
        assert kwargs["shell"] is False
        process = FakeProcess()
        processes.append(process)
        return process

    manager = StreamManager(str(executable), popen=popen, startup_seconds=0.01)
    assert manager.start_stream("camera", "rtsp://source/live", PUBLISH_URL) is True
    assert manager.start_stream("camera", "rtsp://source/live", PUBLISH_URL) is False
    assert len(processes) == 1
    assert manager.is_streaming("camera") is True
    assert manager.stop_stream("camera") is True
    assert processes[0].terminated is True
    assert manager.is_streaming("camera") is False


def test_stream_manager_reports_early_ffmpeg_exit(tmp_path):
    executable = tmp_path / "ffmpeg.exe"
    executable.write_bytes(b"test")
    manager = StreamManager(
        str(executable), popen=lambda *a, **k: FakeProcess(dies=True), startup_seconds=0.01
    )
    with pytest.raises(StreamAgentError, match="arranque"):
        manager.start_stream("camera", "rtsp://source/live", PUBLISH_URL)


def test_stream_manager_reports_missing_ffmpeg(tmp_path):
    manager = StreamManager(str(tmp_path / "missing-ffmpeg.exe"), startup_seconds=0.01)
    with pytest.raises(StreamAgentError, match="FFmpeg"):
        manager.start_stream("camera", "rtsp://source/live", PUBLISH_URL)


def test_cloudflare_retries_transient_network_errors(cameras):
    class FlakyClient(FakeClient):
        def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            if len(self.calls) < 3:
                raise httpx.ConnectError("temporary")
            return FakeResponse(self.uid)

    client = FlakyClient()
    with system_session() as db:
        camera = db.get(Camera, cameras["a"]["id"])
        service = configured(CloudflareStreamService(db, client=client, sleep=lambda _: None))
        assert service.create_live_input(camera).playback_url == PLAYBACK_URL
        assert len(client.calls) == 3


def test_v380_resolver_starts_bridge_once(monkeypatch):
    from vigilay import stream_agent

    ports = iter([False, True])
    monkeypatch.setattr(stream_agent, "_port_open", lambda *a, **k: next(ports))
    started = []
    camera = SimpleNamespace(
        id="camera", name="V380", brand="V380", model="x", integration_type="V380"
    )
    source = CameraStreamResolver(v380_starter=started.append).resolve(
        camera, {"host": "192.168.1.20", "rtsp_port": 8555}
    )
    assert source == "rtsp://127.0.0.1:8555/live"
    assert started[0]["host"] == "192.168.1.20"


def test_stream_agent_rejects_plaintext_transport_in_production(monkeypatch):
    from vigilay import stream_agent

    monkeypatch.setattr(
        stream_agent,
        "settings",
        lambda: SimpleNamespace(
            app_env="production",
            redis_url="redis://example:6379/0",
            database_url="mysql+pymysql://example/db",
        ),
    )
    with pytest.raises(RuntimeError, match="rediss"):
        LocalStreamAgent._validate_transport()


def test_real_camera_ptz_is_authorized_and_executed_by_local_agent(clients, cameras):
    camera_id = cameras["a"]["id"]
    with system_session() as db:
        camera = db.get(Camera, camera_id)
        camera.integration_type = "RTSP"
        db.add(
            CameraCredential(
                tenant_id=camera.tenant_id,
                camera_id=camera.id,
                secret_encrypted=encrypt_credentials(
                    {"rtsp_url": "rtsp://user:password@192.0.2.10/live"},
                    camera.tenant_id,
                    camera.id,
                ),
            )
        )
        db.commit()
    grant = clients["a"].put(
        f"/api/v1/cameras/{camera_id}/permissions",
        json={
            "user_id": clients["operator"].get("/api/v1/me").json()["id"],
            "can_view": True,
            "can_configure": True,
        },
    )
    assert grant.status_code == 200
    queued = clients["operator"].post(
        f"/api/v1/cameras/{camera_id}/ptz", json={"action": "left", "speed": 0.5}
    )
    assert queued.status_code == 202

    class FakePtz:
        calls = []

        def move(self, camera, secret, action, speed):
            self.calls.append((camera.id, action, speed, secret["rtsp_url"]))

    agent = LocalStreamAgent(ptz=FakePtz())
    agent.reconcile()
    with system_session() as db:
        command = db.get(DeviceCommand, queued.json()["id"])
        assert command.status == "SUCCEEDED"
    assert FakePtz.calls[0][:3] == (camera_id, "left", 0.5)


def test_live_start_never_returns_publish_url(monkeypatch, clients, cameras):
    from vigilay import live_routes

    camera_id = cameras["a"]["id"]
    with system_session() as db:
        camera = db.get(Camera, camera_id)
        camera.integration_type = "RTSP"
        db.commit()

    class FakeService:
        def __init__(self, db):
            pass

        def get_or_create_live_input(self, camera):
            return LiveInput("uid", PUBLISH_URL, PLAYBACK_URL)

    monkeypatch.setattr(live_routes, "CloudflareStreamService", FakeService)

    def dispatch(action, camera_id, session_id):
        if action == "start":
            with system_session() as db:
                session = db.get(CameraStreamSession, session_id)
                session.status = "live"
                db.commit()

    monkeypatch.setattr(live_routes, "_dispatch", dispatch)
    response = clients["a"].post(f"/api/v1/cameras/{camera_id}/live/start")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["playbackUrl"] == PLAYBACK_URL
    assert "publish" not in response.text.lower()
    assert "very-secret-value" not in response.text
    assert body["viewerKey"]

    denied = clients["b"].post(f"/api/v1/cameras/{camera_id}/live/start")
    assert denied.status_code == 404

    heartbeat = clients["a"].post(
        f"/api/v1/cameras/{camera_id}/live/heartbeat",
        json={"session_id": body["sessionId"], "viewer_key": body["viewerKey"]},
    )
    assert heartbeat.status_code == 200
    stopped = clients["a"].post(
        f"/api/v1/cameras/{camera_id}/live/stop",
        json={"session_id": body["sessionId"], "viewer_key": body["viewerKey"]},
    )
    assert stopped.status_code == 200
    assert stopped.json()["status"] == "stopped"


def test_real_camera_probe_is_processed_by_local_agent(clients, cameras):
    camera_id = cameras["a"]["id"]
    with system_session() as db:
        camera = db.get(Camera, camera_id)
        camera.integration_type = "RTSP"
        db.add(
            CameraCredential(
                tenant_id=camera.tenant_id,
                camera_id=camera.id,
                secret_encrypted=encrypt_credentials(
                    {"rtsp_url": "rtsp://camera.example/live"}, camera.tenant_id, camera.id
                ),
            )
        )
        db.commit()
    response = clients["a"].post(f"/api/v1/cameras/{camera_id}/probe")
    assert response.status_code == 202, response.text
    resolver = SimpleNamespace(resolve=lambda camera, secret: secret["rtsp_url"])
    agent = LocalStreamAgent(resolver=resolver, manager=SimpleNamespace())
    with system_session() as db:
        agent._process_probe(db)
        db.commit()
        command = db.get(DeviceCommand, response.json()["id"])
        assert command.status == "SUCCEEDED"
        assert db.get(Camera, camera_id).status == "ONLINE"
        assert db.get(CameraCapability, (camera_id, "live_video")).supported is True


def test_superadmin_configures_cloudflare_from_web_encrypted(monkeypatch, clients):
    from vigilay import live_routes

    observed = {}

    class Verifier:
        def __init__(self, db, *, account_id, api_token):
            observed.update(account_id=account_id, api_token=api_token)

        def verify_credentials(self):
            return None

    monkeypatch.setattr(live_routes, "CloudflareStreamService", Verifier)
    token = "cloudflare-secret-token-123456"
    response = clients["root"].put(
        "/api/v1/admin/integrations/cloudflare",
        json={"account_id": "account-123", "api_token": token},
    )
    assert response.status_code == 200, response.text
    assert token not in response.text
    assert observed == {"account_id": "account-123", "api_token": token}
    with system_session() as db:
        row = db.scalar(
            select(IntegrationSetting).where(IntegrationSetting.provider == "cloudflare")
        )
        assert token.encode() not in row.config_encrypted
        assert decrypt_credentials(row.config_encrypted, "__system__", "cloudflare") == {
            "account_id": "account-123",
            "api_token": token,
        }
    status = clients["root"].get("/api/v1/admin/integrations/cloudflare")
    assert status.json() == {"configured": True, "source": "vigilay", "tokenStored": True}
    assert clients["a"].get("/api/v1/admin/integrations/cloudflare").status_code == 403
