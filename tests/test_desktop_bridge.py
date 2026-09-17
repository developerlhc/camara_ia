import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "desktop_bridge", Path(__file__).resolve().parents[1] / "apps/desktop/resources/bridge.py"
)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


def camera(**extra):
    return {
        "id": "test-camera",
        "name": "Entrada",
        "integration_type": "RTSP",
        "rtsp_url": "rtsp://test:synthetic-secret@192.168.1.10:554/main",
        "frigate_camera_name": "entrada",
        **extra,
    }


def test_desktop_export_keeps_full_recording_and_uses_substream_for_detection():
    config, mappings = bridge.plan([camera(rtsp_substream_url="rtsp://192.168.1.10/sub")], 7)
    assert config["go2rtc"]["streams"]["entrada"] == [camera()["rtsp_url"]]
    assert config["go2rtc"]["streams"]["entrada_live"] == ["rtsp://192.168.1.10/sub"]
    inputs = config["cameras"]["entrada"]["ffmpeg"]["inputs"]
    assert inputs[0]["roles"] == ["record"] and inputs[1]["roles"] == ["detect"]
    assert config["cameras"]["entrada"]["detect"]["fps"] == 5
    assert config["cameras"]["entrada"]["record"]["continuous"]["days"] == 7
    assert config["auth"]["enabled"] is True
    assert config["go2rtc"]["webrtc"]["candidates"] == ["127.0.0.1:18555"]
    assert "synthetic-secret" not in json.dumps(mappings)
    assert "reset_admin_password" not in config["auth"]


def test_desktop_export_shares_one_source_without_substream():
    config, _ = bridge.plan([camera()])
    assert len(config["go2rtc"]["streams"]) == 1
    assert config["cameras"]["entrada"]["ffmpeg"]["inputs"][0]["roles"] == ["record", "detect"]


@pytest.mark.parametrize(
    "source",
    [
        "exec:danger",
        "ffmpeg:rtsp://test",
        "file:///etc/passwd",
        "rtsp://camera/live#exec=x",
        "rtsp://camera/\nsecret",
    ],
)
def test_desktop_export_rejects_non_rtsp_or_injected_sources(source):
    with pytest.raises(ValueError):
        bridge.plan([camera(rtsp_url=source)])


@pytest.mark.parametrize("days", [0, 31, -1, True, "3"])
def test_desktop_export_limits_retention(days):
    with pytest.raises(ValueError):
        bridge.plan([camera()], days)


def test_desktop_export_preserves_v380_mapping_and_external_bridge():
    config, _ = bridge.plan(
        [camera(integration_type="V380", frigate_camera_name="calle", rtsp_port=8556)]
    )
    assert config["go2rtc"]["streams"]["calle"] == ["rtsp://host.docker.internal:8556/live"]


def test_desktop_export_rejects_alias_collisions():
    with pytest.raises(ValueError):
        bridge.plan([camera(), camera(id="other", frigate_camera_name="entrada_live")])


def test_desktop_export_backup_and_manual_change_protection(tmp_path):
    config, mappings = bridge.plan([camera()])
    scope = {"tenant_id": "test-tenant", "site_id": "test-site"}
    bridge.export_config(tmp_path, config, mappings, scope)
    bridge.export_config(tmp_path, config, mappings, scope)
    directory = tmp_path / "frigate/config"
    assert len(list(directory.glob("*.bak"))) == 1
    original = (directory / "config.yml").read_bytes()
    assert list(directory.glob("*.bak"))[0].read_bytes() == original
    with pytest.raises(ValueError, match="otra empresa"):
        bridge.export_config(tmp_path, config, mappings, {**scope, "site_id": "other"})
    (directory / "config.yml").write_text("# technician change\n" + original.decode())
    with pytest.raises(ValueError, match="manuales"):
        bridge.export_config(tmp_path, config, mappings, scope)
    assert (directory / "config.yml").read_text().startswith("# technician change")


def test_desktop_never_adopts_unmanaged_frigate(tmp_path):
    directory = tmp_path / "frigate/config"
    directory.mkdir(parents=True)
    (directory / "config.yml").write_text("private original")
    with pytest.raises(ValueError, match="no fue creada"):
        bridge.export_config(tmp_path, {}, [], {})
    assert (directory / "config.yml").read_text() == "private original"


def test_desktop_never_returns_credentials_to_ui():
    visible = json.dumps(
        bridge.safe_cameras([camera(password="never-return", device_id="private")])
    )
    assert "synthetic-secret" not in visible and "never-return" not in visible
    assert "rtsp_url" not in visible and "private" not in visible


def test_desktop_revalidates_scope_before_access(monkeypatch):
    import camera_store

    monkeypatch.setattr(
        camera_store,
        "local_scope_catalog",
        lambda: {"configured": {"tenant_id": "a", "site_id": "a-site"}},
    )
    with pytest.raises(ValueError, match="cambió"):
        bridge.execute({"action": "cameras", "scope": {"tenant_id": "b", "site_id": "b-site"}})


def test_desktop_saves_real_rtsp_in_scoped_test_database(monkeypatch, tmp_path, cameras):
    import camera_store

    monkeypatch.setattr(camera_store, "LOCAL_IDENTITY_PATH", tmp_path / "identity.json")
    own = cameras["a"]
    scope = {"tenant_id": own["tenant_id"], "site_id": own["site_id"]}
    camera_store.configure_local_scope(**scope)
    saved = bridge.execute(
        {
            "action": "save_camera",
            "scope": scope,
            "camera": {
                "name": "Desktop RTSP",
                "brand": "TEST",
                "rtsp_url": camera()["rtsp_url"],
                "rtsp_substream_url": "rtsp://192.168.1.10/sub",
            },
        }
    )
    assert saved["name"] == "Desktop RTSP" and "rtsp_url" not in saved
    stored = bridge.scoped_cameras(camera_store, saved["id"])[0]
    assert stored["rtsp_url"] == camera()["rtsp_url"]
    assert stored["rtsp_substream_url"] == "rtsp://192.168.1.10/sub"
    bridge.execute(
        {
            "action": "save_camera",
            "scope": scope,
            "camera": {
                "id": saved["id"],
                "name": "Renamed",
                "rtsp_url": "",
                "rtsp_substream_url": "",
            },
        }
    )
    updated = bridge.scoped_cameras(camera_store, saved["id"])[0]
    assert updated["rtsp_url"] == camera()["rtsp_url"]
    assert updated["rtsp_substream_url"] == "rtsp://192.168.1.10/sub"
    with pytest.raises(KeyError):
        bridge.execute(
            {
                "action": "save_camera",
                "scope": scope,
                "camera": {
                    "id": cameras["b"]["id"],
                    "name": "Not authorized",
                    "rtsp_url": camera()["rtsp_url"],
                },
            }
        )
