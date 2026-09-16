"""Read-only smoke checks against the isolated CAMERA_STORAGE=env test container."""

import json
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5002"
for attempt in range(30):
    try:
        with urlopen(base + "/healthz", timeout=2) as response:
            health = json.load(response)
        assert health["status"] == "ok" and health["version"] == "0.2.0", health
        break
    except (URLError, TimeoutError, ConnectionError):
        if attempt == 29:
            raise
        time.sleep(0.5)

with urlopen(base + "/", timeout=5) as response:
    assert response.status == 200
    assert "Vigilay" in response.read().decode("utf-8")

for request in [
    Request(base + "/healthz", headers={"Host": "untrusted.example"}),
    Request(base + "/healthz", method="POST", headers={"Origin": "https://untrusted.example"}),
]:
    try:
        urlopen(request, timeout=5)
        raise AssertionError("Local accepted an untrusted Host/Origin")
    except HTTPError as exc:
        assert exc.code == 403, exc.code
        exc.close()

print("Vigilay Local 0.2.0: health, UI and Host/Origin checks passed.")
