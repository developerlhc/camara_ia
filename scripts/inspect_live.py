"""Read-only media diagnostics; deliberately excludes credentials and stream URLs."""

import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "apps/api/src")]
load_dotenv(ROOT / ".env", override=False)

from sqlalchemy import select  # noqa: E402
from vigilay.db import system_session  # noqa: E402
from vigilay.models import CameraStreamSession, ServiceHeartbeat  # noqa: E402

from camera_store import list_runtime_cameras  # noqa: E402


def frigate(path):
    result = subprocess.run(
        ["docker", "exec", "frigate", "curl", "-fsS", "--max-time", "10", path],
        capture_output=True,
        timeout=15,
        check=True,
    )
    return json.loads(result.stdout)


def main():
    cameras = list_runtime_cameras()
    print(
        json.dumps(
            {
                "cameras": [
                    {
                        "id": c["id"],
                        "name": c["name"],
                        "alias": c.get("frigate_camera_name"),
                        "source_host": urlsplit(c.get("rtsp_url", "")).hostname or c.get("host"),
                        "source_mode": c.get("source"),
                        "bridge_rtsp_port": c.get("rtsp_port"),
                    }
                    for c in cameras
                ]
            },
            indent=2,
        )
    )
    with system_session() as db:
        print(
            json.dumps(
                {
                    "heartbeat": [
                        {"name": r.service_name, "seen": str(r.last_seen_at)}
                        for r in db.scalars(select(ServiceHeartbeat))
                    ],
                    "recent_sessions": [
                        {
                            "camera": r.camera_id,
                            "status": r.status,
                            "reason": r.stop_reason,
                            "started": str(r.started_at),
                            "heartbeat": str(r.last_heartbeat_at),
                        }
                        for r in db.scalars(
                            select(CameraStreamSession)
                            .order_by(CameraStreamSession.started_at.desc())
                            .limit(6)
                        )
                    ],
                },
                indent=2,
            )
        )
    stats = frigate("http://127.0.0.1:5000/api/stats")
    config = frigate("http://127.0.0.1:5000/api/config")
    print(
        json.dumps(
            {
                "detect": {
                    name: {
                        key: camera.get("detect", {}).get(key) for key in ("width", "height", "fps")
                    }
                    for name, camera in config.get("cameras", {}).items()
                }
            },
            indent=2,
        )
    )
    print(
        json.dumps({"frigate": stats.get("cameras"), "detectors": stats.get("detectors")}, indent=2)
    )
    streams = frigate("http://127.0.0.1:1984/api/streams")
    print(
        json.dumps(
            {
                "go2rtc": {
                    name: {
                        "producers": [
                            {
                                "host": urlsplit(p.get("url", "").removeprefix("ffmpeg:")).hostname,
                                "bytes_recv": p.get("bytes_recv"),
                                "medias": p.get("medias"),
                            }
                            for p in (v.get("producers") or [])
                        ],
                        "consumers": len(v.get("consumers") or []),
                    }
                    for name, v in streams.items()
                }
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
