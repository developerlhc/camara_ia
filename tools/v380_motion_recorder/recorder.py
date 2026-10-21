"""Graba clips MP4 desde el RTSP del puente V380 cuando detecta movimiento."""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import signal
import subprocess
import time
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from threading import Event

import cv2
import numpy as np

LOG = logging.getLogger("v380-recorder")


@dataclass(frozen=True)
class RecorderConfig:
    source: str
    output: Path
    camera: str = "calle"
    camera_name: str = ""
    fps: float = 15.0
    pre_roll: float = 5.0
    post_roll: float = 20.0
    max_clip: float = 20.0
    detector: str = "motion"
    model: Path = Path("yolo11n.pt")
    confidence: float = 0.45
    yolo_every: int = 3
    min_area_percent: float = 0.35
    threshold: int = 24
    consecutive_frames: int = 3
    warmup_frames: int = 30
    detect_width: int = 480
    jpeg_quality: int = 80
    min_free_gb: float = 2.0
    reconnect_seconds: float = 3.0
    codec: str = "mp4v"


class MotionDetector:
    """Detector liviano basado en un fondo que se adapta gradualmente."""

    def __init__(self, config: RecorderConfig):
        self.config = config
        self.background: np.ndarray | None = None
        self.frames = 0

    def detect(self, frame: np.ndarray) -> tuple[bool, float]:
        height, width = frame.shape[:2]
        scale = min(1.0, self.config.detect_width / max(1, width))
        small = cv2.resize(frame, (int(width * scale), int(height * scale)))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)
        current = gray.astype("float32")
        if self.background is None:
            self.background = current
            return False, 0.0

        delta = cv2.absdiff(gray, cv2.convertScaleAbs(self.background))
        mask = cv2.threshold(delta, self.config.threshold, 255, cv2.THRESH_BINARY)[1]
        mask = cv2.dilate(mask, None, iterations=2)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        moving_area = sum(cv2.contourArea(contour) for contour in contours)
        percent = 100.0 * moving_area / max(1, mask.shape[0] * mask.shape[1])

        # El fondo aprende más despacio cuando hay actividad para no absorberla enseguida.
        cv2.accumulateWeighted(current, self.background, 0.003 if percent else 0.02)
        self.frames += 1
        ready = self.frames >= self.config.warmup_frames
        return ready and percent >= self.config.min_area_percent, percent


class PersonCrossingCounter:
    """Sigue centroides y cuenta cada persona una vez al cruzar la linea central."""

    def __init__(self, line_ratio: float = 0.5, hysteresis: float = 0.04, max_missing=12):
        self.line_ratio = line_ratio
        self.hysteresis = hysteresis
        self.max_missing = max_missing
        self.frame_index = 0
        self.next_id = 1
        self.tracks: dict[int, dict] = {}
        self.persons_crossed = 0
        self.crossings_down = 0
        self.crossings_up = 0

    def update(self, boxes: list[list[float]], frame_shape: tuple[int, ...]) -> None:
        self.frame_index += 1
        height, width = frame_shape[:2]
        centers = [((box[0] + box[2]) / 2, (box[1] + box[3]) / 2) for box in boxes]
        maximum_distance = max(width, height) * 0.18
        candidates = []
        for track_id, track in self.tracks.items():
            for center_index, center in enumerate(centers):
                distance = ((track["x"] - center[0]) ** 2 + (track["y"] - center[1]) ** 2) ** 0.5
                if distance <= maximum_distance:
                    candidates.append((distance, track_id, center_index))
        matched_tracks, matched_centers = set(), set()
        for _, track_id, center_index in sorted(candidates):
            if track_id in matched_tracks or center_index in matched_centers:
                continue
            matched_tracks.add(track_id)
            matched_centers.add(center_index)
            self._move_track(track_id, centers[center_index], height)
        for center_index, center in enumerate(centers):
            if center_index in matched_centers:
                continue
            side = self._side(center[1], height)
            self.tracks[self.next_id] = {
                "x": center[0],
                "y": center[1],
                "side": side,
                "last_seen": self.frame_index,
                "counted": False,
            }
            self.next_id += 1
        self.tracks = {
            track_id: track
            for track_id, track in self.tracks.items()
            if self.frame_index - track["last_seen"] <= self.max_missing
        }

    def _side(self, y: float, height: int) -> int:
        line = height * self.line_ratio
        deadband = height * self.hysteresis
        if y < line - deadband:
            return -1
        if y > line + deadband:
            return 1
        return 0

    def _move_track(self, track_id: int, center: tuple[float, float], height: int) -> None:
        track = self.tracks[track_id]
        side = self._side(center[1], height)
        previous_side = track["side"]
        if side and previous_side and side != previous_side and not track["counted"]:
            track["counted"] = True
            self.persons_crossed += 1
            if side > previous_side:
                self.crossings_down += 1
            else:
                self.crossings_up += 1
        if side:
            track["side"] = side
        track.update(x=center[0], y=center[1], last_seen=self.frame_index)

    def reset_event_counts(self) -> None:
        """Inicia el siguiente clip sin olvidar IDs que siguen en pantalla."""
        self.persons_crossed = 0
        self.crossings_down = 0
        self.crossings_up = 0


class YoloDetector:
    """Detecta personas con YOLO; su presencia activa la grabación."""

    def __init__(self, config: RecorderConfig):
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise RuntimeError("Instala ultralytics para usar el detector YOLO") from exc
        if not config.model.exists():
            raise RuntimeError(f"No se encontró el modelo YOLO: {config.model}")
        self.config = config
        self.model = YOLO(str(config.model))
        self.frame_index = 0
        self.last_result = False
        self.last_count = 0.0
        self.crossings = PersonCrossingCounter()

    def detect(self, frame: np.ndarray) -> tuple[bool, float]:
        self.frame_index += 1
        if (self.frame_index - 1) % self.config.yolo_every:
            return self.last_result, self.last_count
        results = self.model.predict(
            frame,
            conf=self.config.confidence,
            classes=[0],
            imgsz=416,
            verbose=False,
        )
        boxes = results[0].boxes
        count = len(boxes) if boxes is not None else 0
        coordinates = boxes.xyxy.cpu().tolist() if boxes is not None else []
        self.crossings.update(coordinates, frame.shape)
        self.last_result, self.last_count = count > 0, float(count)
        return self.last_result, self.last_count

    @property
    def crossing_counts(self) -> dict[str, int]:
        return {
            "persons_crossed": self.crossings.persons_crossed,
            "crossings_down": self.crossings.crossings_down,
            "crossings_up": self.crossings.crossings_up,
        }

    def reset_event_counts(self) -> None:
        self.crossings.reset_event_counts()


class MotionRecorder:
    def __init__(self, config: RecorderConfig, stop_event: Event | None = None):
        self.config = config
        self.stop_event = stop_event or Event()
        self.detector = (
            YoloDetector(config) if config.detector == "yolo" else MotionDetector(config)
        )
        self.buffer: deque[tuple[datetime, bytes]] = deque(
            maxlen=max(1, round(config.pre_roll * config.fps))
        )
        self.writer = None
        self.partial_path: Path | None = None
        self.final_path: Path | None = None
        self.event_started_wall: datetime | None = None
        self.event_started_mono: float | None = None
        self.last_motion_mono: float | None = None
        self.motion_streak = 0
        self.frames_written = 0
        self.peak_motion = 0.0

    def run(self) -> None:
        self.config.output.mkdir(parents=True, exist_ok=True)
        while not self.stop_event.is_set():
            capture = self._open_capture()
            if capture is None:
                self.stop_event.wait(self.config.reconnect_seconds)
                continue
            try:
                self._consume(capture)
            finally:
                capture.release()
                self._finish_clip("stream_disconnected")
            if not self.stop_event.is_set():
                LOG.warning(
                    "Stream interrumpido; reconectando en %.1f s", self.config.reconnect_seconds
                )
                self.stop_event.wait(self.config.reconnect_seconds)

    def _open_capture(self):
        capture = cv2.VideoCapture(
            self.config.source,
            cv2.CAP_FFMPEG,
            [
                cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
                8000,
                cv2.CAP_PROP_READ_TIMEOUT_MSEC,
                8000,
            ],
        )
        if not capture.isOpened():
            capture.release()
            LOG.error("No se pudo abrir el stream V380")
            return None
        LOG.info("Stream conectado")
        return capture

    def _consume(self, capture) -> None:
        frame_period = 1.0 / self.config.fps
        next_frame = time.monotonic()
        while not self.stop_event.is_set():
            ok, frame = capture.read()
            if not ok:
                return
            now_mono = time.monotonic()
            if now_mono < next_frame:
                continue
            next_frame = now_mono + frame_period
            now_wall = datetime.now().astimezone()
            moving, area = self.detector.detect(frame)
            self.peak_motion = max(self.peak_motion, area)
            self.motion_streak = self.motion_streak + 1 if moving else 0

            if self.writer is None:
                self._remember(now_wall, frame)
                if self.motion_streak >= self.config.consecutive_frames:
                    self._start_clip(frame, now_mono)
            else:
                self.writer.write(frame)
                self.frames_written += 1
                if moving:
                    self.last_motion_mono = now_mono
                elapsed = now_mono - (self.event_started_mono or now_mono)
                silent = now_mono - (self.last_motion_mono or now_mono)
                if elapsed >= self.config.max_clip:
                    self._finish_clip("max_duration")
                    self._remember(now_wall, frame)
                elif silent >= self.config.post_roll:
                    self._finish_clip("motion_ended")

    def _remember(self, timestamp: datetime, frame: np.ndarray) -> None:
        ok, encoded = cv2.imencode(
            ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self.config.jpeg_quality]
        )
        if ok:
            self.buffer.append((timestamp, encoded.tobytes()))

    def _start_clip(self, frame: np.ndarray, now_mono: float) -> None:
        if shutil.disk_usage(self.config.output).free < self.config.min_free_gb * 1024**3:
            LOG.error("Espacio libre menor a %.1f GB; evento omitido", self.config.min_free_gb)
            self.buffer.clear()
            self.motion_streak = 0
            return
        start = self.buffer[0][0] if self.buffer else datetime.now().astimezone()
        directory = self.config.output / start.strftime("%Y-%m-%d") / self.config.camera
        directory.mkdir(parents=True, exist_ok=True)
        stem = start.strftime("%H-%M-%S") + "_movimiento"
        self.final_path = self._unique_path(directory / f"{stem}.mp4")
        self.partial_path = self.final_path.with_name(self.final_path.stem + ".partial.mp4")
        height, width = frame.shape[:2]
        self.writer = cv2.VideoWriter(
            str(self.partial_path),
            cv2.VideoWriter_fourcc(*self.config.codec),
            self.config.fps,
            (width, height),
        )
        if not self.writer.isOpened():
            self.writer.release()
            self.writer = None
            raise RuntimeError("OpenCV no pudo crear el archivo MP4")
        snapshot = self.final_path.with_suffix(".jpg")
        if not cv2.imwrite(
            str(snapshot), frame, [cv2.IMWRITE_JPEG_QUALITY, self.config.jpeg_quality]
        ):
            LOG.warning("No se pudo guardar la evidencia JPEG de %s", self.final_path)
        self.event_started_wall = start
        self.event_started_mono = now_mono
        self.last_motion_mono = now_mono
        self.frames_written = 0
        self.peak_motion = 0.0
        for _, encoded in self.buffer:
            buffered = cv2.imdecode(np.frombuffer(encoded, dtype=np.uint8), cv2.IMREAD_COLOR)
            if buffered is not None and buffered.shape[:2] == (height, width):
                self.writer.write(buffered)
                self.frames_written += 1
        self.buffer.clear()
        LOG.info("Grabando %s", self.final_path)

    def _finish_clip(self, reason: str) -> None:
        if self.writer is None:
            return
        self.writer.release()
        self.writer = None
        ended = datetime.now().astimezone()
        final_path, partial_path = self.final_path, self.partial_path
        if partial_path and final_path and partial_path.exists():
            codec = self._publish_clip(partial_path, final_path)
            metadata = {
                "camera": self.config.camera,
                "camera_name": self.config.camera_name or self.config.camera,
                "started_at": self.event_started_wall.isoformat()
                if self.event_started_wall
                else None,
                "started_at_epoch": self.event_started_wall.timestamp()
                if self.event_started_wall
                else None,
                "ended_at": ended.isoformat(),
                "ended_at_epoch": ended.timestamp(),
                "frames": self.frames_written,
                "fps": self.config.fps,
                "codec": codec,
                "objects": int(self.peak_motion) if self.config.detector == "yolo" else 0,
                **(
                    self.detector.crossing_counts
                    if self.config.detector == "yolo"
                    else {"persons_crossed": 0, "crossings_down": 0, "crossings_up": 0}
                ),
                "peak_motion_percent": (
                    0 if self.config.detector == "yolo" else round(self.peak_motion, 3)
                ),
                "close_reason": reason,
                "video": final_path.name,
            }
            final_path.with_suffix(".json").write_text(
                json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            LOG.info("Clip terminado: %s (%s)", final_path, reason)
        self.partial_path = self.final_path = None
        self.event_started_wall = None
        self.event_started_mono = self.last_motion_mono = None
        self.frames_written = 0
        self.motion_streak = 0
        self.peak_motion = 0.0
        if self.config.detector == "yolo":
            self.detector.reset_event_counts()

    @staticmethod
    def _publish_clip(partial_path: Path, final_path: Path) -> str:
        """Convierte a H.264/fMP4 compatible con navegadores antes de publicar."""
        encoded = final_path.with_name(final_path.stem + ".encoded.mp4")
        try:
            import imageio_ffmpeg

            executable = imageio_ffmpeg.get_ffmpeg_exe()
            subprocess.run(
                [
                    executable,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(partial_path),
                    "-an",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-pix_fmt",
                    "yuv420p",
                    "-movflags",
                    "+faststart",
                    str(encoded),
                ],
                check=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=120,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if not encoded.is_file() or encoded.stat().st_size == 0:
                raise OSError("FFmpeg no generó el clip final")
            os.replace(encoded, final_path)
            partial_path.unlink(missing_ok=True)
            return "h264"
        except (ImportError, OSError, subprocess.SubprocessError):
            encoded.unlink(missing_ok=True)
            os.replace(partial_path, final_path)
            LOG.exception("No se pudo convertir el clip a H.264; se conserva MP4V")
            return "mp4v"

    @staticmethod
    def _unique_path(path: Path) -> Path:
        if not path.exists() and not path.with_name(path.stem + ".partial.mp4").exists():
            return path
        for index in range(2, 10000):
            candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
            if not candidate.exists():
                return candidate
        raise RuntimeError("No se pudo generar un nombre de grabación único")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="rtsp://127.0.0.1:8556/live")
    parser.add_argument("--output", type=Path, default=Path("grabaciones_v380"))
    parser.add_argument("--camera", default="calle")
    parser.add_argument("--fps", type=float, default=15.0)
    parser.add_argument("--pre-roll", type=float, default=5.0)
    parser.add_argument("--post-roll", type=float, default=20.0)
    parser.add_argument("--max-clip", type=float, default=20.0)
    parser.add_argument("--detector", choices=("motion", "yolo"), default="motion")
    parser.add_argument("--model", type=Path, default=Path("yolo11n.pt"))
    parser.add_argument("--confidence", type=float, default=0.45)
    parser.add_argument("--min-area-percent", type=float, default=0.35)
    parser.add_argument("--threshold", type=int, default=24)
    parser.add_argument("--min-free-gb", type=float, default=2.0)
    return parser.parse_args(argv)


def config_from_args(args) -> RecorderConfig:
    config = RecorderConfig(
        source=args.source,
        output=args.output.resolve(),
        camera=args.camera,
        fps=args.fps,
        pre_roll=args.pre_roll,
        post_roll=args.post_roll,
        max_clip=args.max_clip,
        detector=args.detector,
        model=args.model.resolve(),
        confidence=args.confidence,
        min_area_percent=args.min_area_percent,
        threshold=args.threshold,
        min_free_gb=args.min_free_gb,
    )
    if config.fps <= 0 or config.pre_roll < 0 or config.post_roll < 0:
        raise SystemExit("FPS debe ser positivo y los tiempos no pueden ser negativos")
    if config.max_clip <= 0 or not 0 < config.min_area_percent <= 100:
        raise SystemExit("max-clip y min-area-percent no son válidos")
    if not 0 < config.confidence <= 1:
        raise SystemExit("confidence debe estar entre 0 y 1")
    return config


def main(argv=None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = config_from_args(parse_args(argv))
    LOG.info("Configuración: %s", {**asdict(config), "source": "[RTSP oculto]"})
    stop_event = Event()

    def stop(_signum, _frame):
        LOG.info("Deteniendo grabador...")
        stop_event.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    MotionRecorder(config, stop_event).run()


if __name__ == "__main__":
    main()
