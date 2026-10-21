"""Agente de live por sede integrado en Vigilay Recorder, sin acceso directo a MySQL."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib import error, request

LOG = logging.getLogger("vigilay-recorder.live")


def ffmpeg_executable():
    configured = os.getenv("VIGILAY_FFMPEG_PATH", "").strip()
    candidates = [Path(configured)] if configured else []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).with_name("vigilay-ffmpeg.exe"))
    discovered = shutil.which("ffmpeg")
    if discovered:
        candidates.append(Path(discovered))
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.resolve())
    raise RuntimeError("No se encontró el componente FFmpeg con soporte WHIP")


@dataclass
class Publisher:
    process: subprocess.Popen
    ready: threading.Event
    reported_status: str = ""


class SiteLiveAgent:
    """Publica cámaras locales a trabajos WHIP autorizados para una sola sede."""

    def __init__(self, config, stop_event, *, popen=subprocess.Popen, poll_seconds=1.0):
        self.config = config
        self.stop_event = stop_event
        self.popen = popen
        self.poll_seconds = poll_seconds
        self.cameras = {camera.id: camera for camera in config.cameras if camera.enabled}
        self.publishers: dict[str, Publisher] = {}
        self.retry_after: dict[str, float] = {}

    def _post(self, path, payload):
        body = json.dumps(
            {
                "site_id": self.config.site_id,
                "gateway_token": self.config.gateway_token,
                **payload,
            }
        ).encode("utf-8")
        call = request.Request(
            f"{self.config.api_url}/api/v1{path}",
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": "Vigilay-Recorder/0.3"},
            method="POST",
        )
        with request.urlopen(call, timeout=8) as response:
            return json.loads(response.read().decode("utf-8"))

    def _report(self, camera_id, status):
        publisher = self.publishers.get(camera_id)
        if publisher and publisher.reported_status == status:
            return
        self._post("/agent/live/status", {"camera_id": camera_id, "status": status})
        if publisher:
            publisher.reported_status = status

    @staticmethod
    def _watch_progress(process, ready):
        stream = process.stdout
        if stream is None:
            return
        try:
            for line in stream:
                key, _, value = line.strip().partition("=")
                if key == "frame" and value.isdigit() and int(value) > 0:
                    ready.set()
        except (OSError, ValueError):
            pass
        finally:
            stream.close()

    def _start(self, camera_id, publish_url):
        camera = self.cameras.get(camera_id)
        if camera is None:
            self._post("/agent/live/status", {"camera_id": camera_id, "status": "error"})
            self.retry_after[camera_id] = time.monotonic() + 15
            return
        command = [
            ffmpeg_executable(),
            "-hide_banner",
            "-loglevel",
            "warning",
            "-progress",
            "pipe:1",
            "-stats_period",
            "0.25",
            "-rtsp_transport",
            "tcp",
            "-fflags",
            "nobuffer",
            "-flags",
            "low_delay",
            "-i",
            camera.source,
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-c:v",
            "libx264",
            "-vf",
            "fps=15,scale=w='min(1280,iw)':h='min(720,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2",
            "-profile:v",
            "baseline",
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "veryfast",
            "-tune",
            "zerolatency",
            "-bf",
            "0",
            "-g",
            "15",
            "-c:a",
            "libopus",
            "-b:a",
            "128k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-f",
            "whip",
            publish_url,
        ]
        process = self.popen(
            command,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        publisher = Publisher(process=process, ready=threading.Event())
        self.publishers[camera_id] = publisher
        threading.Thread(
            target=self._watch_progress,
            args=(process, publisher.ready),
            name=f"live-progress-{camera_id}",
            daemon=True,
        ).start()
        self._report(camera_id, "starting")

    def _stop(self, camera_id):
        publisher = self.publishers.pop(camera_id, None)
        if publisher is None or publisher.process.poll() is not None:
            return
        publisher.process.terminate()
        try:
            publisher.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            publisher.process.kill()
            publisher.process.wait(timeout=5)

    def reconcile(self):
        payload = self._post("/agent/live/poll", {})
        jobs = {
            str(item.get("camera_id")): str(item.get("publish_url"))
            for item in payload.get("streams", [])
            if item.get("camera_id") and item.get("publish_url")
        }
        for camera_id in list(self.publishers):
            if camera_id not in jobs:
                self._stop(camera_id)
                continue
            publisher = self.publishers[camera_id]
            if publisher.process.poll() is not None:
                self.publishers.pop(camera_id, None)
                self._post("/agent/live/status", {"camera_id": camera_id, "status": "error"})
                self.retry_after[camera_id] = time.monotonic() + 5
            elif publisher.ready.is_set():
                self._report(camera_id, "live")
        for camera_id, publish_url in jobs.items():
            if camera_id in self.publishers or time.monotonic() < self.retry_after.get(
                camera_id, 0
            ):
                continue
            self._start(camera_id, publish_url)

    def run(self):
        LOG.info("Agente de video integrado iniciado para la sede configurada")
        while not self.stop_event.is_set():
            try:
                self.reconcile()
            except (
                OSError,
                ValueError,
                RuntimeError,
                subprocess.SubprocessError,
                error.URLError,
                json.JSONDecodeError,
            ):
                LOG.warning("No se pudo sincronizar el agente de live; se reintentará")
            self.stop_event.wait(self.poll_seconds)
        for camera_id in list(self.publishers):
            self._stop(camera_id)
