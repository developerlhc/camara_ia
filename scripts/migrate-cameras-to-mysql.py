"""Importa las cámaras heredadas de .env y retira sus secretos del archivo."""

import sys
from pathlib import Path

from dotenv import dotenv_values, unset_key

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from camera_store import migrate_environment_cameras  # noqa: E402

CAMERA_KEYS = {
    "RTSP_URL",
    "CAMERA_NAME",
    "CAMERA_BRAND",
    "CAMERA_MODEL",
    "CAMERA_ONVIF_PORT",
    "V380_ENABLED",
    "V380_CAMERA_NAME",
    "V380_MODEL",
    "V380_DEVICE_ID",
    "V380_USERNAME",
    "V380_PASSWORD",
    "V380_IP",
    "V380_PORT",
    "V380_QUALITY",
    "V380_RTSP_PORT",
    "V380_HTTP_PORT",
}
for index in range(2, 9):
    CAMERA_KEYS.update(
        {
            f"CAMERA_{index}_RTSP_URL",
            f"CAMERA_{index}_NAME",
            f"CAMERA_{index}_BRAND",
            f"CAMERA_{index}_MODEL",
            f"CAMERA_{index}_ONVIF_PORT",
        }
    )


def main():
    env_path = BASE_DIR / ".env"
    values = {key: value or "" for key, value in dotenv_values(env_path).items()}
    imported = migrate_environment_cameras(values)
    for key in CAMERA_KEYS:
        if key in values:
            unset_key(str(env_path), key)
    print(f"Cámaras importadas en MySQL: {imported}. Secretos retirados de .env.")


if __name__ == "__main__":
    main()
