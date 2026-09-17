"""Exercise legacy live classes without booting cameras or the Flask app on import."""

import ast
import ipaddress
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def classes():
    path = Path(__file__).resolve().parents[1] / "camara-ia.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    namespace = {"threading": threading, "time": time, "datetime": datetime, "os": os}
    declarations = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name in {"CameraAnalytics", "CameraPreviewHub"}
    ]
    exec(compile(ast.Module(body=declarations, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


def test_late_frame_from_previous_camera_is_discarded(classes):
    analytics = classes["CameraAnalytics"].__new__(classes["CameraAnalytics"])
    analytics.lock = threading.Lock()
    analytics.stop_event = threading.Event()
    analytics.camera_changed = threading.Event()
    analytics.active_camera_id = "a"
    analytics.cameras = {"a": {"id": "a", "rtsp_url": "rtsp://test/a", "target_fps": 10}}
    analytics.latest_jpeg = None
    capture = SimpleNamespace(set=lambda *a: None, isOpened=lambda: True, release=lambda: None)
    fake_cv = SimpleNamespace(
        VideoCapture=lambda *a: capture,
        CAP_FFMPEG=1,
        CAP_PROP_OPEN_TIMEOUT_MSEC=2,
        CAP_PROP_READ_TIMEOUT_MSEC=3,
        CAP_PROP_BUFFERSIZE=4,
        CAP_PROP_FRAME_WIDTH=5,
        CAP_PROP_FRAME_HEIGHT=6,
    )
    classes.update(cv2=fake_cv, CAMERA_WIDTH=1920, CAMERA_HEIGHT=1080, TARGET_FPS=10)

    def read(_):
        analytics.active_camera_id = "b"
        analytics.camera_changed.set()
        analytics.stop_event.set()
        return True, object()

    analytics._read_latest_frame = read
    analytics._run()
    assert analytics.latest_jpeg is None


def test_open_socket_without_fresh_frames_is_not_online(classes):
    analytics = classes["CameraAnalytics"].__new__(classes["CameraAnalytics"])
    analytics.lock = threading.Lock()
    analytics.status = {"camera_online": True, "display_fps": 10}
    analytics.last_frame_at = time.monotonic() - 10
    analytics.latest_jpeg = b"old"
    analytics.latest_frame_version = 5
    assert analytics.get_status() == {"camera_online": False, "display_fps": 0}
    assert analytics.get_jpeg_packet() == (None, 5)
    analytics.last_frame_at = time.monotonic()
    assert analytics.get_jpeg_packet() == (b"old", 5)


def test_active_camera_never_falls_back_to_stale_thumbnail(classes):
    hub = classes["CameraPreviewHub"](
        SimpleNamespace(
            cameras={"a": {}}, active_camera_id="a", get_jpeg_packet=lambda _: (None, 0)
        )
    )
    hub.states["a"] = {"jpeg": b"old", "version": 8, "online": True}
    assert hub.get_packet("a")[0] is None


def test_offline_preview_clears_image_and_expires_without_frames(classes):
    hub = classes["CameraPreviewHub"](SimpleNamespace(active_camera_id="other"))
    hub.states["a"] = {"jpeg": b"old", "online": True, "last_frame_at": time.monotonic() - 10}
    assert not hub.camera_online("a")
    hub._set_offline("a")
    assert hub.states["a"]["jpeg"] is None


def test_primary_read_does_not_wait_for_fourteen_extra_frames(classes):
    classes["DROP_BUFFER_FRAMES"] = 0
    analytics = classes["CameraAnalytics"].__new__(classes["CameraAnalytics"])

    def unexpected_grab():
        raise AssertionError("Must not wait for future frames")

    capture = SimpleNamespace(grab=unexpected_grab, read=lambda: (True, b"frame"))
    assert analytics._read_latest_frame(capture) == (True, b"frame")


def test_edit_without_frigate_field_preserves_mapping_and_cloud_source(classes, monkeypatch):
    monkeypatch.setenv("CAMERA_STORAGE", "mysql")
    stored = dict(
        id="a",
        name="V380",
        model="",
        brand="V380",
        integration_type="V380",
        host="192.168.1.20",
        username="test",
        password="test-only",
        device_id="test",
        source="cloud",
        frigate_camera_name="calle",
        port=8800,
        rtsp_port=8556,
        http_port=8081,
        quality="sd",
        target_fps=10,
        grayscale=False,
    )
    updates = []

    def update(camera_id, **kwargs):
        updates.append(kwargs)
        return {**stored, **kwargs}

    monkeypatch.setitem(
        sys.modules,
        "camera_store",
        SimpleNamespace(get_runtime_camera=lambda _: dict(stored), update_camera=update),
    )
    classes.update(
        ipaddress=ipaddress,
        validate_frigate_camera_name=lambda name: name,
        preview_source=lambda camera: dict(camera),
    )
    analytics = classes["CameraAnalytics"].__new__(classes["CameraAnalytics"])
    analytics.lock = threading.Lock()
    analytics.cameras = {"a": dict(stored)}
    analytics.active_camera_id = "other"
    analytics.update_camera_configuration("a", {"name": "V380", "target_fps": 8})
    assert updates[0]["frigate_camera_name"] == "calle"
    assert updates[0]["secret"]["source"] == "cloud"
    assert updates[0]["secret"]["rtsp_port"] == 8556
