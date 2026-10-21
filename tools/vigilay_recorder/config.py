"""Configuracion validada y catalogo local del grabador Vigilay."""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


class RecorderConfigurationError(ValueError):
    """Error seguro para mostrar en Desktop."""


@dataclass(frozen=True)
class CameraConfiguration:
    id: str
    name: str
    source: str
    fps: float = 15.0
    enabled: bool = True


@dataclass(frozen=True)
class AgentConfiguration:
    output_dir: Path
    retention_days: int
    min_free_gb: float
    detector: str
    confidence: float
    model: Path
    gateway_port: int
    gateway_token: str
    cameras: tuple[CameraConfiguration, ...]


def _safe_camera_id(value: object) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 80 or not all(c.isalnum() or c in "-_" for c in text):
        raise RecorderConfigurationError("El identificador de camara no es valido")
    return text


def _source(value: object) -> str:
    text = str(value or "").strip()
    try:
        parsed = urlsplit(text)
    except ValueError as exc:
        raise RecorderConfigurationError("La fuente de video no es valida") from exc
    if parsed.scheme not in {"rtsp", "rtsps", "http", "https"} or not parsed.hostname:
        raise RecorderConfigurationError("La fuente debe usar RTSP o HTTP y tener un host")
    if parsed.fragment or any(ord(char) < 32 for char in text) or len(text) > 2048:
        raise RecorderConfigurationError("La fuente de video contiene datos no permitidos")
    return text


def load_configuration(path: Path) -> AgentConfiguration:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RecorderConfigurationError("No se pudo leer la configuracion del grabador") from exc
    try:
        output = Path(data["output_dir"]).expanduser().resolve()
        retention = int(data.get("retention_days", 7))
        min_free = float(data.get("min_free_gb", 2))
        detector = str(data.get("detector", "yolo"))
        confidence = float(data.get("confidence", 0.45))
        model_value = Path(data.get("model") or "yolo11n.pt").expanduser()
        if not model_value.is_absolute() and getattr(sys, "frozen", False):
            model_value = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / model_value
        model = model_value.resolve()
        gateway_port = int(data.get("gateway_port", 8788))
        gateway_token = str(data.get("gateway_token") or "")
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise RecorderConfigurationError("La configuracion del grabador esta incompleta") from exc
    if not 1 <= retention <= 365:
        raise RecorderConfigurationError("La retencion debe estar entre 1 y 365 dias")
    if not 0 <= min_free <= 1024:
        raise RecorderConfigurationError("La reserva de espacio no es valida")
    if detector not in {"motion", "yolo"}:
        raise RecorderConfigurationError("El detector debe ser motion o yolo")
    if not 0.1 <= confidence <= 0.95:
        raise RecorderConfigurationError("La confianza debe estar entre 0.1 y 0.95")
    if not 1024 <= gateway_port <= 65535:
        raise RecorderConfigurationError("El puerto local del grabador no es valido")
    if len(gateway_token) < 32 or len(gateway_token) > 256:
        raise RecorderConfigurationError("La credencial local del grabador no es valida")
    if detector == "yolo" and not model.is_file():
        raise RecorderConfigurationError("No se encontro el modelo de deteccion YOLO")
    cameras = []
    seen = set()
    for item in data.get("cameras", []):
        camera_id = _safe_camera_id(item.get("id"))
        if camera_id in seen:
            raise RecorderConfigurationError("Hay una camara duplicada en la configuracion")
        seen.add(camera_id)
        name = str(item.get("name") or "").strip()
        if not name or len(name) > 160:
            raise RecorderConfigurationError("El nombre de una camara no es valido")
        fps = float(item.get("fps", 15))
        if not 1 <= fps <= 30:
            raise RecorderConfigurationError("Los FPS deben estar entre 1 y 30")
        cameras.append(
            CameraConfiguration(
                id=camera_id,
                name=name,
                source=_source(item.get("source")),
                fps=fps,
                enabled=bool(item.get("enabled", True)),
            )
        )
    return AgentConfiguration(
        output_dir=output,
        retention_days=retention,
        min_free_gb=min_free,
        detector=detector,
        confidence=confidence,
        model=model,
        gateway_port=gateway_port,
        gateway_token=gateway_token,
        cameras=tuple(cameras),
    )


def recording_catalog(output_dir: Path, *, camera_id="", after=0, before=None) -> list[dict]:
    """Lee solo metadatos contiguos; nunca confia en rutas incluidas en el JSON."""
    root = output_dir.resolve()
    before = before if before is not None else time.time()
    rows = []
    if not root.is_dir():
        return rows
    for metadata_path in root.glob("????-??-??/*/*.json"):
        try:
            resolved = metadata_path.resolve()
            resolved.relative_to(root)
            data = json.loads(resolved.read_text(encoding="utf-8"))
            video = resolved.with_suffix(".mp4")
            started = float(data.get("started_at_epoch") or video.stat().st_mtime)
            ended = float(data.get("ended_at_epoch") or started)
            item_camera = resolved.parent.name
            if not video.is_file() or (camera_id and item_camera != camera_id):
                continue
            if ended < after or started > before:
                continue
            relative = video.relative_to(root).as_posix()
            snapshot = video.with_suffix(".jpg")
            rows.append(
                {
                    "id": relative,
                    "camera_id": item_camera,
                    "camera_name": data.get("camera_name") or data.get("camera") or item_camera,
                    "start": started,
                    "end": ended,
                    "duration": round(max(0, ended - started), 1),
                    "objects": int(data.get("objects") or 0),
                    "persons_crossed": int(data.get("persons_crossed") or 0),
                    "crossings_down": int(data.get("crossings_down") or 0),
                    "crossings_up": int(data.get("crossings_up") or 0),
                    "motion": round(float(data.get("peak_motion_percent") or 0), 3),
                    "size": video.stat().st_size,
                    "snapshot_id": snapshot.relative_to(root).as_posix()
                    if snapshot.is_file()
                    else None,
                }
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
    return sorted(rows, key=lambda item: item["start"], reverse=True)


def prune_recordings(output_dir: Path, retention_days: int, min_free_gb: float) -> int:
    """Elimina clips vencidos y luego los mas antiguos hasta recuperar la reserva."""
    root = output_dir.resolve()
    if not root.is_dir():
        return 0
    cutoff = time.time() - retention_days * 86400
    videos = []
    for video in root.glob("????-??-??/*/*.mp4"):
        try:
            videos.append((video.stat().st_mtime, video))
        except OSError:
            continue
    videos.sort(key=lambda item: item[0])
    removed = 0
    for modified, video in videos:
        expired = modified < cutoff
        try:
            low_space = shutil.disk_usage(root).free < min_free_gb * 1024**3
        except OSError:
            break
        if not expired and not low_space:
            continue
        for target in (video, video.with_suffix(".json"), video.with_suffix(".jpg")):
            try:
                target.resolve().relative_to(root)
                target.unlink(missing_ok=True)
            except OSError:
                pass
        removed += 1
    for directory in sorted(root.glob("????-??-??/*"), reverse=True):
        try:
            directory.rmdir()
            directory.parent.rmdir()
        except OSError:
            pass
    return removed


def private_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".pending")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    os.replace(temporary, path)
