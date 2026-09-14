import secrets
from datetime import timedelta
from uuid import uuid4

import pytest
from cryptography.exceptions import InvalidTag
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from vigilay.config import settings
from vigilay.db import ScopedSession, engine, system_session, tenant_session
from vigilay.main import create_app
from vigilay.models import (
    AuditLog,
    Camera,
    CameraCredential,
    CameraPermission,
    LoginSession,
    PasswordReset,
    Site,
    Tenant,
    User,
    UserRole,
    utcnow,
)
from vigilay.security import decrypt_credentials, encrypt_credentials, hash_token
from vigilay.worker import process_one


def test_login_and_logout_are_real_revocable_sessions(clients, identities):
    client = clients["a"]
    cookie = client.cookies.get("vigilay_session")
    me = client.get("/api/v1/me")
    assert me.status_code == 200 and me.json()["tenant_id"] == identities["tenants"][0]
    with system_session() as db:
        session = db.scalar(
            select(LoginSession).where(LoginSession.token_hash == hash_token(cookie))
        )
        assert session and session.token_hash != cookie
        assert db.get(User, identities["users"]["a"].id).password_hash.startswith("$argon2id$")
    assert client.post("/api/v1/auth/logout").status_code == 204
    client.cookies.set("vigilay_session", cookie)
    assert client.get("/api/v1/me").status_code == 401


def test_csrf_origin_and_unauthenticated_access(clients):
    anonymous = TestClient(create_app())
    assert anonymous.get("/api/v1/cameras").status_code == 401
    assert (
        clients["a"].post("/api/v1/auth/logout", headers={"x-csrf-token": "bad"}).status_code == 403
    )
    assert (
        clients["a"]
        .post("/api/v1/auth/logout", headers={"origin": "https://attacker.example"})
        .status_code
        == 403
    )
    assert clients["a"].get("/api/v1/me").status_code == 200


def test_session_fixation_rotation(clients, identities):
    client = clients["a"]
    old = client.cookies.get("vigilay_session")
    response = client.post(
        "/api/v1/auth/login",
        json={"identifier": identities["users"]["a"].email, "password": identities["password"]},
    )
    assert response.status_code == 200
    assert client.cookies.get("vigilay_session") != old
    with system_session() as db:
        assert db.scalar(
            select(LoginSession).where(LoginSession.token_hash == hash_token(old))
        ).revoked_at


@pytest.mark.parametrize("suffix", ["", "/settings", "/capabilities", "/commands"])
def test_cross_tenant_camera_reads_denied(clients, cameras, suffix):
    response = clients["a"].get(f"/api/v1/cameras/{cameras['b']['id']}{suffix}")
    assert response.status_code == 404
    assert cameras["b"]["name"] not in response.text


def test_cross_tenant_lists_sites_users_and_audit(clients, identities, cameras):
    assert {c["id"] for c in clients["a"].get("/api/v1/cameras").json()} == {cameras["a"]["id"]}
    for path in ["/users", "/sites", "/audit"]:
        response = clients["a"].get("/api/v1" + path)
        assert response.status_code == 200, response.text
        assert all(r["tenant_id"] == identities["tenants"][0] for r in response.json())
    assert clients["a"].get("/api/v1/sites/" + cameras["b"]["site_id"]).status_code == 404
    assert clients["a"].get("/api/v1/tenants/" + identities["tenants"][1]).status_code == 404


def test_server_pagination_search_and_tenant_filter(clients, identities, cameras):
    response = clients["root"].get(
        "/api/v1/cameras",
        params={"paged": "true", "page": 1, "page_size": 5, "q": "Cámara a"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["page"] == 1 and body["pageSize"] == 5
    assert body["total"] >= 1 and body["pages"] >= 1
    assert all("cámara a" in row["name"].lower() for row in body["items"])

    own = clients["a"].get(
        "/api/v1/cameras",
        params={"paged": "true", "tenant_id": identities["tenants"][0]},
    )
    assert own.status_code == 200
    assert {row["id"] for row in own.json()["items"]} == {cameras["a"]["id"]}
    denied = clients["a"].get(
        "/api/v1/cameras",
        params={"paged": "true", "tenant_id": identities["tenants"][1]},
    )
    assert denied.status_code == 404


def test_cross_tenant_writes_and_escalation_denied(clients, identities, cameras):
    a, b = identities["tenants"]
    assert clients["a"].post("/api/v1/tenants", json={"name": "Escalation"}).status_code == 403
    assert (
        clients["a"]
        .post("/api/v1/sites", json={"name": "Wrong tenant", "tenant_id": b})
        .status_code
        == 404
    )
    assert (
        clients["a"]
        .post(
            "/api/v1/cameras",
            json={
                "name": "Wrong site",
                "tenant_id": a,
                "site_id": cameras["b"]["site_id"],
                "integration_type": "SIMULATOR",
            },
        )
        .status_code
        == 404
    )
    assert clients["a"].post(f"/api/v1/cameras/{cameras['b']['id']}/probe").status_code == 404
    assert (
        clients["a"]
        .put(f"/api/v1/cameras/{cameras['b']['id']}/settings", json={"motion_sensitivity": 70})
        .status_code
        == 404
    )
    payload = {
        "tenant_id": a,
        "email": "intruder@example.com",
        "username": "intruder",
        "password": "fake-test-password",
        "role": "SUPER_ADMIN",
    }
    response = clients["a"].post("/api/v1/users", json=payload)
    assert response.status_code == 422 and payload["password"] not in response.text
    assert (
        clients["viewer"].post("/api/v1/sites", json={"name": "No", "tenant_id": a}).status_code
        == 403
    )


def test_camera_grants_required_even_for_same_tenant(clients, identities, cameras):
    path = f"/api/v1/cameras/{cameras['a']['id']}"
    assert clients["viewer"].get(path).status_code == 404
    assert clients["operator"].get(path).status_code == 404
    response = clients["a"].put(
        path + "/permissions",
        json={
            "user_id": identities["users"]["operator"].id,
            "can_view": True,
            "can_configure": False,
        },
    )
    assert response.status_code == 200
    assert clients["operator"].get(path).status_code == 200
    assert clients["operator"].post(path + "/probe").status_code == 403
    response = clients["a"].put(
        path + "/permissions",
        json={
            "user_id": identities["users"]["viewer"].id,
            "can_view": False,
            "can_configure": True,
        },
    )
    assert response.status_code == 200
    grants = clients["a"].get(path + "/permissions")
    assert grants.status_code == 200
    by_user = {grant["user_id"]: grant for grant in grants.json()}
    assert by_user[identities["users"]["operator"].id]["can_view"] is True
    assert by_user[identities["users"]["viewer"].id]["can_view"] is True
    assert by_user[identities["users"]["viewer"].id]["can_configure"] is True
    assert (
        clients["a"]
        .put(
            path + "/permissions",
            json={"user_id": identities["users"]["b"].id, "can_view": True, "can_configure": True},
        )
        .status_code
        == 404
    )


def test_repository_layer_denies_missing_scope_and_cross_tenant_writes(identities, cameras):
    with ScopedSession(engine()) as db:
        with pytest.raises(PermissionError):
            db.scalars(select(Camera)).all()
    a, b = identities["tenants"]
    with tenant_session(a) as db:
        assert db.get(Tenant, b) is None
        assert db.get(Camera, cameras["b"]["id"]) is None
        assert all(c.tenant_id == a for c in db.scalars(select(Camera)))
        with pytest.raises(PermissionError):
            db.execute(text("SELECT * FROM cameras"))
        db.add(Site(tenant_id=b, name="Forbidden"))
        with pytest.raises(PermissionError):
            db.flush()


def test_mysql_composite_foreign_key_prevents_wrong_site(identities, cameras):
    with system_session() as db:
        db.add(
            Camera(
                tenant_id=identities["tenants"][0],
                site_id=cameras["b"]["site_id"],
                name="Invalid",
                integration_type="RTSP",
            )
        )
        with pytest.raises(IntegrityError):
            db.flush()


def test_credentials_encrypted_and_never_serialized(clients, cameras):
    camera = cameras["a"]
    uri = "rtsp://testing:synthetic-secret@192.0.2.10:554/live"
    response = clients["a"].post(
        "/api/v1/cameras",
        json={
            "name": "Protected",
            "tenant_id": camera["tenant_id"],
            "site_id": camera["site_id"],
            "integration_type": "RTSP",
            "rtsp_url": uri,
        },
    )
    assert response.status_code == 201
    camera_id = response.json()["id"]
    assert uri not in response.text and "secret" not in response.text
    with system_session() as db:
        stored = db.scalar(select(CameraCredential).where(CameraCredential.camera_id == camera_id))
        assert uri.encode() not in stored.secret_encrypted
        assert (
            decrypt_credentials(stored.secret_encrypted, camera["tenant_id"], camera_id)["rtsp_url"]
            == uri
        )
    invalid = clients["a"].post("/api/v1/cameras", json={"secret": uri})
    assert invalid.status_code == 422 and uri not in invalid.text


def test_encryption_bound_to_tenant_and_camera():
    encoded = encrypt_credentials({"password": "synthetic"}, "a", "camera")
    with pytest.raises(InvalidTag):
        decrypt_credentials(encoded, "b", "camera")
    with pytest.raises(InvalidTag):
        decrypt_credentials(encoded[:-1] + bytes([encoded[-1] ^ 1]), "a", "camera")


def drain_queue():
    for _ in range(100):
        if not process_one():
            return
    raise AssertionError("Unexpected queue backlog")


def test_simulated_device_commands_verify_actual_readback(clients, cameras):
    path = "/api/v1/cameras/" + cameras["a"]["id"]
    assert clients["a"].put(path + "/settings", json={"motion_sensitivity": 70}).status_code == 409
    assert clients["a"].post(path + "/probe").status_code == 202
    assert clients["a"].post(path + "/probe").status_code == 409
    drain_queue()
    assert clients["a"].get(path).json()["status"] == "ONLINE"
    cap = clients["a"].get(path + "/capabilities").json()[0]
    assert cap["writable"] and cap["metadata"]["simulated"]
    assert clients["a"].put(path + "/settings", json={"motion_sensitivity": 70}).status_code == 202
    assert clients["a"].get(path + "/settings").json()[0]["status"] == "PENDING"
    drain_queue()
    setting = clients["a"].get(path + "/settings").json()[0]
    assert setting == {
        "key": "motion_sensitivity",
        "desired": 70,
        "reported": 70,
        "status": "SYNCED",
    }
    assert clients["a"].get(path + "/commands").json()[0]["status"] == "SUCCEEDED"
    assert clients["a"].put(path + "/settings", json={"motion_sensitivity": 101}).status_code == 422
    assert (
        clients["a"]
        .put(path + "/settings", json={"motion_sensitivity": 20, "restart": True})
        .status_code
        == 422
    )
    with Redis.from_url(settings().redis_url) as redis:
        redis.hset("vigilay:simulator:" + cameras["a"]["id"], "motion_sensitivity", "15")
    assert clients["a"].post(path + "/probe").status_code == 202
    drain_queue()
    assert clients["a"].get(path + "/settings").json()[0]["status"] == "DRIFTED"


def test_simulated_offline_failure(clients, cameras):
    path = "/api/v1/cameras/" + cameras["a"]["id"]
    with Redis.from_url(settings().redis_url) as cache:
        cache.hset("vigilay:simulator:" + cameras["a"]["id"], "offline", "1")
    response = clients["a"].post(path + "/probe")
    assert response.status_code == 202
    drain_queue()
    assert clients["a"].get(path + "/commands").json()[0]["status"] == "FAILED"
    assert clients["a"].get(path).json()["status"] == "OFFLINE"


def test_password_reset_single_use_and_session_revocation(clients, identities):
    token = secrets.token_urlsafe(48)
    with system_session() as db:
        db.add(
            PasswordReset(
                user_id=identities["users"]["a"].id,
                token_hash=hash_token(token),
                expires_at=utcnow() + timedelta(minutes=15),
            )
        )
        db.commit()
    payload = {"token": token, "new_password": secrets.token_urlsafe(20)}
    response = clients["a"].post("/api/v1/auth/reset-password", json=payload)
    assert response.status_code == 204
    assert clients["a"].get("/api/v1/me").status_code == 401
    assert clients["a"].post("/api/v1/auth/reset-password", json=payload).status_code == 400


def test_user_disable_revokes_sessions(clients, identities):
    response = clients["root"].put(
        "/api/v1/users/" + identities["users"]["a"].id,
        json={"first_name": "Test", "last_name": "", "status": "DISABLED", "role": "CLIENT_ADMIN"},
    )
    assert response.status_code == 200
    assert clients["a"].get("/api/v1/me").status_code == 401


def test_account_lock_and_sql_injection(identities):
    client = TestClient(create_app(), client=(uuid4().hex, 5000))
    client.headers["origin"] = "http://localhost:3000"
    for _ in range(5):
        assert (
            client.post(
                "/api/v1/auth/login",
                json={"identifier": identities["users"]["a"].email, "password": "wrong"},
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"identifier": identities["users"]["a"].email, "password": identities["password"]},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auth/login", json={"identifier": "' OR 1=1 --", "password": "wrong"}
        ).status_code
        == 401
    )


def test_shared_login_rate_limit(identities):
    ip = uuid4().hex
    with Redis.from_url(settings().redis_url) as redis:
        redis.set("vigilay:ratelimit:login:" + hash_token(ip), 30, ex=60)
    client = TestClient(create_app(), client=(ip, 5000))
    response = client.post(
        "/api/v1/auth/login",
        headers={"origin": "http://localhost:3000"},
        json={"identifier": "random", "password": "wrong"},
    )
    assert response.status_code == 429 and "Retry-After" in response.headers


def test_data_survives_new_app_instance(clients, cameras):
    cookie = clients["a"].cookies.get("vigilay_session")
    with TestClient(create_app()) as fresh:
        fresh.cookies.set("vigilay_session", cookie)
        assert fresh.get("/api/v1/cameras/" + cameras["a"]["id"]).status_code == 200
    with system_session() as db:
        assert db.scalar(select(AuditLog).where(AuditLog.resource_id == cameras["a"]["id"]))


def test_mysql_rejects_cross_tenant_grants_and_global_role(identities, cameras):
    with system_session() as db:
        db.add(
            CameraPermission(
                tenant_id=identities["tenants"][0],
                user_id=identities["users"]["a"].id,
                camera_id=cameras["b"]["id"],
                can_view=True,
            )
        )
        with pytest.raises(IntegrityError):
            db.flush()
    with system_session() as db:
        role = db.get(UserRole, identities["users"]["a"].id)
        role.role_name = "SUPER_ADMIN"
        with pytest.raises(OperationalError) as exc:
            db.flush()
        assert exc.value.orig.args[0] == 3819  # MySQL CHECK violation, not a connection failure.


def test_suspended_tenant_loses_access_immediately(clients, identities):
    tenant_id = identities["tenants"][0]
    result = clients["root"].put(
        "/api/v1/tenants/" + tenant_id, json={"name": "Suspendido", "status": "SUSPENDED"}
    )
    assert result.status_code == 200
    assert clients["a"].get("/api/v1/me").status_code == 403
    assert clients["a"].get("/api/v1/cameras").status_code == 403
