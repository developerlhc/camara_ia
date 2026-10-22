import http.client
import json
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from tools.vigilay_recorder.agent import InstanceLock, handler_factory
from tools.vigilay_recorder.config import (
    RecorderConfigurationError,
    load_configuration,
    prune_recordings,
    recording_catalog,
)


def write_config(path: Path, output: Path, cameras=None):
    path.write_text(
        json.dumps(
            {
                "output_dir": str(output),
                "retention_days": 7,
                "min_free_gb": 0,
                "detector": "motion",
                "confidence": 0.45,
                "model": "yolo11n.pt",
                "gateway_port": 8788,
                "gateway_token": "test-token-" + "x" * 32,
                "cameras": cameras or [],
            }
        ),
        encoding="utf-8",
    )


def test_configuration_accepts_multiple_safe_sources(tmp_path):
    path = tmp_path / "recorder.json"
    write_config(
        path,
        tmp_path / "clips",
        [
            {"id": "cam-1", "name": "Entrada", "source": "rtsp://camera/live"},
            {"id": "cam_2", "name": "Caja", "source": "http://127.0.0.1/stream.mjpg"},
        ],
    )
    config = load_configuration(path)
    assert [camera.id for camera in config.cameras] == ["cam-1", "cam_2"]
    assert config.gateway_port == 8788


def test_configuration_rejects_commands_in_source(tmp_path):
    path = tmp_path / "recorder.json"
    write_config(path, tmp_path, [{"id": "cam", "name": "Cam", "source": "file:///x"}])
    with pytest.raises(RecorderConfigurationError):
        load_configuration(path)


def test_catalog_and_retention_are_confined_to_output(tmp_path):
    output = tmp_path / "clips"
    folder = output / "2026-01-01" / "cam-1"
    folder.mkdir(parents=True)
    video = folder / "10-00-00_movimiento.mp4"
    video.write_bytes(b"video")
    snapshot = video.with_suffix(".jpg")
    snapshot.write_bytes(b"jpeg")
    video.with_suffix(".json").write_text(
        json.dumps(
            {
                "camera_name": "Entrada",
                "started_at_epoch": 100,
                "ended_at_epoch": 120,
                "peak_motion_percent": 3,
                "persons_crossed": 2,
                "crossings_down": 1,
                "crossings_up": 1,
            }
        ),
        encoding="utf-8",
    )
    item = recording_catalog(output, camera_id="cam-1", after=90, before=130)[0]
    assert item["size"] == 5
    assert item["persons_crossed"] == 2
    assert item["crossings_down"] == 1
    assert item["crossings_up"] == 1
    assert item["snapshot_id"] == "2026-01-01/cam-1/10-00-00_movimiento.jpg"
    old = time.time() - 10 * 86400
    video.touch()
    import os

    os.utime(video, (old, old))
    assert prune_recordings(output, retention_days=1, min_free_gb=0) == 1
    assert not video.exists()
    assert not snapshot.exists()


def test_local_api_requires_token_and_supports_ranges(tmp_path):
    output = tmp_path / "clips"
    folder = output / "2026-01-01" / "cam-1"
    folder.mkdir(parents=True)
    video = folder / "10-00-00_movimiento.mp4"
    video.write_bytes(b"0123456789")
    video.with_suffix(".jpg").write_bytes(b"jpeg-data")
    video.with_suffix(".json").write_text(
        json.dumps(
            {
                "camera_name": "Entrada",
                "started_at_epoch": 100,
                "ended_at_epoch": 110,
                "persons_crossed": 2,
                "crossings_down": 1,
                "crossings_up": 1,
            }
        ),
        encoding="utf-8",
    )
    config_path = tmp_path / "recorder.json"
    write_config(
        config_path,
        output,
        [{"id": "cam-1", "name": "Entrada", "source": "rtsp://camera/live"}],
    )
    config = load_configuration(config_path)
    stop_event = threading.Event()
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_factory(config, stop_event))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        connection.request("GET", "/api/recordings?camera_id=cam-1&after=90&before=120")
        assert connection.getresponse().status == 401
        connection.close()

        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        connection.request(
            "GET",
            "/api/recordings/file?id=2026-01-01/cam-1/10-00-00_movimiento.mp4",
            headers={"Authorization": "Bearer test-token-" + "x" * 32, "Range": "bytes=2-5"},
        )
        response = connection.getresponse()
        assert response.status == 206
        assert response.read() == b"2345"
        connection.close()

        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        connection.request(
            "GET",
            "/api/recordings/file?id=2026-01-01/cam-1/10-00-00_movimiento.mp4",
            headers={"Authorization": "Bearer test-token-" + "x" * 32, "Range": "bytes=-3"},
        )
        response = connection.getresponse()
        assert response.status == 206
        assert response.read() == b"789"
        connection.close()

        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        connection.request(
            "GET",
            "/api/recordings/file?id=2026-01-01/cam-1/10-00-00_movimiento.jpg",
            headers={"Authorization": "Bearer test-token-" + "x" * 32},
        )
        response = connection.getresponse()
        assert response.status == 200
        assert response.getheader("Content-Type") == "image/jpeg"
        assert response.read() == b"jpeg-data"
        connection.close()

        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        connection.request(
            "GET",
            "/api/events?after=90&before=120",
            headers={"Authorization": "Bearer test-token-" + "x" * 32},
        )
        response = connection.getresponse()
        assert response.status == 200
        event = json.loads(response.read())[0]
        assert event["persons_crossed"] == 2
        assert event["crossings_down"] == 1
        assert event["crossings_up"] == 1
        connection.close()

        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        connection.request("POST", "/api/shutdown")
        assert connection.getresponse().status == 401
        connection.close()

        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        connection.request(
            "POST",
            "/api/shutdown",
            headers={"Authorization": "Bearer test-token-" + "x" * 32},
        )
        response = connection.getresponse()
        assert response.status == 202
        assert json.loads(response.read()) == {"stopping": True}
        assert stop_event.wait(1)
        connection.close()
    finally:
        server.shutdown()
        server.server_close()


def test_recorder_allows_only_one_instance_per_configuration(tmp_path):
    first = InstanceLock(tmp_path / "recorder.json")
    second = InstanceLock(tmp_path / "recorder.json")
    first.acquire()
    try:
        with pytest.raises(RuntimeError, match="ya está activo"):
            second.acquire()
    finally:
        first.release()
    second.acquire()
    second.release()
