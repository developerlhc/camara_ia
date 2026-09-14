"""Private Frigate API client. Internal URLs never reach the browser."""

from urllib.parse import urlsplit

import httpx

from vigilay.config import settings


class FrigateError(RuntimeError):
    pass


class FrigateService:
    def __init__(self, *, client=None):
        config = settings()
        self.base_url = config.frigate_api_url.rstrip("/")
        parsed = urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise FrigateError("La dirección interna de Frigate no es válida")
        self.timeout = config.frigate_timeout_seconds
        self._client = client

    def request(self, path: str, *, params=None):
        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=self.timeout)
        try:
            response = client.get(f"{self.base_url}/api{path}", params=params)
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

    def events(self, *, limit=200):
        result = self.json("/events", params={"limit": min(limit, 200)})
        return result if isinstance(result, list) else []

    def event(self, event_id: str):
        result = self.json(f"/events/{event_id}")
        return result if isinstance(result, dict) else {}

    def recordings(self, camera_name: str, *, after: int, before: int):
        result = self.json(
            f"/{camera_name}/recordings", params={"after": after, "before": before}
        )
        return result if isinstance(result, list) else []

    def media(self, path: str):
        response = self.request(path)
        media_type = response.headers.get("content-type", "application/octet-stream")
        return response.content, media_type

    def stream_media(self, path: str):
        """Return a bounded-memory iterator and keep its private client alive."""
        client = httpx.Client(timeout=self.timeout)
        try:
            request = client.build_request("GET", f"{self.base_url}/api{path}")
            response = client.send(request, stream=True)
            if response.status_code == 404:
                response.close()
                client.close()
                raise FrigateError("La grabación ya no existe en Frigate")
            if response.status_code >= 400:
                response.close()
                client.close()
                raise FrigateError("Frigate rechazó la consulta")
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            client.close()
            raise FrigateError("Frigate no está disponible en la sede") from exc

        def chunks():
            try:
                yield from response.iter_bytes()
            finally:
                response.close()
                client.close()

        return chunks(), response.headers.get("content-type", "application/octet-stream")


def recording_windows(segments: list[dict]) -> list[dict]:
    """Join Frigate's short storage segments into useful playback windows."""
    ordered = sorted(segments, key=lambda item: float(item.get("start_time") or 0))
    windows = []
    for segment in ordered:
        start = float(segment.get("start_time") or 0)
        end = float(segment.get("end_time") or start)
        if end <= start:
            continue
        if windows and start - windows[-1]["end"] <= 5 and end - windows[-1]["start"] <= 3600:
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
