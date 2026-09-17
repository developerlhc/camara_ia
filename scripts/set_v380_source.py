"""Change one V380 connection mode while preserving its encrypted credentials."""

import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env", override=False)

from camera_store import get_runtime_camera, update_camera  # noqa: E402

if len(sys.argv) != 3:
    raise SystemExit("Uso: python scripts/set_v380_source.py CAMERA_ID lan|cloud")
camera_id, source = sys.argv[1:3]
if source not in {"lan", "cloud"}:
    raise SystemExit("source debe ser lan o cloud")
camera = get_runtime_camera(camera_id)
if camera.get("integration_type") != "V380":
    raise SystemExit("La cámara seleccionada no es V380; no se modificó su configuración")
secret_keys = (
    "host",
    "port",
    "source",
    "device_id",
    "username",
    "password",
    "quality",
    "rtsp_port",
    "http_port",
)
secret = {key: camera[key] for key in secret_keys if key in camera}
secret["source"] = source
update_camera(
    camera_id,
    name=camera["name"],
    model=camera.get("model", ""),
    secret=secret,
    frigate_camera_name=camera.get("frigate_camera_name"),
    target_fps=camera.get("target_fps", 10),
    grayscale=camera.get("grayscale", False),
)
print(f"V380 {camera_id}: source={source}")
