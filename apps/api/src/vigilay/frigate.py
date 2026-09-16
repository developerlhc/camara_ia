"""Private Frigate API client. Gateway URLs and credentials never reach the browser."""

from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlsplit

import httpx
from cryptography.exceptions import InvalidTag
from sqlalchemy import select

from vigilay.config import settings
from vigilay.models import FrigateConnection, utcnow
from vigilay.security import decrypt_credentials


class FrigateError(RuntimeError):
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
        return {
            name: self.response.headers[name]
            for name in (
                "content-type",
                "content-length",
                "content-range",
                "accept-ranges",
                "etag",
                "last-modified",
                "content-encoding",
            )
            if name in self.response.headers
        }


class FrigateService:
    def __init__(self, *, base_url=None, gateway_token="", client=None):
        config = settings()
        self.base_url = (base_url or config.frigate_api_url).rstrip("/")
        parsed = urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise FrigateError("La dirección interna de Frigate no es válida")
        if (
            base_url
            and config.app_env == "production"
            and (parsed.scheme != "https" or not parsed.hostname.endswith(".trycloudflare.com"))
        ):
            raise FrigateError("El endpoint publicado por Vigilay Local no es válido")
        self.timeout = config.frigate_timeout_seconds
        self.headers = {"Authorization": f"Bearer {gateway_token}"} if gateway_token else {}
        self._client = client

    @classmethod
    def for_site(cls, db, tenant_id: str, site_id: str, *, client=None):
        connection = db.scalar(
            select(FrigateConnection).where(
                FrigateConnection.tenant_id == tenant_id,
                FrigateConnection.site_id == site_id,
            )
        )
        if connection is None:
            if settings().app_env != "production":
                return cls(client=client)
            raise FrigateError("Vigilay Local no ha publicado Frigate para esta sede")
        if (
            connection.status != "ONLINE"
            or not connection.endpoint_url
            or connection.last_seen_at is None
            or connection.last_seen_at < utcnow() - timedelta(seconds=45)
        ):
            raise FrigateError("El enlace de Vigilay Local con Frigate está desconectado")
        if not connection.gateway_token_encrypted:
            raise FrigateError("Vigilay Local debe renovar la credencial de esta sede")
        try:
            gateway_token = decrypt_credentials(
                connection.gateway_token_encrypted, tenant_id, site_id
            )["gateway_token"]
        except (InvalidTag, KeyError, ValueError) as exc:
            raise FrigateError("La credencial de Vigilay Local no es válida") from exc
        return cls(
            base_url=connection.endpoint_url,
            gateway_token=gateway_token,
            client=client,
        )

    def request(self, path: str, *, params=None):
        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=self.timeout)
        try:
            response = client.get(f"{self.base_url}/api{path}", params=params, headers=self.headers)
            if response.status_code in {401, 403}:
                raise FrigateError("Vigilay Local rechazó la credencial de esta sede")
            if response.status_code == 404:
                raise FrigateError("El recurso ya no existe en Frigate")
            if response.status_code >= 400:
                raise FrigateError("Frigate rechazó la consulta")
            return response
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise FrigateError("Frigate no está disponible en la sede") from exc
        finally:
            if owns_client:
                client.close()

    def json(self, path: str, *, params=None):
        try:
            return self.request(path, params=params).json()
        except ValueError as exc:
            raise FrigateError("Frigate devolvió una respuesta inválida") from exc

    def camera_names(self) -> set[str]:
        config = self.json("/config")
        return set((config.get("cameras") or {}).keys())

    def events(self, *, limit=200, after=None, before=None):
        params = {"limit": min(limit, 200)}
        if after is not None:
            params["after"] = after
        if before is not None:
            params["before"] = before
        result = self.json("/events", params=params)
        return result if isinstance(result, list) else []

    def event(self, event_id: str):
        result = self.json(f"/events/{event_id}")
        return result if isinstance(result, dict) else {}

    def recordings(self, camera_name: str, *, after: int, before: int):
        result = self.json(f"/{camera_name}/recordings", params={"after": after, "before": before})
        return result if isinstance(result, list) else []

    def media(self, path: str):
        response = self.request(path)
        media_type = response.headers.get("content-type", "application/octet-stream")
        return response.content, media_type

    def stream_media(self, path: str, *, range_header=None, if_range=None):
        """Return a bounded-memory iterator and keep its private client alive."""
        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=httpx.Timeout(60, connect=5))
        headers = {**self.headers, "Accept-Encoding": "identity"}
        if range_header:
            headers["Range"] = range_header
        if if_range:
            headers["If-Range"] = if_range
        response = None
        try:
            request = client.build_request("GET", f"{self.base_url}/api{path}", headers=headers)
            response = client.send(request, stream=True)
            if response.status_code in {401, 403}:
                raise FrigateError("Vigilay Local rechazó la credencial de esta sede")
            if response.status_code == 404:
                raise FrigateError("La grabación ya no existe en Frigate")
            if response.status_code >= 400 and response.status_code != 416:
                raise FrigateError("Frigate rechazó la consulta")
        except (httpx.HTTPError, FrigateError) as exc:
            if response is not None:
                response.close()
            if owns_client:
                client.close()
            if isinstance(exc, FrigateError):
                raise
            raise FrigateError("Frigate no está disponible en la sede") from exc
        return MediaStream(response, client, owns_client)


def recording_windows(segments: list[dict]) -> list[dict]:
    """Join Frigate's short storage segments into useful playback windows."""
    ordered = sorted(segments, key=lambda item: float(item.get("start_time") or 0))
    windows = []
    for segment in ordered:
        start = float(segment.get("start_time") or 0)
        end = float(segment.get("end_time") or start)
        if end <= start:
            continue
        if windows and start - windows[-1]["end"] <= 5 and end - windows[-1]["start"] <= 300:
            current = windows[-1]
            current["end"] = max(current["end"], end)
            current["motion"] += int(segment.get("motion") or 0)
            current["objects"] += int(segment.get("objects") or 0)
        else:
            windows.append(
                {
                    "start": start,
                    "end": end,
                    "motion": int(segment.get("motion") or 0),
                    "objects": int(segment.get("objects") or 0),
                }
            )
    for window in windows:
        window["duration"] = round(window["end"] - window["start"], 1)
    return list(reversed(windows))
