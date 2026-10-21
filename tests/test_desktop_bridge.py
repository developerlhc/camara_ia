"""Contract checks for the credential-free desktop installer."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "apps" / "desktop"


def test_installer_uses_web_account_and_not_database_credentials():
    html = (ROOT / "index.html").read_text(encoding="utf-8").lower()
    rust = (ROOT / "src-tauri/src/deployment.rs").read_text(encoding="utf-8").lower()
    assert "usuario o correo" in html
    assert "/api/v1/auth/login" in rust
    assert "bdmysql" not in html + rust
    assert "encryption_key" not in html + rust


def test_installer_has_no_frigate_runtime_or_credentials():
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [
            ROOT / "index.html",
            ROOT / "src/main.ts",
            ROOT / "src-tauri/src/deployment.rs",
            ROOT / "src-tauri/src/main.rs",
        ]
    ).lower()
    assert "frigate" not in sources
    assert "docker" not in sources


def test_installer_supports_admin_catalog_and_camera_creation():
    rust = (ROOT / "src-tauri/src/deployment.rs").read_text(encoding="utf-8")
    for route in ["/api/v1/tenants", "/api/v1/sites", "/api/v1/cameras"]:
        assert route in rust
    assert "/recorder-cameras" in rust
    assert "sync_recording_cameras" in rust


def test_desktop_uses_tauri_camel_case_arguments_and_supports_viewers():
    typescript = (ROOT / "src/main.ts").read_text(encoding="utf-8")
    rust = (ROOT / "src-tauri/src/deployment.rs").read_text(encoding="utf-8")
    assert "tenantId: scope.tenant_id" in typescript
    assert "siteId: scope.site_id" in typescript
    assert "Esta cuenta no tiene permisos de administración" not in rust
    for command in ["start_live", "heartbeat_live", "stop_live"]:
        assert command in typescript and command in rust


def test_desktop_starts_the_local_video_agent_automatically():
    typescript = (ROOT / "src/main.ts").read_text(encoding="utf-8")
    rust = (ROOT / "src-tauri/src/deployment.rs").read_text(encoding="utf-8")
    powershell = (ROOT.parents[1] / "scripts/asegurar-agente-stream.ps1").read_text(
        encoding="utf-8"
    )
    assert "void ensureVideoAgent()" in typescript
    assert "ensure_stream_agent" in rust
    assert "asegurar-agente-stream.ps1" in rust
    assert "Get-CimInstance" not in powershell


def test_installer_controls_its_own_recorder_and_storage_path():
    html = (ROOT / "index.html").read_text(encoding="utf-8").lower()
    rust = (ROOT / "src-tauri/src/deployment.rs").read_text(encoding="utf-8").lower()
    assert "carpeta de grabaciones" in html
    assert "start_recorder" in rust
    assert "stop_recorder" in rust
    assert "retention_days" in rust
    assert "frigate" not in html + rust


def test_installer_bundles_cloudflared_for_recording_tunnel():
    bundle = (ROOT / "src-tauri/tauri.bundle.conf.json").read_text(encoding="utf-8")
    rust = (ROOT / "src-tauri/src/deployment.rs").read_text(encoding="utf-8")
    build = (ROOT.parents[1] / "scripts/build-desktop-recorder.ps1").read_text(encoding="utf-8")
    assert '"binaries/cloudflared"' in bundle
    assert 'parent.join("cloudflared.exe")' in rust
    assert "cloudflared-windows-amd64.exe" in build
    assert "System.Security.Cryptography.SHA256" in build
    assert "ComputeHash($cloudflaredStream)" in build


def test_password_is_not_persisted():
    rust = (ROOT / "src-tauri/src/deployment.rs").read_text(encoding="utf-8")
    assert "settings.password" in rust
    session_fields = rust.split("struct Session", 1)[1].split("}", 1)[0]
    assert "password" not in session_fields
    recorder_fields = rust.split("struct RecorderSettings", 1)[1].split("}", 1)[0]
    assert "password" not in recorder_fields
