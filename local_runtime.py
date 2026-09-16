"""Container-safe LAN and preview configuration; never persists camera secrets."""

import ipaddress
import os
from urllib.parse import quote


def preview_source(camera):
    result = dict(camera)
    alias = camera.get("frigate_camera_name")
    restream = os.getenv("FRIGATE_RESTREAM_URL", "").rstrip("/")
    if alias and restream and os.getenv("VIGILAY_LOCAL_PREFER_RESTREAM", "false") == "true":
        result["rtsp_url"] = f"{restream}/{quote(alias, safe='')}"
    return result


def external_v380(camera):
    """Use Frigate or the existing host bridge, not a Windows .exe in Linux."""
    host = os.getenv("V380_EXTERNAL_BRIDGE_HOST", "host.docker.internal")
    result = {
        **camera,
        "source_host": camera.get("source_host") or camera["host"],
        "host": host,
        "rtsp_url": f"rtsp://{host}:{int(camera.get('rtsp_port', 8555))}/live",
        "onvif_port": int(camera.get("http_port", 8081)),
        "username": "",
        "password": "",
    }
    return preview_source(result)


def discovery_network(local_ip):
    explicit = os.getenv("VIGILAY_LOCAL_LAN_CIDR", "").strip()
    if os.getenv("VIGILAY_LOCAL_CONTAINER") == "true" and not explicit:
        raise OSError(
            "Configura VIGILAY_LOCAL_LAN_CIDR con la subred de las cámaras; la red Docker no es la LAN."
        )
    try:
        network = ipaddress.ip_network(explicit or f"{local_ip}/24", strict=False)
    except ValueError as exc:
        raise OSError("La subred LAN no es válida.") from exc
    if (
        network.version != 4
        or network.prefixlen < 24
        or not network.is_private
        or network.is_loopback
    ):
        raise OSError("Usa una subred IPv4 privada /24 o menor (máximo 256 direcciones).")
    return network
