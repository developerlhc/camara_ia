"""Desktop's stdin/stdout bridge, executed inside its own Vigilay Local container.

No HTTP endpoint exposes camera secrets. Docker access is the technician boundary.
Only generated configuration under /deployment is managed; existing NVRs are untouched.
"""

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


class ValidationError(ValueError):
    """Safe user-facing message; library exceptions are never rendered."""


ALIAS = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def rtsp_source(value):
    value = str(value or "")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"rtsp", "rtsps"}
        or not parsed.hostname
        or parsed.fragment
        or any(ord(c) < 32 for c in value)
        or len(value) > 2048
    ):
        raise ValidationError("La fuente debe ser una URL RTSP válida, sin fragmentos ni comandos.")
    return value


def plan(cameras, days=3):
    if not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= 30:
        raise ValidationError("La retención debe estar entre 1 y 30 días.")
    config = {
        "mqtt": {"enabled": False},
        "auth": {"enabled": True, "cookie_secure": True},
        "detectors": {"cpu": {"type": "cpu"}},
        # Desktop publishes only loopback, with a host port different from go2rtc's 8555.
        "go2rtc": {"streams": {}, "webrtc": {"candidates": ["127.0.0.1:18555"]}},
        "cameras": {},
    }
    mappings = []
    used = set()
    for camera in cameras:
        if camera.get("integration_type") == "SIMULATOR":
            continue
        alias = camera.get("frigate_camera_name") or "cam_" + camera["id"].replace("-", "")
        if not ALIAS.fullmatch(alias) or alias in used or alias + "_live" in used:
            raise ValidationError(
                "Alias Frigate inválido o duplicado; corrige la cámara antes de exportar."
            )
        used.update((alias, alias + "_live"))
        if camera.get("integration_type") == "V380":
            # The proprietary Windows bridge is external to the Linux container.
            port = int(camera.get("rtsp_port", 8556))
            if not 1024 <= port <= 65535:
                raise ValidationError("Puerto del puente V380 inválido.")
            source = f"rtsp://host.docker.internal:{port}/live"
        else:
            source = rtsp_source(camera.get("rtsp_url"))
        live = rtsp_source(camera.get("rtsp_substream_url") or source)
        streams = config["go2rtc"]["streams"]
        streams[alias] = [source]
        if live != source:
            streams[alias + "_live"] = [live]
        live_alias = alias + "_live" if live != source else alias
        record_input = {"path": f"rtsp://127.0.0.1:8554/{alias}", "roles": ["record"]}
        inputs = [record_input]
        if live_alias == alias:
            record_input["roles"].append("detect")
        else:
            inputs.append({"path": f"rtsp://127.0.0.1:8554/{live_alias}", "roles": ["detect"]})
        config["cameras"][alias] = {
            "ffmpeg": {"input_args": "preset-rtsp-restream", "inputs": inputs},
            "detect": {"enabled": True, "fps": 5},
            "record": {
                "enabled": True,
                "continuous": {"days": days},
                "alerts": {"retain": {"days": days}},
                "detections": {"retain": {"days": days}},
            },
            "live": {"streams": {"Principal": live_alias}},
            "snapshots": {"enabled": True},
        }
        mappings.append({"id": camera["id"], "name": camera["name"], "alias": alias})
    return config, mappings


def digest(data):
    return hashlib.sha256(data).hexdigest()


def export_config(root, config, mappings, scope):
    directory = Path(root) / "frigate" / "config"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "config.yml"
    marker = directory / ".vigilay-managed.json"
    if target.is_symlink() or marker.is_symlink():
        raise ValidationError("No se admiten enlaces simbólicos en la configuración administrada.")
    if target.exists():
        if not marker.exists():
            raise ValidationError(
                "Esta configuración no fue creada por Desktop; no se sobrescribió."
            )
        previous = json.loads(marker.read_text(encoding="utf-8"))
        if previous.get("scope") != scope:
            raise ValidationError(
                "La instalación pertenece a otra empresa/sede; no se sobrescribió."
            )
        if previous.get("sha256") != digest(target.read_bytes()):
            raise ValidationError(
                "Hay cambios manuales en Frigate; respáldalos y revísalos antes de exportar."
            )
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = directory / f"config.{stamp}.bak"
        backup.write_bytes(target.read_bytes())
        os.chmod(backup, 0o600)
    # JSON is valid YAML; structured serialization prevents YAML/source injection.
    data = (json.dumps(config, ensure_ascii=False, indent=2) + "\n").encode()
    temporary = directory / "config.pending"
    temporary.write_bytes(data)
    os.chmod(temporary, 0o600)
    temporary.replace(target)
    marker.write_text(
        json.dumps({"scope": scope, "sha256": digest(data), "mappings": mappings}), encoding="utf-8"
    )
    os.chmod(marker, 0o600)
    return {
        "cameras": mappings,
        "exported": True,
        "warning": "El archivo contiene fuentes privadas.",
    }


def safe_cameras(cameras):
    return [
        {
            key: row.get(key)
            for key in ("id", "name", "brand", "integration_type", "frigate_camera_name")
        }
        for row in cameras
    ]


def scoped_cameras(store, camera_id=None):
    """Batch-load secrets locally, including substreams omitted by older Local DTOs."""
    from sqlalchemy import select
    from vigilay.db import system_session
    from vigilay.models import Camera, CameraCredential
    from vigilay.security import decrypt_credentials

    with system_session() as db:
        tenant, site = store.get_local_scope(db)
        statement = (
            select(Camera, CameraCredential)
            .join(CameraCredential, CameraCredential.camera_id == Camera.id)
            .where(
                Camera.tenant_id == tenant.id,
                Camera.site_id == site.id,
                CameraCredential.tenant_id == tenant.id,
                Camera.integration_type.in_(["RTSP", "V380"]),
            )
            .order_by(Camera.created_at, Camera.name)
        )
        statement = statement.where(
            Camera.id == camera_id if camera_id else Camera.enabled.is_(True)
        )
        result = []
        for row, credential in db.execute(statement):
            secret = decrypt_credentials(credential.secret_encrypted, tenant.id, row.id)
            runtime = store._runtime_camera(row, secret)
            if secret.get("rtsp_substream_url"):
                runtime["rtsp_substream_url"] = secret["rtsp_substream_url"]
            result.append(runtime)
        if camera_id and not result:
            raise KeyError(camera_id)
        return result


def execute(payload):
    sys.path.insert(0, "/app")
    import camera_store as store

    action = payload.get("action")
    if action == "catalog":
        return store.local_scope_catalog()
    if action == "configure_scope":
        values = payload.get("scope", {})
        marker = Path("/deployment/frigate/config/.vigilay-managed.json")
        if marker.exists():
            installed = json.loads(marker.read_text())["scope"]
            if any(values.get(key) != installed[key] for key in ("tenant_id", "site_id")):
                raise ValidationError(
                    "Esta instalación ya administra otra sede. No se reasignaron cámaras ni grabaciones."
                )
        allowed = {"tenant_id", "tenant_name", "site_id", "site_name", "address"}
        return store.configure_local_scope(**{k: v for k, v in values.items() if k in allowed})
    catalog = store.local_scope_catalog()
    selected = catalog.get("configured")
    if not selected:
        raise ValidationError("Configura primero una empresa activa y su sede.")
    scope = {key: selected[key] for key in ("tenant_id", "site_id")}
    if payload.get("scope") != scope:
        raise ValidationError("La empresa/sede cambió; actualiza el asistente antes de continuar.")
    if action == "cameras":
        return safe_cameras(scoped_cameras(store))
    if action == "save_camera":
        values = payload["camera"]
        name = str(values.get("name", "")).strip()
        if not name or len(name) > 160:
            raise ValidationError("Indica un nombre de cámara de hasta 160 caracteres.")
        camera_id = values.get("id")
        current = scoped_cameras(store, camera_id)[0] if camera_id else None
        if current and current["integration_type"] != "RTSP":
            raise ValidationError("Edita las conexiones propietarias V380 desde Vigilay Local.")
        secret = {
            "rtsp_url": rtsp_source(values.get("rtsp_url") or (current or {}).get("rtsp_url"))
        }
        substream = values.get("rtsp_substream_url") or (current or {}).get("rtsp_substream_url")
        if substream:
            secret["rtsp_substream_url"] = rtsp_source(substream)
        # Do not lose ONVIF settings when editing a URL.
        secret["onvif_port"] = int((current or {}).get("onvif_port", 80))
        if camera_id:
            row = store.update_camera(
                camera_id,
                name=name,
                model=current.get("model", ""),
                secret=secret,
                frigate_camera_name=current.get("frigate_camera_name"),
                target_fps=current.get("target_fps", 10),
                grayscale=current.get("grayscale", False),
            )
        else:
            row = store.save_camera(
                name=name,
                brand=str(values.get("brand", "GENERIC"))[:60],
                model="",
                integration_type="RTSP",
                secret=secret,
            )
        return safe_cameras([row])[0]
    if action in {"plan", "export"}:
        config, mappings = plan(scoped_cameras(store), payload.get("days", 3))
        if not mappings:
            raise ValidationError("Registra al menos una cámara real antes de exportar.")
        if action == "plan":
            return {"cameras": mappings, "retention_days": payload.get("days", 3)}
        return export_config("/deployment", config, mappings, scope)
    if action == "bind":
        import httpx
        from vigilay.db import system_session
        from vigilay.models import Camera

        directory = Path("/deployment/frigate/config")
        marker = json.loads((directory / ".vigilay-managed.json").read_text())
        if marker["scope"] != scope or marker["sha256"] != digest(
            (directory / "config.yml").read_bytes()
        ):
            raise ValidationError("La exportación cambió; revisa el plan antes de vincular.")
        response = httpx.get("http://frigate:5000/api/config", timeout=15, trust_env=False)
        response.raise_for_status()
        aliases = response.json()["cameras"]
        with system_session() as db:
            store.get_local_scope(db)
            for mapping in marker["mappings"]:
                row = db.get(Camera, mapping["id"])
                if (
                    not row
                    or row.tenant_id != scope["tenant_id"]
                    or row.site_id != scope["site_id"]
                ):
                    raise ValidationError("Una cámara ya no pertenece a esta sede; no se vinculó.")
                if mapping["alias"] not in aliases:
                    raise ValidationError("Frigate aún no confirmó todas las cámaras exportadas.")
                store._validate_frigate_assignment(
                    db, row.site_id, mapping["alias"], camera_id=row.id
                )
                row.frigate_camera_name = mapping["alias"]
            db.commit()
        return {"linked": len(marker["mappings"])}
    if action == "password":
        import httpx

        password = str(payload.get("password", ""))
        if not 12 <= len(password) <= 128:
            raise ValidationError("La contraseña Frigate debe tener entre 12 y 128 caracteres.")
        # Accessible only inside this Desktop-owned Docker network, never a public API.
        response = httpx.put(
            "http://frigate:5000/api/users/admin/password",
            json={"password": password},
            timeout=15,
            trust_env=False,
        )
        response.raise_for_status()
        return {"username": "admin", "changed": True}
    raise ValidationError("Operación no permitida.")


def main():
    try:
        raw = sys.stdin.read(65537)
        if len(raw) > 65536:
            raise ValidationError("Solicitud demasiado grande.")
        result = execute(json.loads(raw))
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
    except ValidationError as exc:
        # Only our own validation messages are safe; JSON/library exceptions may contain input.
        safe = str(exc)
        print(json.dumps({"ok": False, "error": safe}, ensure_ascii=False))
        return 1
    except Exception:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "No se completó la operación. Revisa MySQL, la clave de cifrado y el estado de Frigate.",
                }
            )
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
