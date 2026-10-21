"""Cliente del servicio local de grabaciones propio de Vigilay."""

from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlsplit

import httpx
from cryptography.exceptions import InvalidTag
from sqlalchemy import select

from vigilay.config import settings
from vigilay.models import RecorderConnection, utcnow
from vigilay.security import decrypt_credentials


class MediaError(RuntimeError):
    pass


@dataclass
class MediaStream:
    response: httpx.Response
    client: httpx.Client
    owns_client: bool

    def close(self):
        self.response.close()
        if self.owns_client:
            self.client.close()

    def chunks(self):
        try:
            yield from self.response.iter_raw()
        finally:
            self.close()

    @property
    def headers(self):
        allowed = (
            "content-type",
            "content-length",
            "content-range",
            "accept-ranges",
            "etag",
            "last-modified",
        )
        return {
            name: self.response.headers[name] for name in allowed if name in self.response.headers
        }


class LocalMediaService:
    def __init__(self, *, base_url=None, gateway_token="", client=None):
        config = settings()
        self.base_url = (base_url or config.recording_api_url).rstrip("/")
        parsed = urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise MediaError("La dirección de Vigilay Recorder no es válida")
        if (
            base_url
            and config.app_env == "production"
            and (parsed.scheme != "https" or not parsed.hostname.endswith(".trycloudflare.com"))
        ):
            raise MediaError("El endpoint publicado por Vigilay Recorder no es válido")
        self.timeout = config.recording_timeout_seconds
        self.headers = {"Authorization": f"Bearer {gateway_token}"} if gateway_token else {}
        self._client = client

    @classmethod
    def for_site(cls, db, tenant_id: str, site_id: str, *, client=None):
        # Reutiliza la tabla histórica para una migración sin pérdida de conexiones.
        connection = db.scalar(
            select(RecorderConnection).where(
                RecorderConnection.tenant_id == tenant_id,
                RecorderConnection.site_id == site_id,
            )
        )
        if connection is None:
            if settings().app_env != "production":
                return cls(gateway_token=settings().recording_gateway_token, client=client)
            raise MediaError("Vigilay Recorder no está conectado para esta sede")
        if (
            connection.status != "ONLINE"
            or not connection.endpoint_url
            or connection.last_seen_at is None
            or connection.last_seen_at < utcnow() - timedelta(seconds=45)
        ):
            raise MediaError("El enlace con Vigilay Recorder está desconectado")
        if not connection.gateway_token_encrypted:
            raise MediaError("Vigilay Recorder debe renovar la credencial de esta sede")
        try:
            token = decrypt_credentials(connection.gateway_token_encrypted, tenant_id, site_id)[
                "gateway_token"
            ]
        except (InvalidTag, KeyError, ValueError) as exc:
            raise MediaError("La credencial de Vigilay Recorder no es válida") from exc
        return cls(base_url=connection.endpoint_url, gateway_token=token, client=client)

    def json(self, path, *, params=None):
        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=self.timeout)
        try:
            response = client.get(f"{self.base_url}/api{path}", params=params, headers=self.headers)
            if response.status_code in {401, 403}:
                raise MediaError("Vigilay Recorder rechazó la credencial de esta sede")
            if response.status_code >= 400:
                raise MediaError("Vigilay Recorder rechazó la consulta")
            result = response.json()
            return result if isinstance(result, list) else []
        except (httpx.HTTPError, ValueError) as exc:
            if isinstance(exc, MediaError):
                raise
            raise MediaError("Vigilay Recorder no está disponible en la sede") from exc
        finally:
            if owns_client:
                client.close()

    def cameras(self):
        return self.json("/cameras")

    def events(self, *, after=None, before=None):
        return self.json("/events", params={"after": after or 0, "before": before or 2**63 - 1})

    def recordings(self, camera_id, *, after, before):
        return self.json(
            "/recordings", params={"camera_id": camera_id, "after": after, "before": before}
        )

    def stream_recording(self, recording_id, *, range_header=None, if_range=None):
        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=httpx.Timeout(60, connect=5))
        headers = {**self.headers, "Accept-Encoding": "identity"}
        if range_header:
            headers["Range"] = range_header
        if if_range:
            headers["If-Range"] = if_range
        response = None
        try:
            request = client.build_request(
                "GET",
                f"{self.base_url}/api/recordings/file",
                params={"id": recording_id},
                headers=headers,
            )
            response = client.send(request, stream=True)
            if response.status_code in {401, 403}:
                raise MediaError("Vigilay Recorder rechazó la credencial de esta sede")
            if response.status_code == 404:
                raise MediaError("La grabación ya no existe")
            if response.status_code >= 400 and response.status_code != 416:
                raise MediaError("Vigilay Recorder rechazó la consulta")
        except (httpx.HTTPError, MediaError) as exc:
            if response is not None:
                response.close()
            if owns_client:
                client.close()
            if isinstance(exc, MediaError):
                raise
            raise MediaError("Vigilay Recorder no está disponible en la sede") from exc
        return MediaStream(response, client, owns_client)
