import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import vigilay.frigate_routes as frigate_routes
from sqlalchemy import select
from vigilay.db import system_session
from vigilay.frigate import FrigateError, FrigateService, recording_windows
from vigilay.models import Camera, FrigateConnection, Site, utcnow
from vigilay.security import frigate_gateway_token

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import camera_store  # noqa: E402


class FakeFrigate:
    @classmethod
    def for_site(cls, db, tenant_id, site_id, *, client=None):
        return cls()

    def camera_names(self):
        return {"camera_a", "camera_b"}

    def events(self, *, limit=200):
        return [
            {"id": "event-a", "camera": "camera_a", "label": "person", "has_snapshot": True},
            {"id": "event-b", "camera": "camera_b", "label": "car", "has_snapshot": True},
        ]


def test_frigate_events_are_filtered_by_tenant(monkeypatch, clients, cameras):
    monkeypatch.setattr(frigate_routes, "FrigateService", FakeFrigate)
    with system_session() as db:
        camera_a = db.get(Camera, cameras["a"]["id"])
        camera_b = db.get(Camera, cameras["b"]["id"])
        camera_a.frigate_camera_name = "camera_a"
        camera_b.frigate_camera_name = "camera_b"
        db.commit()

    response = clients["a"].get("/api/v1/frigate/events")
    assert response.status_code == 200
    assert [event["id"] for event in response.json()] == ["event-a"]
    assert response.json()[0]["camera_id"] == cameras["a"]["id"]


def test_vigilay_local_frigate_catalog_requires_private_key(monkeypatch, clients, cameras):
    monkeypatch.setattr(frigate_routes, "FrigateService", FakeFrigate)
    monkeypatch.setattr(
        frigate_routes, "settings", lambda: SimpleNamespace(internal_proxy_secret="local-key")
    )
    path = f"/api/v1/frigate/internal/cameras?site_id={cameras['a']['site_id']}"
    assert clients["root"].get(path).status_code == 404
    response = clients["root"].get(path, headers={"x-vigilay-local-key": "local-key"})
    assert response.status_code == 200
    assert response.json() == [{"name": "camera_a"}, {"name": "camera_b"}]


def test_same_frigate_source_cannot_be_assigned_twice_in_a_site(
    monkeypatch, clients, cameras, identities
):
    monkeypatch.setattr(frigate_routes, "FrigateService", FakeFrigate)
    camera = cameras["a"]
    linked = clients["a"].put(
        f"/api/v1/frigate/cameras/{camera['id']}",
        json={"frigate_camera_name": "camera_a"},
    )
    assert linked.status_code == 200, linked.text

    second = clients["a"].post(
        "/api/v1/cameras",
        json={
            "name": "Duplicada",
            "tenant_id": identities["tenants"][0],
            "site_id": camera["site_id"],
            "integration_type": "SIMULATOR",
        },
    )
    assert second.status_code == 201, second.text
    duplicate = clients["a"].put(
        f"/api/v1/frigate/cameras/{second.json()['id']}",
        json={"frigate_camera_name": "camera_a"},
    )
    assert duplicate.status_code == 409


def test_local_camera_can_be_read_and_reassigned(monkeypatch, tmp_path, cameras, identities):
    monkeypatch.setattr(camera_store, "LOCAL_IDENTITY_PATH", tmp_path / "identity.json")
    scope = camera_store.configure_local_scope(
        tenant_id=identities["tenants"][0], site_id=cameras["a"]["site_id"]
    )
    assert scope["site_id"] == cameras["a"]["site_id"]
    created = camera_store.save_camera(
        name="Local RTSP",
        brand="IMOU",
        model="Prueba",
        integration_type="RTSP",
        secret={"rtsp_url": "rtsp://camera.local/live", "onvif_port": 80},
        frigate_camera_name="camera_a",
    )
    assert camera_store.get_runtime_camera(created["id"])["frigate_camera_name"] == "camera_a"

    updated = camera_store.update_camera(
        created["id"],
        name="Local RTSP",
        model="Prueba",
        frigate_camera_name="camera_b",
    )
    assert updated["frigate_camera_name"] == "camera_b"


def test_recording_segments_are_grouped_into_playable_windows():
    result = recording_windows(
        [
            {"start_time": 100, "end_time": 120, "motion": 1, "objects": 2},
            {"start_time": 122, "end_time": 140, "motion": 3, "objects": 4},
            {"start_time": 200, "end_time": 220, "motion": 5, "objects": 6},
        ]
    )
    assert result == [
        {"start": 200.0, "end": 220.0, "motion": 5, "objects": 6, "duration": 20.0},
        {"start": 100.0, "end": 140.0, "motion": 4, "objects": 6, "duration": 40.0},
    ]


def test_site_frigate_connection_is_authenticated(cameras):
    camera = cameras["a"]

    def respond(request):
        assert request.headers["authorization"] == (
            "Bearer " + frigate_gateway_token(camera["tenant_id"], camera["site_id"])
        )
        return httpx.Response(200, json={"cameras": {"imou": {}}})

    client = httpx.Client(transport=httpx.MockTransport(respond))
    with system_session() as db:
        db.add(
            FrigateConnection(
                tenant_id=camera["tenant_id"],
                site_id=camera["site_id"],
                endpoint_url="https://site.trycloudflare.com",
                status="ONLINE",
                last_seen_at=utcnow(),
            )
        )
        db.commit()
        assert FrigateService.for_site(
            db, camera["tenant_id"], camera["site_id"], client=client
        ).camera_names() == {"imou"}
    client.close()


def test_stale_site_frigate_connection_is_rejected(cameras):
    camera = cameras["b"]
    with system_session() as db:
        db.add(
            FrigateConnection(
                tenant_id=camera["tenant_id"],
                site_id=camera["site_id"],
                endpoint_url="https://stale.trycloudflare.com",
                status="ONLINE",
                last_seen_at=utcnow() - timedelta(minutes=2),
            )
        )
        db.commit()
        with pytest.raises(FrigateError, match="desconectado"):
            FrigateService.for_site(db, camera["tenant_id"], camera["site_id"])


def test_local_scope_rejects_site_from_another_company(monkeypatch, tmp_path, clients, identities):
    monkeypatch.setattr(camera_store, "LOCAL_IDENTITY_PATH", tmp_path / "identity.json")
    sites = []
    for key, tenant_id in zip(("a", "b"), identities["tenants"]):
        response = clients[key].post(
            "/api/v1/sites", json={"name": f"Local {key}", "tenant_id": tenant_id}
        )
        assert response.status_code == 201
        sites.append(response.json()["id"])

    try:
        camera_store.configure_local_scope(tenant_id=identities["tenants"][0], site_id=sites[1])
    except ValueError as exc:
        assert "no pertenece" in str(exc)
    else:
        raise AssertionError("Una sede cruzada no debe configurar Vigilay Local")

    configured = camera_store.configure_local_scope(
        tenant_id=identities["tenants"][0], site_id=sites[0]
    )
    assert configured["tenant_id"] == identities["tenants"][0]
    with system_session() as db:
        assert db.scalar(select(Site).where(Site.id == configured["site_id"])) is not None
