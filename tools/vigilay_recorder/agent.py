"""Proceso supervisor para grabar varias camaras sin Frigate."""

from __future__ import annotations

import argparse
import hmac
import json
import logging
import signal
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from tools.v380_motion_recorder.recorder import MotionRecorder, RecorderConfig
from tools.vigilay_recorder.config import load_configuration, prune_recordings, recording_catalog

LOG = logging.getLogger("vigilay-recorder")


def handler_factory(config):
    root = config.output_dir.resolve()

    class RecordingHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):  # noqa: N802
            if config.gateway_token:
                expected = f"Bearer {config.gateway_token}"
                if not hmac.compare_digest(self.headers.get("Authorization", ""), expected):
                    return self._json(401, {"detail": "Unauthorized"})
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query)
            if parsed.path == "/api/cameras":
                return self._json(
                    200,
                    [
                        {"id": camera.id, "name": camera.name}
                        for camera in config.cameras
                        if camera.enabled
                    ],
                )
            if parsed.path in {"/api/events", "/api/recordings"}:
                try:
                    after = float(query.get("after", [0])[0])
                    before = float(query.get("before", [str(float("inf"))])[0])
                except ValueError:
                    return self._json(422, {"detail": "Invalid date range"})
                camera_id = query.get("camera_id", [""])[0]
                rows = recording_catalog(root, camera_id=camera_id, after=after, before=before)
                if parsed.path == "/api/events":
                    rows = [
                        {
                            "id": row["id"],
                            "camera_id": row["camera_id"],
                            "camera_name": row["camera_name"],
                            "label": "person" if config.detector == "yolo" else "motion",
                            "start_time": row["start"],
                            "end_time": row["end"],
                            "has_clip": True,
                            "has_snapshot": bool(row.get("snapshot_id")),
                            "snapshot_id": row.get("snapshot_id"),
                            "persons_visible_peak": row.get("objects", 0),
                            "persons_crossed": row.get("persons_crossed", 0),
                            "crossings_down": row.get("crossings_down", 0),
                            "crossings_up": row.get("crossings_up", 0),
                        }
                        for row in rows
                    ]
                return self._json(200, rows)
            if parsed.path == "/api/recordings/file":
                return self._file(query.get("id", [""])[0])
            return self._json(404, {"detail": "Not found"})

        def _file(self, recording_id):
            try:
                target = (root / recording_id).resolve()
                target.relative_to(root)
                suffix = target.suffix.lower()
                if suffix not in {".mp4", ".jpg"} or not target.is_file():
                    raise OSError
                size = target.stat().st_size
            except (OSError, ValueError):
                return self._json(404, {"detail": "Recording not found"})
            start, end, status = 0, size - 1, 200
            range_header = self.headers.get("Range", "")
            if range_header.startswith("bytes="):
                try:
                    first, _, last = range_header[6:].partition("-")
                    if first:
                        start = int(first)
                        end = min(size - 1, int(last) if last else size - 1)
                    elif last:
                        suffix = int(last)
                        if suffix <= 0:
                            raise ValueError
                        start, end = max(0, size - suffix), size - 1
                    else:
                        raise ValueError
                    if start < 0 or end < start or start >= size:
                        raise ValueError
                    status = 206
                except ValueError:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
            length = end - start + 1
            self.send_response(status)
            self.send_header("Content-Type", "image/jpeg" if suffix == ".jpg" else "video/mp4")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(length))
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Cache-Control", "private, no-store")
            self.end_headers()
            try:
                with target.open("rb") as stream:
                    stream.seek(start)
                    remaining = length
                    while remaining:
                        chunk = stream.read(min(64 * 1024, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _json(self, status, value):
            body = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "private, no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    return RecordingHandler


class RecorderAgent:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.stop_event = threading.Event()
        self.threads: list[threading.Thread] = []
        self.server = None

    def run(self) -> None:
        config = load_configuration(self.config_path)
        config.output_dir.mkdir(parents=True, exist_ok=True)
        prune_recordings(config.output_dir, config.retention_days, config.min_free_gb)
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", config.gateway_port), handler_factory(config)
        )
        threading.Thread(
            target=self.server.serve_forever, name="recording-api", daemon=True
        ).start()
        enabled = [camera for camera in config.cameras if camera.enabled]
        if not enabled:
            raise RuntimeError("Configura al menos una camara activa antes de grabar")
        for camera in enabled:
            recorder_config = RecorderConfig(
                source=camera.source,
                output=config.output_dir,
                camera=camera.id,
                camera_name=camera.name,
                fps=camera.fps,
                detector=config.detector,
                model=config.model,
                confidence=config.confidence,
                min_free_gb=config.min_free_gb,
            )
            thread = threading.Thread(
                target=self._record,
                args=(recorder_config,),
                name=f"recorder-{camera.id}",
                daemon=True,
            )
            thread.start()
            self.threads.append(thread)
        while not self.stop_event.wait(30):
            prune_recordings(config.output_dir, config.retention_days, config.min_free_gb)
            if not any(thread.is_alive() for thread in self.threads):
                raise RuntimeError("Todos los grabadores terminaron inesperadamente")
        for thread in self.threads:
            thread.join(timeout=15)
        self.server.shutdown()

    def _record(self, config: RecorderConfig) -> None:
        while not self.stop_event.is_set():
            try:
                MotionRecorder(config, self.stop_event).run()
            except Exception:
                LOG.exception("Grabador interrumpido camera_id=%s; se reintentara", config.camera)
            if not self.stop_event.is_set():
                self.stop_event.wait(5)


def main() -> None:
    parser = argparse.ArgumentParser(description="Agente local de grabacion Vigilay")
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    agent = RecorderAgent(args.config.resolve())

    def stop(*_):
        agent.stop_event.set()

    for name in ("SIGINT", "SIGTERM"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), stop)
    agent.run()


if __name__ == "__main__":
    main()
