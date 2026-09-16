"""Single-process WSGI entrypoint for the local administration/preview application."""

import os
import runpy
import signal
from pathlib import Path

from waitress import create_server


def main():
    # One process owns the preview threads. Never use multiple WSGI workers here.
    if os.getenv("LOCAL_AI_ENABLED", "false").lower() in {"1", "true", "yes", "on"}:
        raise RuntimeError("La imagen Local usa Frigate para IA; LOCAL_AI_ENABLED debe ser false.")
    if os.getenv("START_STREAM_AGENT_WITH_LOCAL", "false").lower() in {"1", "true", "yes", "on"}:
        raise RuntimeError("Usa el agente dedicado; no ejecutes un segundo publicador en Local.")
    application = runpy.run_path(str(Path(__file__).with_name("camara-ia.py")))
    analytics = application["analytics"]
    server = create_server(application["app"], host="0.0.0.0", port=5000, threads=16)

    def stop(*_):
        analytics.stop_event.set()
        server.close()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    analytics.start()
    try:
        server.run()
    finally:
        analytics.stop_event.set()
        server.close()


if __name__ == "__main__":
    main()
