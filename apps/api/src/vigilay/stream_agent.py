"""Local on-demand publisher run beside the Windows camera process."""

from __future__ import annotations

import logging
import os
import shutil
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path
from urllib import request
from urllib.error import URLError
from urllib.parse import urlsplit

from sqlalchemy import select

from vigilay.config import settings
from vigilay.db import system_session
from vigilay.models import (
    AuditLog,
    Camera,
    CameraCapability,
    CameraCredential,
    CameraStreamProvider,
    CameraStreamSession,
    DeviceCommand,
    ServiceHeartbeat,
    utcnow,
)
from vigilay.security import decrypt_credentials

try:
    from onvif import ONVIFCamera
except ImportError:  # pragma: no cover - reported as a safe command failure
    ONVIFCamera = None

logger = logging.getLogger("vigilay.stream_agent")


class StreamAgentError(RuntimeError):
    pass


class PtzController:
    vectors = {
        "left": (-1, 0, 0),
        "right": (1, 0, 0),
        "up": (0, 1, 0),
        "down": (0, -1, 0),
        "up-left": (-0.7, 0.7, 0),
        "up-right": (0.7, 0.7, 0),
        "down-left": (-0.7, -0.7, 0),
        "down-right": (0.7, -0.7, 0),
        "zoom-in": (0, 0, 1),
        "zoom-out": (0, 0, -1),
    }

    def move(self, camera: Camera, secret: dict, action: str, speed: float):
        if action not in self.vectors:
            raise StreamAgentError("Movimiento PTZ no válido")
        if camera.integration_type == "V380":
            return self._move_v380(secret, action)
        return self._move_onvif(camera, secret, action, speed)

    @staticmethod
    def _move_v380(secret: dict, action: str):
        movements = {
            "left": ("left",),
            "right": ("right",),
            "up": ("up",),
            "down": ("down",),
            "up-left": ("up", "left"),
            "up-right": ("up", "right"),
            "down-left": ("down", "left"),
            "down-right": ("down", "right"),
        }
        if action not in movements:
            raise StreamAgentError("La V380 no ofrece zoom mediante el puente local")
        port = int(secret.get("http_port", 8081))
        try:
            for movement in movements[action]:
                command = request.Request(
                    f"http://127.0.0.1:{port}/api/ptz/{movement}", data=b"", method="POST"
                )
                with request.urlopen(command, timeout=3) as response:
                    if response.status != 200:
                        raise StreamAgentError("El puente V380 rechazó el movimiento")
        except (OSError, URLError) as exc:
            raise StreamAgentError("El puente V380 no está disponible") from exc

    @classmethod
    def _move_onvif(cls, camera: Camera, secret: dict, action: str, speed: float):
        if ONVIFCamera is None:
            raise StreamAgentError("El agente no tiene soporte ONVIF")
        parsed = urlsplit(secret.get("rtsp_url", ""))
        host = parsed.hostname
        username = parsed.username or secret.get("username", "")
        password = parsed.password or secret.get("password", "")
        if not host:
            raise StreamAgentError("La conexión ONVIF no tiene una dirección válida")
        client = ONVIFCamera(
            host, int(secret.get("onvif_port", 80)), username, password, no_cache=True
        )
        media = client.create_media_service()
        profiles = media.GetProfiles()
        if not profiles:
            raise StreamAgentError("La cámara no publicó perfiles ONVIF")
        profile = profiles[0]
        ptz = client.create_ptz_service()
        options = ptz.GetConfigurationOptions(
            {"ConfigurationToken": profile.PTZConfiguration.token}
        )
        pan_spaces = options.Spaces.ContinuousPanTiltVelocitySpace or []
        zoom_spaces = options.Spaces.ContinuousZoomVelocitySpace or []
        pan, tilt, zoom = cls.vectors[action]
        movement = ptz.create_type("ContinuousMove")
        movement.ProfileToken = profile.token
        speed = min(1.0, max(0.1, float(speed)))
        if zoom:
            if not zoom_spaces:
                raise StreamAgentError("La cámara no ofrece zoom ONVIF")
            movement.Velocity = {"Zoom": {"x": zoom * speed, "space": zoom_spaces[0].URI}}
        else:
            fallback = "http://www.onvif.org/ver10/tptz/PanTiltSpaces/VelocityGenericSpace"
            space = pan_spaces[0].URI if pan_spaces else fallback
            movement.Velocity = {"PanTilt": {"x": pan * speed, "y": tilt * speed, "space": space}}
        try:
            ptz.ContinuousMove(movement)
            time.sleep(0.28)
        finally:
            ptz.Stop(
                {
                    "ProfileToken": profile.token,
                    "PanTilt": not bool(zoom),
                    "Zoom": bool(zoom),
                }
            )


def _port_open(host: str, port: int, timeout=1.0):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class CameraStreamResolver:
    def __init__(self, *, v380_starter=None):
        self.v380_starter = v380_starter

    def resolve(self, camera: Camera, secret: dict) -> str:
        if camera.integration_type == "V380":
            port = int(secret.get("rtsp_port", 8555))
            if not _port_open("127.0.0.1", port):
                runtime = {"id": camera.id, "name": camera.name, **secret}
                runtime.update(
                    {
                        "brand": camera.brand,
                        "model": camera.model,
                        "integration_type": camera.integration_type,
                    }
                )
                (self.v380_starter or self._start_v380_bridge)(runtime)
            if not _port_open("127.0.0.1", port):
                raise StreamAgentError("El puente V380 no está disponible")
            return f"rtsp://127.0.0.1:{port}/live"
        if camera.integration_type == "RTSP":
            source = secret.get("rtsp_url", "")
            parsed = urlsplit(source)
            if parsed.scheme not in {"rtsp", "rtsps"} or not parsed.hostname:
                raise StreamAgentError("La fuente RTSP no es válida")
            if not _port_open(parsed.hostname, parsed.port or 554):
                raise StreamAgentError("La cámara no está disponible")
            return source
        raise StreamAgentError("La cámara no ofrece una fuente de video compatible")

    @staticmethod
    def _start_v380_bridge(camera: dict):
        executable = Path(settings().v380_decoder_path).resolve()
        if not executable.is_file():
            raise StreamAgentError("No se encontró V380Decoder")
        rtsp_port = int(camera.get("rtsp_port", 8555))
        http_port = int(camera.get("http_port", 8081))
        child_environment = os.environ.copy()
        child_environment["V380_CAMERA_PASSWORD"] = str(camera.get("password", ""))
        arguments = [
            str(executable),
            "--id",
            str(camera.get("device_id", "")),
            "--username",
            str(camera.get("username", "")),
            "--ip",
            str(camera.get("host", "")),
            "--port",
            str(camera.get("port", 8800)),
            "--source",
            "lan",
            "--quality",
            str(camera.get("quality", "sd")),
            "--enable-api",
            "--http-port",
            str(http_port),
            "--rtsp-port",
            str(rtsp_port),
        ]
        subprocess.Popen(
            arguments,
            cwd=executable.parent,
            env=child_environment,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        child_environment["V380_CAMERA_PASSWORD"] = ""
        for _ in range(40):
            if _port_open("127.0.0.1", rtsp_port):
                return
            time.sleep(0.5)
        raise StreamAgentError("El puente V380 no pudo iniciar")


class StreamManager:
    def __init__(self, ffmpeg_path: str, *, popen=subprocess.Popen, startup_seconds=2):
        self.ffmpeg_path = ffmpeg_path
        self._popen = popen
        self.startup_seconds = startup_seconds
        self._lock = threading.RLock()
        self._active = {}

    def _executable(self):
        path = Path(self.ffmpeg_path)
        executable = str(path) if path.is_file() else shutil.which(self.ffmpeg_path)
        if not executable:
            raise StreamAgentError("No se encontró FFmpeg")
        return executable

    def start_stream(self, camera_id: str, source_url: str, whip_url: str):
        with self._lock:
            current = self._active.get(camera_id)
            if current and current.poll() is None:
                return False
            if current:
                self._active.pop(camera_id, None)
            arguments = [
                self._executable(),
                "-hide_banner",
                "-loglevel",
                "warning",
                "-rtsp_transport",
                "tcp",
                "-i",
                source_url,
                "-f",
                "lavfi",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=48000",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "libx264",
                "-profile:v",
                "baseline",
                "-level:v",
                "3.1",
                "-pix_fmt",
                "yuv420p",
                "-preset",
                "veryfast",
                "-tune",
                "zerolatency",
                "-bf",
                "0",
                "-g",
                "30",
                "-maxrate",
                "4000k",
                "-bufsize",
                "1500k",
                "-flags",
                "+global_header",
                "-c:a",
                "libopus",
                "-b:a",
                "128k",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-ts_buffer_size",
                "16777216",
                "-f",
                "whip",
                whip_url,
            ]
            process = self._popen(
                arguments,
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self._active[camera_id] = process
        try:
            code = process.wait(timeout=self.startup_seconds)
        except subprocess.TimeoutExpired:
            logger.info("Cloudflare stream started camera_id=%s", camera_id)
            return True
        with self._lock:
            self._active.pop(camera_id, None)
        raise StreamAgentError(f"FFmpeg terminó durante el arranque (código {code})")

    def stop_stream(self, camera_id: str):
        with self._lock:
            process = self._active.pop(camera_id, None)
        if not process or process.poll() is not None:
            return False
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        logger.info("Cloudflare stream stopped camera_id=%s", camera_id)
        return True

    def is_streaming(self, camera_id: str):
        with self._lock:
            process = self._active.get(camera_id)
            if process and process.poll() is not None:
                self._active.pop(camera_id, None)
                return False
            return process is not None

    def get_stream_status(self, camera_id: str):
        return "live" if self.is_streaming(camera_id) else "stopped"

    def camera_ids(self):
        with self._lock:
            return list(self._active)

    def stop_all(self):
        for camera_id in self.camera_ids():
            self.stop_stream(camera_id)


class LocalStreamAgent:
    def __init__(self, *, resolver=None, manager=None, ptz=None, poll_seconds=1):
        config = settings()
        self.resolver = resolver or CameraStreamResolver()
        self.manager = manager or StreamManager(config.ffmpeg_path)
        self.ptz = ptz or PtzController()
        self.poll_seconds = poll_seconds
        self.idle_timeout = config.stream_idle_timeout_seconds
        self.stop_event = threading.Event()
        self.last_viewer_at = {}
        self.failures = {}
        self.next_retry_at = {}

    def _active_sessions(self, db, camera_id=None):
        cutoff = utcnow().timestamp() - self.idle_timeout
        stmt = select(CameraStreamSession).where(
            CameraStreamSession.status.in_(["starting", "live"])
        )
        if camera_id:
            stmt = stmt.where(CameraStreamSession.camera_id == camera_id)
        rows = list(db.scalars(stmt))
        active = []
        for row in rows:
            if row.last_heartbeat_at.timestamp() < cutoff:
                row.status = "stopped"
                row.stopped_at = utcnow()
                row.stop_reason = "heartbeat_timeout"
                self.last_viewer_at[row.camera_id] = time.monotonic() - self.idle_timeout
            else:
                active.append(row)
        return active

    def reconcile(self):
        now = time.monotonic()
        with system_session() as db:
            heartbeat = db.get(ServiceHeartbeat, "stream-agent")
            if heartbeat is None:
                db.add(ServiceHeartbeat(service_name="stream-agent", last_seen_at=utcnow()))
            else:
                heartbeat.last_seen_at = utcnow()
            self._process_probe(db)
            self._process_ptz(db)
            active = self._active_sessions(db)
            by_camera = {}
            for session in active:
                by_camera.setdefault(session.camera_id, []).append(session)

            for camera_id, sessions in by_camera.items():
                self.last_viewer_at[camera_id] = now
                if self.manager.is_streaming(camera_id):
                    for session in sessions:
                        session.status = "live"
                    continue
                if now < self.next_retry_at.get(camera_id, 0):
                    continue
                try:
                    camera = db.get(Camera, camera_id)
                    credential = db.scalar(
                        select(CameraCredential).where(CameraCredential.camera_id == camera_id)
                    )
                    provider = db.scalar(
                        select(CameraStreamProvider).where(
                            CameraStreamProvider.camera_id == camera_id,
                            CameraStreamProvider.enabled.is_(True),
                        )
                    )
                    if not camera or not credential or not provider:
                        raise StreamAgentError("Configuración de streaming incompleta")
                    source_secret = decrypt_credentials(
                        credential.secret_encrypted, camera.tenant_id, camera.id
                    )
                    publish_secret = decrypt_credentials(
                        provider.publish_url_encrypted, camera.tenant_id, camera.id
                    )
                    source = self.resolver.resolve(camera, source_secret)
                    self.manager.start_stream(camera.id, source, publish_secret["publish_url"])
                    self.failures.pop(camera_id, None)
                    self.next_retry_at.pop(camera_id, None)
                    for session in sessions:
                        session.status = "live"
                        session.sanitized_error = None
                except Exception:
                    failures = self.failures.get(camera_id, 0) + 1
                    self.failures[camera_id] = failures
                    if failures <= 3:
                        self.next_retry_at[camera_id] = now + (2, 5, 10)[failures - 1]
                    else:
                        for session in sessions:
                            session.status = "error"
                            session.stopped_at = utcnow()
                            session.stop_reason = "publisher_failed"
                            session.sanitized_error = "No se pudo iniciar la transmisión"
                    logger.warning(
                        "Cloudflare stream start failed camera_id=%s attempt=%s",
                        camera_id,
                        failures,
                    )

            for camera_id in self.manager.camera_ids():
                if camera_id in by_camera:
                    continue
                last = self.last_viewer_at.setdefault(camera_id, now)
                if now - last >= self.idle_timeout:
                    self.manager.stop_stream(camera_id)
                    self.last_viewer_at.pop(camera_id, None)
                    self.failures.pop(camera_id, None)
                    self.next_retry_at.pop(camera_id, None)
            db.commit()

    def _process_probe(self, db):
        command = db.scalar(
            select(DeviceCommand)
            .join(Camera, Camera.id == DeviceCommand.camera_id)
            .where(
                DeviceCommand.status == "PENDING",
                DeviceCommand.command == "PROBE",
                Camera.integration_type != "SIMULATOR",
            )
            .order_by(DeviceCommand.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if command is None:
            return
        camera = db.get(Camera, command.camera_id)
        command.status = "RUNNING"
        try:
            credential = db.scalar(
                select(CameraCredential).where(CameraCredential.camera_id == camera.id)
            )
            if credential is None:
                raise StreamAgentError("La cámara no tiene credenciales")
            secret = decrypt_credentials(credential.secret_encrypted, camera.tenant_id, camera.id)
            self.resolver.resolve(camera, secret)
            capability = db.get(CameraCapability, (camera.id, "live_video"))
            if capability is None:
                capability = CameraCapability(
                    tenant_id=camera.tenant_id,
                    camera_id=camera.id,
                    capability_key="live_video",
                )
                db.add(capability)
            capability.supported = True
            capability.readable = True
            capability.writable = False
            capability.metadata_json = {"transport": "RTSP", "verified_by": "stream_agent"}
            camera.status = "ONLINE"
            command.status = "SUCCEEDED"
            command.sanitized_error = None
        except Exception:
            camera.status = "OFFLINE"
            command.status = "FAILED"
            command.sanitized_error = "El agente no pudo abrir la fuente de video"
        command.completed_at = utcnow()
        db.add(
            AuditLog(
                tenant_id=camera.tenant_id,
                action="CAMERA_COMMAND_" + command.status,
                resource_type="command",
                resource_id=command.id,
            )
        )

    def _process_ptz(self, db):
        command = db.scalar(
            select(DeviceCommand)
            .where(DeviceCommand.status == "PENDING", DeviceCommand.command == "PTZ")
            .order_by(DeviceCommand.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if command is None:
            return
        camera = db.get(Camera, command.camera_id)
        command.status = "RUNNING"
        try:
            credential = db.scalar(
                select(CameraCredential).where(CameraCredential.camera_id == camera.id)
            )
            if credential is None:
                raise StreamAgentError("La cámara no tiene credenciales")
            secret = decrypt_credentials(credential.secret_encrypted, camera.tenant_id, camera.id)
            if camera.integration_type == "V380":
                self.resolver.resolve(camera, secret)
            self.ptz.move(
                camera,
                secret,
                str(command.payload_json.get("action", "")),
                float(command.payload_json.get("speed", 0.5)),
            )
            command.status = "SUCCEEDED"
            command.sanitized_error = None
        except Exception:
            command.status = "FAILED"
            command.sanitized_error = "La cámara rechazó el movimiento PTZ"
        command.completed_at = utcnow()
        db.add(
            AuditLog(
                tenant_id=camera.tenant_id,
                action="CAMERA_PTZ_" + command.status,
                resource_type="command",
                resource_id=command.id,
            )
        )

    def recover(self):
        with system_session() as db:
            for session in db.scalars(
                select(CameraStreamSession).where(
                    CameraStreamSession.status.in_(["starting", "live", "stopping"])
                )
            ):
                session.status = "stopped"
                session.stopped_at = utcnow()
                session.stop_reason = "agent_restart"
            db.commit()

    def run(self):
        self._validate_transport()
        self.recover()
        while not self.stop_event.is_set():
            try:
                self.reconcile()
            except Exception:
                logger.warning("Local stream agent reconciliation failed")
            self.stop_event.wait(self.poll_seconds)
        self.manager.stop_all()

    def start(self):
        thread = threading.Thread(target=self.run, name="vigilay-stream-agent", daemon=True)
        thread.start()
        return thread

    def stop(self):
        self.stop_event.set()
        self.manager.stop_all()

    @staticmethod
    def _validate_transport():
        config = settings()
        if config.app_env != "production":
            return
        database = config.database_url.lower()
        if "ssl_ca=" not in database and "ssl_verify_cert=true" not in database:
            raise RuntimeError("El agente requiere MySQL TLS verificado en producción")


def main():
    """Run the LAN-side publisher as a supervised foreground process."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    agent = LocalStreamAgent()

    def shutdown(*_):
        agent.stop()

    for signal_name in ("SIGINT", "SIGTERM"):
        if hasattr(signal, signal_name):
            signal.signal(getattr(signal, signal_name), shutdown)
    logger.info("Vigilay stream agent starting")
    agent.run()


if __name__ == "__main__":
    main()
