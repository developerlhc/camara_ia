"""Authenticated site gateway for Frigate over an outbound Cloudflare Quick Tunnel."""

from __future__ import annotations

import hmac
import json
import logging
import os
import queue
import re
import secrets
import signal
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from cryptography.exceptions import InvalidTag
from sqlalchemy import select

from vigilay.config import settings
from vigilay.db import system_session
from vigilay.models import FrigateConnection, Site, Tenant, utcnow
from vigilay.security import decrypt_credentials, encrypt_credentials

logger = logging.getLogger("vigilay.frigate_gateway")
TUNNEL_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
SAFE_PATHS = (
    re.compile(r"^/api/config$"),
    re.compile(r"^/api/events(?:/[A-Za-z0-9_.-]+(?:/(?:thumbnail\.jpg|clip\.mp4))?)?$"),
    re.compile(r"^/api/[A-Za-z0-9_-]+/recordings$"),
    re.compile(r"^/api/[A-Za-z0-9_-]+/start/\d+/end/\d+/clip\.mp4$"),
)


def load_scope():
    path = Path(os.getenv("VIGILAY_LOCAL_IDENTITY_PATH", ".local/vigilay-local.json"))
    try:
        identity = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError("Configura primero la empresa y sede en Vigilay Local") from exc
    tenant_id, site_id = identity.get("tenant_id"), identity.get("site_id")
    with system_session() as db:
        tenant, site = db.get(Tenant, tenant_id), db.get(Site, site_id)
        if tenant is None or tenant.status != "ACTIVE":
            raise RuntimeError("La empresa de Vigilay Local no existe o está inactiva")
        if site is None or site.tenant_id != tenant.id:
            raise RuntimeError("La sede de Vigilay Local no pertenece a la empresa")
    return tenant_id, site_id


def publish_connection(tenant_id, site_id, endpoint_url, status):
    with system_session() as db:
        row = db.scalar(select(FrigateConnection).where(FrigateConnection.site_id == site_id))
        if row is None:
            row = FrigateConnection(tenant_id=tenant_id, site_id=site_id)
            db.add(row)
        elif row.tenant_id != tenant_id:
            raise RuntimeError("La conexión Frigate registrada pertenece a otra empresa")
        row.endpoint_url = endpoint_url
        row.status = status
        row.last_seen_at = utcnow()
        db.commit()


def load_or_create_gateway_token(tenant_id, site_id):
    with system_session() as db:
        row = db.scalar(select(FrigateConnection).where(FrigateConnection.site_id == site_id))
        if row is None:
            row = FrigateConnection(tenant_id=tenant_id, site_id=site_id)
            db.add(row)
            db.flush()
        elif row.tenant_id != tenant_id:
            raise RuntimeError("La conexión Frigate registrada pertenece a otra empresa")
        if row.gateway_token_encrypted:
            try:
                return decrypt_credentials(row.gateway_token_encrypted, tenant_id, site_id)[
                    "gateway_token"
                ]
            except (InvalidTag, KeyError, ValueError) as exc:
                raise RuntimeError("No se pudo descifrar la credencial de esta sede") from exc
        token = secrets.token_urlsafe(48)
        row.gateway_token_encrypted = encrypt_credentials(
            {"gateway_token": token}, tenant_id, site_id
        )
        db.commit()
        return token


def handler_factory(token, frigate_url, timeout):
    class FrigateProxyHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):  # noqa: N802
            supplied = self.headers.get("Authorization", "")
            if not hmac.compare_digest(supplied, f"Bearer {token}"):
                return self._error(401, b"Unauthorized")
            parsed = urlsplit(self.path)
            if not any(pattern.fullmatch(parsed.path) for pattern in SAFE_PATHS):
                return self._error(404, b"Not found")
            headers = {}
            if self.headers.get("Range"):
                headers["Range"] = self.headers["Range"]
            try:
                with httpx.stream(
                    "GET",
                    f"{frigate_url.rstrip('/')}{parsed.path}",
                    params=parsed.query,
                    headers=headers,
                    timeout=timeout,
                ) as response:
                    self.send_response(response.status_code)
                    for name in (
                        "content-type",
                        "content-length",
                        "content-range",
                        "accept-ranges",
                    ):
                        if response.headers.get(name):
                            self.send_header(name, response.headers[name])
                    self.send_header("Cache-Control", "private, no-store")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    for chunk in response.iter_bytes():
                        self.wfile.write(chunk)
            except (httpx.HTTPError, OSError):
                if not self.wfile.closed:
                    self.close_connection = True

        def _error(self, status, body):
            self.send_response(status)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    return FrigateProxyHandler


class Gateway:
    def __init__(self):
        config = settings()
        self.tenant_id, self.site_id = load_scope()
        self.port = config.frigate_gateway_port
        self.token = load_or_create_gateway_token(self.tenant_id, self.site_id)
        self.frigate_url = config.frigate_api_url
        self.cloudflared = config.cloudflared_path
        self.timeout = config.frigate_timeout_seconds
        self.stop_event = threading.Event()
        self.endpoint_url = ""
        self.process = None
        self.lines = queue.Queue()
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", self.port),
            handler_factory(self.token, self.frigate_url, self.timeout),
        )

    def _read_output(self):
        assert self.process and self.process.stdout
        for line in self.process.stdout:
            self.lines.put(line)

    def _start_tunnel(self):
        self.process = subprocess.Popen(
            [
                self.cloudflared,
                "tunnel",
                "--no-autoupdate",
                "--url",
                f"http://127.0.0.1:{self.port}",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        threading.Thread(target=self._read_output, daemon=True).start()

    def run(self):
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        last_heartbeat = 0.0
        while not self.stop_event.is_set():
            if self.process is None or self.process.poll() is not None:
                self.endpoint_url = ""
                publish_connection(self.tenant_id, self.site_id, "", "OFFLINE")
                self._start_tunnel()
            try:
                line = self.lines.get(timeout=1)
                match = TUNNEL_URL.search(line)
                if match and match.group(0) != self.endpoint_url:
                    self.endpoint_url = match.group(0)
                    logger.info("Frigate gateway connected for site %s", self.site_id)
            except queue.Empty:
                pass
            now = time.monotonic()
            if now - last_heartbeat >= 10:
                status = "ONLINE" if self.endpoint_url else "STARTING"
                publish_connection(self.tenant_id, self.site_id, self.endpoint_url, status)
                last_heartbeat = now
        self.close()

    def close(self):
        self.stop_event.set()
        self.server.shutdown()
        if self.process and self.process.poll() is None:
            self.process.terminate()
        publish_connection(self.tenant_id, self.site_id, "", "OFFLINE")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    gateway = Gateway()

    def shutdown(*_):
        gateway.stop_event.set()

    for signal_name in ("SIGINT", "SIGTERM"):
        if hasattr(signal, signal_name):
            signal.signal(getattr(signal, signal_name), shutdown)
    gateway.run()


if __name__ == "__main__":
    main()
