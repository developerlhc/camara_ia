from starlette.websockets import WebSocketDisconnect
from vigilay.db import system_session
from vigilay.models import FrigateConnection
from vigilay.realtime_hub import notify_site
from vigilay.security import encrypt_credentials


def test_realtime_camera_snapshot_is_authenticated_and_tenant_scoped(clients, cameras):
    with clients["a"].websocket_connect(
        "/api/v1/realtime", headers={"origin": "http://localhost:3000"}
    ) as socket:
        assert socket.receive_json() == {"type": "ready"}
        socket.send_json({"type": "subscribe", "cameraId": cameras["a"]["id"]})
        snapshot = socket.receive_json()
        assert snapshot["type"] == "snapshot"
        assert snapshot["camera"]["id"] == cameras["a"]["id"]
        assert snapshot["camera"]["status"] == "UNVERIFIED"

        socket.send_json({"type": "subscribe", "cameraId": cameras["b"]["id"]})
        assert socket.receive_json() == {"type": "error", "detail": "Cámara no encontrada"}
        try:
            socket.receive_json()
        except WebSocketDisconnect as exc:
            assert exc.code == 4404


def test_realtime_rejects_untrusted_origin(clients):
    try:
        with clients["a"].websocket_connect(
            "/api/v1/realtime", headers={"origin": "https://attacker.example"}
        ):
            raise AssertionError("El WebSocket no debe aceptar otro origen")
    except WebSocketDisconnect as exc:
        assert exc.code == 4403


def test_site_agent_receives_outbound_wake_signal(clients, cameras):
    camera = cameras["a"]
    token = "site-agent-test-token"
    with system_session() as db:
        connection = FrigateConnection(
            tenant_id=camera["tenant_id"],
            site_id=camera["site_id"],
            gateway_token_encrypted=encrypt_credentials(
                {"gateway_token": token}, camera["tenant_id"], camera["site_id"]
            ),
        )
        db.add(connection)
        db.commit()

    with clients["a"].websocket_connect("/api/v1/agent/realtime") as socket:
        socket.send_json(
            {
                "type": "authenticate",
                "tenantId": camera["tenant_id"],
                "siteId": camera["site_id"],
                "token": token,
            }
        )
        assert socket.receive_json()["type"] == "ready"
        assert socket.receive_json() == {"type": "wake", "event": "connected"}
        notify_site(camera["site_id"], "camera.command", "command-1")
        assert socket.receive_json() == {
            "type": "wake",
            "event": "camera.command",
            "resourceId": "command-1",
        }
