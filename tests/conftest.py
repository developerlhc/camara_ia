import os
import secrets
from urllib.parse import quote_plus
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from dotenv import dotenv_values
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

# Tests always use a separate, explicitly named MySQL schema and Redis database.
local = dotenv_values(".env")
test_url = os.getenv("TEST_DATABASE_URL") or local.get("TEST_DATABASE_URL")
if not test_url:
    if local.get("DATABASE_URL"):
        base_url = make_url(local["DATABASE_URL"])
    else:
        legacy = {
            key.strip().lower(): value.strip()
            for item in local.get("BDMYSQL", "").split(";")
            if "=" in item
            for key, value in [item.split("=", 1)]
        }
        base_url = make_url(
            "mysql+pymysql://{}:{}@{}:{}/vigilay?charset=utf8mb4".format(
                quote_plus(legacy["uid"]),
                quote_plus(legacy["pwd"]),
                legacy["server"],
                legacy.get("port", "3306"),
            )
        )
    test_url = base_url.set(database="vigilay_test").render_as_string(hide_password=False)
if not make_url(test_url).database.endswith("_test"):
    raise RuntimeError("Las pruebas requieren una base cuyo nombre termine en _test")
os.environ["DATABASE_URL"] = test_url
# BDMYSQL has priority in application settings. Clear it explicitly so pytest
# cannot reconnect to the development database after deriving vigilay_test.
os.environ["BDMYSQL"] = ""
os.environ["REDIS_URL"] = os.getenv("TEST_REDIS_URL", "redis://localhost:6379/1")
os.environ["SESSION_SECRET"] = secrets.token_hex(32)
os.environ["CREDENTIAL_ENCRYPTION_KEY"] = (
    local.get("CREDENTIAL_ENCRYPTION_KEY") or os.environ["CREDENTIAL_ENCRYPTION_KEY"]
)
os.environ["ENABLE_SIMULATOR"] = "true"
os.environ["WEB_ORIGIN"] = "http://localhost:3000"

from vigilay.config import settings  # noqa: E402

settings.cache_clear()
if not make_url(settings().database_url).database.endswith("_test"):
    raise RuntimeError("La configuración efectiva de pytest debe terminar en _test")
from vigilay.db import system_session  # noqa: E402
from vigilay.main import create_app  # noqa: E402
from vigilay.models import Tenant, User, UserRole  # noqa: E402
from vigilay.security import hasher  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def migrate():
    command.upgrade(Config("alembic.ini"), "head")


@pytest.fixture
def identities(migrate):
    password = secrets.token_urlsafe(20)
    with system_session() as db:
        a, b = Tenant(name="Test A " + uuid4().hex), Tenant(name="Test B " + uuid4().hex)
        db.add_all([a, b])
        db.flush()
        users = {}
        for key, tenant, role in [
            ("root", None, "SUPER_ADMIN"),
            ("a", a.id, "CLIENT_ADMIN"),
            ("b", b.id, "CLIENT_ADMIN"),
            ("viewer", a.id, "VIEWER"),
            ("operator", a.id, "OPERATOR"),
        ]:
            name = uuid4().hex
            user = User(
                tenant_id=tenant,
                email=name + "@example.com",
                username=name,
                password_hash=hasher.hash(password),
            )
            db.add(user)
            db.flush()
            db.add(UserRole(tenant_id=tenant, user_id=user.id, role_name=role))
            users[key] = user
        db.commit()
        return {"tenants": [a.id, b.id], "users": users, "password": password}


@pytest.fixture
def clients(identities):
    result = {}
    for key, user in identities["users"].items():
        client = TestClient(create_app(), client=(uuid4().hex, 50000))
        client.headers["origin"] = "http://localhost:3000"
        response = client.post(
            "/api/v1/auth/login",
            json={"identifier": user.email, "password": identities["password"]},
        )
        assert response.status_code == 200, response.text
        client.headers["x-csrf-token"] = response.json()["csrf_token"]
        result[key] = client
    yield result
    for client in result.values():
        client.close()


@pytest.fixture
def cameras(clients, identities):
    result = {}
    for key, tenant_id in zip(["a", "b"], identities["tenants"]):
        site = clients[key].post(
            "/api/v1/sites", json={"name": "Sede " + key, "tenant_id": tenant_id}
        )
        assert site.status_code == 201, site.text
        camera = clients[key].post(
            "/api/v1/cameras",
            json={
                "name": "Cámara " + key,
                "tenant_id": tenant_id,
                "site_id": site.json()["id"],
                "integration_type": "SIMULATOR",
            },
        )
        assert camera.status_code == 201, camera.text
        result[key] = camera.json()
    return result
