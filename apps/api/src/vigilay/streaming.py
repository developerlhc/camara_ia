"""Cloudflare Stream control-plane integration.

This module never logs or serializes the WHIP publishing endpoint.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx
from sqlalchemy import select

from vigilay.config import settings
from vigilay.models import CameraStreamProvider, IntegrationSetting
from vigilay.security import decrypt_credentials, encrypt_credentials

logger = logging.getLogger("vigilay.streaming")


class StreamProviderError(RuntimeError):
    """A safe-to-display provider failure without upstream response details."""


@dataclass(frozen=True)
class LiveInput:
    uid: str
    publish_url: str
    playback_url: str


def sanitize_secret(value: object) -> str:
    """Remove credentials and WHIP secrets from diagnostic strings."""
    text = str(value)
    marker = "/webRTC/publish"
    if marker in text:
        prefix = text.split(marker, 1)[0]
        origin = prefix.split("/", 3)[:3]
        text = "/".join(origin) + "/[REDACTED]" + marker
    if "://" in text and "@" in text:
        scheme, remainder = text.split("://", 1)
        text = scheme + "://[REDACTED]@" + remainder.split("@", 1)[1]
    return text


class CloudflareStreamService:
    base_url = "https://api.cloudflare.com/client/v4"
    transient_statuses = {408, 425, 429, 500, 502, 503, 504}

    def __init__(self, db, *, client=None, sleep=time.sleep, account_id=None, api_token=None):
        self.db = db
        self.config = settings()
        self._client = client
        self._sleep = sleep
        self.account_id = account_id
        self.api_token = api_token
        if not self.account_id and not self.api_token:
            row = self.db.scalar(
                select(IntegrationSetting).where(
                    IntegrationSetting.provider == "cloudflare",
                    IntegrationSetting.enabled.is_(True),
                )
            )
            if row:
                stored = decrypt_credentials(row.config_encrypted, "__system__", "cloudflare")
                self.account_id = stored["account_id"]
                self.api_token = stored["api_token"]
        self.account_id = self.account_id or self.config.cloudflare_account_id
        self.api_token = self.api_token or self.config.cloudflare_stream_api_token

    def _configured(self):
        if not self.account_id or not self.api_token:
            raise StreamProviderError("Cloudflare Stream no está configurado")

    def _request(self, method: str, path: str, *, json_body=None):
        self._configured()
        url = f"{self.base_url}/accounts/{self.account_id}{path}"
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }
        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=httpx.Timeout(10, connect=5))
        try:
            for attempt, delay in enumerate((0, 1, 2), start=1):
                if delay:
                    self._sleep(delay)
                try:
                    response = client.request(method, url, headers=headers, json=json_body)
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    if attempt == 3:
                        raise StreamProviderError(
                            "Cloudflare Stream no está disponible temporalmente"
                        ) from exc
                    continue
                if response.status_code in self.transient_statuses and attempt < 3:
                    continue
                if response.status_code >= 400:
                    logger.warning(
                        "Cloudflare Stream request failed method=%s status=%s",
                        method,
                        response.status_code,
                    )
                    raise StreamProviderError("Cloudflare Stream rechazó la operación")
                if response.status_code == 204 or not response.content:
                    return {}
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise StreamProviderError(
                        "Cloudflare Stream devolvió una respuesta inválida"
                    ) from exc
                if payload.get("success") is False:
                    raise StreamProviderError("Cloudflare Stream rechazó la operación")
                return payload.get("result", payload)
        finally:
            if owns_client:
                client.close()

    @staticmethod
    def _parse(result: dict) -> LiveInput:
        try:
            live_input = LiveInput(
                uid=result["uid"],
                publish_url=result["webRTC"]["url"],
                playback_url=result["webRTCPlayback"]["url"],
            )
        except (KeyError, TypeError) as exc:
            raise StreamProviderError("Cloudflare Stream no devolvió credenciales WebRTC") from exc
        if not live_input.publish_url.endswith("/webRTC/publish"):
            raise StreamProviderError("Cloudflare Stream devolvió un endpoint WHIP inválido")
        if not live_input.playback_url.endswith("/webRTC/play"):
            raise StreamProviderError("Cloudflare Stream devolvió un endpoint WHEP inválido")
        return live_input

    @staticmethod
    def _from_row(row: CameraStreamProvider) -> LiveInput:
        secret = decrypt_credentials(row.publish_url_encrypted, row.tenant_id, row.camera_id)
        return LiveInput(row.provider_live_input_uid, secret["publish_url"], row.playback_url)

    def get_or_create_live_input(self, camera) -> LiveInput:
        row = self.db.scalar(
            select(CameraStreamProvider).where(CameraStreamProvider.camera_id == camera.id)
        )
        if row is not None and row.enabled:
            return self._from_row(row)
        if row is not None:
            raise StreamProviderError("La transmisión Cloudflare de esta cámara está deshabilitada")
        return self.create_live_input(camera)

    def create_live_input(self, camera) -> LiveInput:
        result = self._request(
            "POST",
            "/stream/live_inputs",
            json_body={
                "enabled": True,
                "meta": {"name": camera.name, "vigilay_camera_id": camera.id},
                "preferLowLatency": True,
                "recording": {"mode": "off", "requireSignedURLs": False},
            },
        )
        live_input = self._parse(result)
        self.db.add(
            CameraStreamProvider(
                tenant_id=camera.tenant_id,
                camera_id=camera.id,
                provider="cloudflare",
                provider_live_input_uid=live_input.uid,
                publish_url_encrypted=encrypt_credentials(
                    {"publish_url": live_input.publish_url}, camera.tenant_id, camera.id
                ),
                playback_url=live_input.playback_url,
            )
        )
        self.db.flush()
        return live_input

    def get_live_input(self, camera) -> LiveInput:
        row = self.db.scalar(
            select(CameraStreamProvider).where(CameraStreamProvider.camera_id == camera.id)
        )
        if row is None:
            raise StreamProviderError("La cámara no tiene un Live Input")
        result = self._request("GET", f"/stream/live_inputs/{row.provider_live_input_uid}")
        live_input = self._parse(result)
        row.publish_url_encrypted = encrypt_credentials(
            {"publish_url": live_input.publish_url}, camera.tenant_id, camera.id
        )
        row.playback_url = live_input.playback_url
        return live_input

    def rotate_live_input_keys(self, camera) -> LiveInput:
        row = self.db.scalar(
            select(CameraStreamProvider).where(CameraStreamProvider.camera_id == camera.id)
        )
        if row is None:
            raise StreamProviderError("La cámara no tiene un Live Input")
        result = self._request(
            "POST", f"/stream/live_inputs/{row.provider_live_input_uid}/rotate_keys"
        )
        live_input = self._parse(result)
        row.publish_url_encrypted = encrypt_credentials(
            {"publish_url": live_input.publish_url}, camera.tenant_id, camera.id
        )
        row.playback_url = live_input.playback_url
        return live_input

    def delete_live_input(self, camera):
        row = self.db.scalar(
            select(CameraStreamProvider).where(CameraStreamProvider.camera_id == camera.id)
        )
        if row is None:
            return
        self._request("DELETE", f"/stream/live_inputs/{row.provider_live_input_uid}")
        self.db.delete(row)

    def verify_credentials(self):
        self._request("GET", "/stream/live_inputs?per_page=1")
