from types import SimpleNamespace
from uuid import uuid4

from vigilay.db import engine, system_session
from vigilay.models import Camera, CameraCredential, CameraStreamProvider, CameraStreamSession
from vigilay.security import encrypt_credentials
from vigilay.stream_agent import LocalStreamAgent


def test_rtsp_start_releases_pool_and_never_resurrects_closed_viewer(clients, cameras):
    camera = cameras["a"]
    camera_id, tenant_id = camera["id"], camera["tenant_id"]
    actor_id = clients["a"].get("/api/v1/me").json()["id"]
    with system_session() as db:
        db.get(Camera, camera_id).integration_type = "RTSP"
        db.add(
            CameraCredential(
                tenant_id=tenant_id,
                camera_id=camera_id,
                secret_encrypted=encrypt_credentials(
                    {"rtsp_url": "rtsp://test/live"}, tenant_id, camera_id
                ),
            )
        )
        db.add(
            CameraStreamProvider(
                tenant_id=tenant_id,
                camera_id=camera_id,
                provider="cloudflare",
                provider_live_input_uid=camera_id,
                publish_url_encrypted=encrypt_credentials(
                    {"publish_url": "https://test/publish"}, tenant_id, camera_id
                ),
                playback_url="https://test/play",
            )
        )
        session = CameraStreamSession(
            tenant_id=tenant_id,
            camera_id=camera_id,
            user_id=actor_id,
            viewer_key_hash=uuid4().hex,
            status="starting",
        )
        db.add(session)
        db.commit()
        session_id = session.id
    observed = []

    def resolve(*args):
        observed.append(engine().pool.checkedout())
        # A viewer may leave while the camera/WHIP connection is being negotiated.
        with system_session() as db:
            db.get(CameraStreamSession, session_id).status = "stopped"
            db.commit()
        return "rtsp://test/live"

    def start(*args):
        observed.append(engine().pool.checkedout())

    agent = LocalStreamAgent(
        resolver=SimpleNamespace(resolve=resolve),
        manager=SimpleNamespace(
            is_streaming=lambda _: False, start_stream=start, camera_ids=lambda: []
        ),
    )
    original = agent._active_sessions
    agent._active_sessions = lambda db, camera_id=None: original(db, camera["id"])
    agent.reconcile_live()
    assert observed == [0, 0]
    with system_session() as db:
        assert db.get(CameraStreamSession, session_id).status == "stopped"
