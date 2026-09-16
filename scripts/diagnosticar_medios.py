"""Read-only local Frigate check. Never prints config, RTSP URLs or credentials.

Run from the host: python scripts/diagnosticar_medios.py [--container frigate]
No camera, database or Frigate configuration is changed.
"""

import argparse
import json
import re
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", default="frigate")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.container):
        parser.error("Nombre de contenedor inválido")

    def get(path):
        started = time.monotonic()
        result = subprocess.run(
            [
                "docker",
                "exec",
                args.container,
                "curl",
                "--max-time",
                "15",
                "--fail",
                "--silent",
                "http://127.0.0.1:5000/api" + path,
            ],
            capture_output=True,
            timeout=25,
            check=True,
        )
        return json.loads(result.stdout), round((time.monotonic() - started) * 1000)

    try:
        stats, elapsed = get("/stats")
        config, _ = get("/config")
        now = int(time.time())
        output = {"stats_elapsed_ms_including_docker_exec": elapsed, "cameras": []}
        for name, values in stats.get("cameras", {}).items():
            if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
                continue
            segments, duration = get(f"/{name}/recordings?after={now - 3600}&before={now}")
            camera_config = config.get("cameras", {}).get(name, {})
            report = {
                "camera": name,
                "camera_fps": values.get("camera_fps"),
                "process_fps": values.get("process_fps"),
                "skipped_fps": values.get("skipped_fps"),
                "recording_segments_last_hour": len(segments)
                if isinstance(segments, list)
                else None,
                "recordings_elapsed_ms_including_docker_exec": duration,
                "record_enabled": camera_config.get("record", {}).get("enabled"),
                "retention": {
                    key: camera_config.get("record", {}).get(key)
                    for key in ("retain", "continuous", "motion", "alerts", "detections")
                },
                "input_roles": [
                    row.get("roles", [])
                    for row in camera_config.get("ffmpeg", {}).get("inputs", [])
                ],
            }
            if isinstance(segments, list) and segments:
                segment = max(segments, key=lambda row: row.get("end_time", 0))
                start = int(segment["start_time"])
                end = min(start + 10, int(segment["end_time"]))
                if end > start:
                    clip = subprocess.run(
                        [
                            "docker",
                            "exec",
                            args.container,
                            "curl",
                            "--max-time",
                            "20",
                            "--silent",
                            "--range",
                            "0-1023",
                            "--dump-header",
                            "-",
                            "--output",
                            "/dev/null",
                            f"http://127.0.0.1:5000/api/{name}/start/{start}/end/{end}/clip.mp4",
                        ],
                        capture_output=True,
                        timeout=25,
                    )
                    report["clip_curl_exit"] = clip.returncode
                    report["clip_headers"] = [
                        line
                        for line in clip.stdout.decode(errors="replace").splitlines()
                        if line.lower().startswith(
                            ("http/", "content-type:", "content-range:", "content-length:")
                        )
                    ]
            output["cameras"].append(report)
        print(json.dumps(output, indent=2, ensure_ascii=False))
    except (subprocess.SubprocessError, ValueError, OSError):
        print(
            "No se pudo consultar Frigate. Revisa el contenedor; no se muestran respuestas privadas."
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
