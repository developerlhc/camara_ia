import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "local_runtime", Path(__file__).resolve().parents[1] / "local_runtime.py"
)
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def test_preview_keeps_direct_rtsp_without_mutating_camera():
    camera = {
        "host": "192.168.1.10",
        "username": "test",
        "password": "test-only",
        "rtsp_url": "rtsp://camera/live",
    }
    assert runtime.preview_source(camera) == camera
    assert runtime.preview_source(camera) is not camera


def test_v380_uses_host_bridge_without_mutating_secret(monkeypatch):
    monkeypatch.setenv("V380_EXTERNAL_BRIDGE_HOST", "host.docker.internal")
    camera = {"host": "192.168.1.10", "password": "test-only", "rtsp_port": 8556}
    result = runtime.external_v380(camera)
    assert result["rtsp_url"] == "rtsp://host.docker.internal:8556/live"
    assert result["source_host"] == "192.168.1.10"
    assert result["password"] == ""
    assert camera["password"] == "test-only"


def test_container_discovery_requires_lan(monkeypatch):
    monkeypatch.setenv("VIGILAY_LOCAL_CONTAINER", "true")
    monkeypatch.delenv("VIGILAY_LOCAL_LAN_CIDR", raising=False)
    with pytest.raises(OSError, match="subred"):
        runtime.discovery_network("172.18.0.2")


def test_v380_mjpeg_preview_keeps_rtsp_input_unchanged(monkeypatch):
    monkeypatch.setenv("V380_LOCAL_TRANSPORT", "mjpeg")
    camera = {
        "integration_type": "V380",
        "host": "127.0.0.1",
        "http_port": 8081,
        "rtsp_url": "rtsp://127.0.0.1:8556/live",
    }
    result = runtime.preview_source(camera)
    assert result["rtsp_url"] == "http://127.0.0.1:8081/stream.mjpg"
    assert camera["rtsp_url"].startswith("rtsp:")


@pytest.mark.parametrize("cidr", ["0.0.0.0/0", "192.168.0.0/16", "8.8.8.0/24", "bad"])
def test_discovery_rejects_broad_or_public_networks(monkeypatch, cidr):
    monkeypatch.setenv("VIGILAY_LOCAL_LAN_CIDR", cidr)
    with pytest.raises(OSError):
        runtime.discovery_network("172.18.0.2")


def test_discovery_uses_explicit_lan_not_docker_network(monkeypatch):
    monkeypatch.setenv("VIGILAY_LOCAL_LAN_CIDR", "192.168.1.0/24")
    assert str(runtime.discovery_network("172.18.0.2")) == "192.168.1.0/24"
