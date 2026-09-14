import concurrent.futures
import csv
import ipaddress
import json
import os
import socket
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib import request
from urllib.error import URLError
from urllib.parse import quote, unquote, urlsplit, urlunsplit

import cv2
import psutil
from dotenv import load_dotenv, set_key
from flask import Flask, Response, jsonify, render_template, send_from_directory
from flask import request as flask_request
from ultralytics import YOLO

try:
    from onvif import ONVIFCamera
except ImportError:
    ONVIFCamera = None

try:
    import face_recognition
except ImportError:
    face_recognition = None


BASE_DIR = Path(__file__).resolve().parent
# Las variables ya definidas en PowerShell conservan prioridad sobre .env.
load_dotenv(BASE_DIR / ".env", override=False)
LEGACY_CONFIG_PATH = BASE_DIR / ".local" / "legacy-config.json"
LEGACY_CONFIG = json.loads(LEGACY_CONFIG_PATH.read_text(encoding="utf-8")) if LEGACY_CONFIG_PATH.exists() else {}
MODEL_PATH = BASE_DIR / "yolo11n.pt"
KNOWN_FACES_DIR = BASE_DIR / "rostros_conocidos"
REPORTS_DIR = BASE_DIR / "reportes"
VISITS_DIR = BASE_DIR / "visitas"
REPORT_CSV = REPORTS_DIR / "conteo_personas.csv"
VISITS_CSV = REPORTS_DIR / "visitas.csv"

RTSP_URL = os.getenv("RTSP_URL", LEGACY_CONFIG.get("RTSP_URL", ""))
CONFIDENCE = float(os.getenv("YOLO_CONFIDENCE", "0.45"))
FRAME_WIDTH = int(os.getenv("FRAME_WIDTH", "960"))
PROCESS_WIDTH = int(os.getenv("PROCESS_WIDTH", "512"))
FACE_DETECT_WIDTH = int(os.getenv("FACE_DETECT_WIDTH", "1280"))
YOLO_IMAGE_SIZE = int(os.getenv("YOLO_IMAGE_SIZE", "416"))
LOCAL_AI_ENABLED = os.getenv("LOCAL_AI_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
CAMERA_WIDTH = int(os.getenv("CAMERA_WIDTH", "1920"))
CAMERA_HEIGHT = int(os.getenv("CAMERA_HEIGHT", "1080"))
TARGET_FPS = float(os.getenv("TARGET_FPS", "10"))
DROP_BUFFER_FRAMES = int(os.getenv("DROP_BUFFER_FRAMES", "14"))
ANALYZE_EVERY_FRAMES = max(1, int(os.getenv("ANALYZE_EVERY_FRAMES", "3")))
FACE_SCAN_EVERY = int(os.getenv("FACE_SCAN_EVERY", "5"))
REPORT_EVERY_SECONDS = int(os.getenv("REPORT_EVERY_SECONDS", "5"))
VISIT_SAVE_SECONDS = int(os.getenv("VISIT_SAVE_SECONDS", "30"))
FACE_PADDING = int(os.getenv("FACE_PADDING", "28"))
PERSON_PADDING = int(os.getenv("PERSON_PADDING", "18"))
JPEG_QUALITY = int(os.getenv("JPEG_QUALITY", "85"))
FACE_CONTEXT_SCALE = float(os.getenv("FACE_CONTEXT_SCALE", "3.2"))
FACE_MIN_CROP_WIDTH = int(os.getenv("FACE_MIN_CROP_WIDTH", "520"))
UPSCALE_FACE_CROP = os.getenv("UPSCALE_FACE_CROP", "0") == "1"
FACE_SAVE_WIDTH = int(os.getenv("FACE_SAVE_WIDTH", "0"))
NOTIFY_URL = os.getenv("NOTIFY_URL", "https://cenfelec.com/notificarmsg")
NOTIFY_PHONE = os.getenv("NOTIFY_PHONE", LEGACY_CONFIG.get("NOTIFY_PHONE", ""))
NOTIFY_MESSAGE = os.getenv("NOTIFY_MESSAGE", "alguien llego a la tienda.")
EMPTY_RESET_SECONDS = float(os.getenv("EMPTY_RESET_SECONDS", "3"))

os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS",
    "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|max_delay;500000",
)


def load_notification_config():
    fallback = {
        "enabled": bool(NOTIFY_PHONE),
        "url": NOTIFY_URL,
        "phone": NOTIFY_PHONE,
        "message": NOTIFY_MESSAGE,
    }
    if os.getenv("CAMERA_STORAGE", "env").lower() != "mysql":
        return fallback
    try:
        from camera_store import get_notification_config

        stored = get_notification_config()
        return stored or fallback
    except Exception:
        return fallback


def load_frigate_camera_names():
    """Consulta aliases por el canal privado local; el navegador nunca recibe la clave."""
    api_url = os.getenv("VIGILAY_API_URL", "http://127.0.0.1:8000").rstrip("/")
    local_key = os.getenv("INTERNAL_PROXY_SECRET", "")
    if not local_key:
        raise RuntimeError("Configura INTERNAL_PROXY_SECRET para consultar Frigate.")
    command = request.Request(
        f"{api_url}/api/v1/frigate/internal/cameras",
        headers={"x-vigilay-local-key": local_key},
    )
    try:
        with request.urlopen(command, timeout=10) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError) as error:
        raise RuntimeError("Vigilay API no pudo consultar las cámaras de Frigate.") from error
    return sorted(
        str(item.get("name", ""))
        for item in result
        if isinstance(item, dict) and item.get("name")
    )


def validate_frigate_camera_name(value):
    name = str(value or "").strip()
    if name and name not in load_frigate_camera_names():
        raise ValueError("La cámara seleccionada no existe en Frigate.")
    return name or None


def _camera_config(camera_id, name, rtsp_url, brand="Cámara IP", onvif_port=80):
    parsed = urlsplit(rtsp_url)
    return {
        "id": camera_id,
        "name": name,
        "brand": brand,
        "model": "",
        "integration_type": "RTSP",
        "host": parsed.hostname or "",
        "rtsp_url": rtsp_url,
        "username": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "onvif_port": onvif_port,
    }


def load_cameras():
    if os.getenv("CAMERA_STORAGE", "env").lower() == "mysql":
        try:
            from camera_store import list_runtime_cameras

            stored = list_runtime_cameras()
            cameras = []
            for index, camera in enumerate(stored, start=1):
                if camera["integration_type"] == "V380":
                    camera = _start_v380_bridge(camera, index)
                cameras.append(camera)
            return cameras
        except Exception as error:
            raise RuntimeError(
                "No se pudieron cargar las cámaras cifradas desde MySQL."
            ) from error

    cameras = []
    if RTSP_URL:
        cameras.append(
            _camera_config(
                "camera-1",
                os.getenv("CAMERA_NAME", "EZVIZ principal"),
                RTSP_URL,
                os.getenv("CAMERA_BRAND", "EZVIZ"),
                int(os.getenv("CAMERA_ONVIF_PORT", "80")),
            )
        )

    for index in range(2, 9):
        rtsp_url = os.getenv(f"CAMERA_{index}_RTSP_URL", "").strip()
        if not rtsp_url:
            continue
        cameras.append(
            _camera_config(
                f"camera-{index}",
                os.getenv(f"CAMERA_{index}_NAME", f"Cámara {index}"),
                rtsp_url,
                os.getenv(f"CAMERA_{index}_BRAND", "Cámara IP"),
                int(os.getenv(f"CAMERA_{index}_ONVIF_PORT", "80")),
            )
        )

    # Compatibilidad temporal hasta que scripts/migrate-cameras-to-mysql.py
    # confirme la importación y retire estos valores de .env.
    configured_ids = {camera["id"] for camera in cameras}
    if (
        os.getenv("V380_ENABLED", "0") == "1"
        and "camera-3" not in configured_ids
    ):
        cameras.append(
            _start_v380_bridge(
                {
                    "id": "camera-3",
                    "name": os.getenv("V380_CAMERA_NAME", "V380 Pro"),
                    "brand": "V380",
                    "model": os.getenv("V380_MODEL", "HsAKTQWQ"),
                    "integration_type": "V380",
                    "device_id": os.getenv("V380_DEVICE_ID", ""),
                    "username": os.getenv("V380_USERNAME", ""),
                    "password": os.getenv("V380_PASSWORD", ""),
                    "host": os.getenv("V380_IP", ""),
                    "port": int(os.getenv("V380_PORT", "8800")),
                    "quality": os.getenv("V380_QUALITY", "sd"),
                    "rtsp_port": int(os.getenv("V380_RTSP_PORT", "8555")),
                    "http_port": int(os.getenv("V380_HTTP_PORT", "8081")),
                },
                3,
            )
        )
    return cameras


def _stop_v380_bridge(bridge_dir, http_port, rtsp_port):
    target = (bridge_dir / "V380Decoder.exe").resolve()
    process_ids = set()
    for connection in psutil.net_connections(kind="tcp"):
        if (
            connection.pid
            and connection.status == psutil.CONN_LISTEN
            and connection.laddr
            and connection.laddr.port in {http_port, rtsp_port}
        ):
            process_ids.add(connection.pid)
    for process_id in process_ids:
        try:
            process = psutil.Process(process_id)
            if Path(process.exe()).resolve() != target:
                continue
            process.terminate()
            try:
                process.wait(timeout=3)
            except psutil.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        except (psutil.Error, OSError):
            continue


def _start_v380_bridge(camera, index, force_restart=False):
    bridge_dir = BASE_DIR / ".local" / "v380-bridge"
    executable = bridge_dir / "V380Decoder.exe"
    if not executable.exists():
        raise RuntimeError("No se encontró el puente local V380.")
    rtsp_port = int(camera.get("rtsp_port", 8554 + index))
    http_port = int(camera.get("http_port", 8080 + index))
    source_host = camera["host"]
    if force_restart:
        _stop_v380_bridge(bridge_dir, http_port, rtsp_port)
        for _ in range(20):
            if not _port_is_open("127.0.0.1", http_port):
                break
            time.sleep(0.1)
    if not _port_is_open("127.0.0.1", http_port):
        child_environment = os.environ.copy()
        child_environment["V380_CAMERA_PASSWORD"] = camera["password"]
        arguments = [
            str(executable),
            "--id", str(camera["device_id"]),
            "--username", camera["username"],
            "--ip", camera["host"],
            "--port", str(camera.get("port", 8800)),
            "--source", "lan",
            "--quality", camera.get("quality", "sd"),
            "--enable-api",
            "--http-port", str(http_port),
            "--rtsp-port", str(rtsp_port),
        ]
        log_name = "v380-" + camera["id"]
        with (bridge_dir / f"{log_name}.out.log").open("ab") as stdout, (
            bridge_dir / f"{log_name}.err.log"
        ).open("ab") as stderr:
            subprocess.Popen(
                arguments,
                cwd=bridge_dir,
                env=child_environment,
                stdout=stdout,
                stderr=stderr,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        child_environment["V380_CAMERA_PASSWORD"] = ""
        for _ in range(40):
            if _port_is_open("127.0.0.1", http_port):
                break
            time.sleep(0.5)
        else:
            raise ConnectionError(f"El puente de {camera['name']} no pudo iniciar.")
    camera.update(
        {
            "host": "127.0.0.1",
            "source_host": source_host,
            "rtsp_url": f"rtsp://127.0.0.1:{rtsp_port}/live",
            "username": "",
            "password": "",
            "onvif_port": http_port,
        }
    )
    return camera


def _port_is_open(host, port, timeout=0.3):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _rtsp_url_with_credentials(uri, fallback_host, username, password):
    """Normaliza una URI RTSP obtenida por ONVIF sin registrar secretos."""
    parsed = urlsplit(uri)
    if parsed.scheme not in {"rtsp", "rtsps"}:
        raise ConnectionError("ONVIF no devolvió una dirección RTSP válida.")
    host = parsed.hostname or fallback_host
    port = parsed.port or 554
    authentication = ""
    if username or password:
        authentication = f"{quote(username, safe='')}:{quote(password, safe='')}@"
    return urlunsplit(
        (parsed.scheme, f"{authentication}{host}:{port}", parsed.path, parsed.query, "")
    )


def discover_onvif_rtsp(host, port, username, password):
    """Obtiene del dispositivo su stream principal en vez de adivinar una ruta."""
    if ONVIFCamera is None:
        raise RuntimeError("Instala onvif-zeep para detectar perfiles ONVIF.")
    try:
        client = ONVIFCamera(host, port, username, password, no_cache=True)
        media = client.create_media_service()
        profiles = media.GetProfiles()
        if not profiles:
            raise ConnectionError("La cámara no publicó perfiles de video por ONVIF.")
        stream = media.GetStreamUri(
            {
                "StreamSetup": {
                    "Stream": "RTP-Unicast",
                    "Transport": {"Protocol": "RTSP"},
                },
                "ProfileToken": profiles[0].token,
            }
        )
        return _rtsp_url_with_credentials(stream.Uri, host, username, password)
    except ConnectionError:
        raise
    except Exception as error:
        raise ConnectionError(
            "La cámara no aceptó ONVIF. Actívalo en Configuración avanzada de V380 Pro."
        ) from error


def discover_network_cameras(configured_cameras):
    """Busca cámaras en la subred local y devuelve solo metadatos sin credenciales."""
    configured_hosts = {
        camera.get("source_host") or camera.get("host")
        for camera in configured_cameras
        if camera.get("source_host") or camera.get("host")
    }
    probe_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Una conexión UDP no envía tráfico, pero permite conocer la interfaz LAN
        # que Windows usaría. Nunca se toma 127.0.0.1 del puente V380.
        probe_socket.connect(("8.8.8.8", 80))
        local_ip = probe_socket.getsockname()[0]
    except OSError:
        candidates = []
        try:
            candidates = socket.gethostbyname_ex(socket.gethostname())[2]
        except OSError:
            pass
        candidates.extend(configured_hosts)
        local_ip = next(
            (
                host
                for host in candidates
                if not ipaddress.ip_address(host).is_loopback
                and ipaddress.ip_address(host).is_private
            ),
            "",
        )
    finally:
        probe_socket.close()

    try:
        local_address = ipaddress.ip_address(local_ip)
    except ValueError as error:
        raise OSError("No se pudo determinar la interfaz de red local.") from error
    if local_address.is_loopback or not local_address.is_private:
        raise OSError("No se encontró una interfaz LAN privada para buscar cámaras.")

    network = ipaddress.ip_network(f"{local_ip}/24", strict=False)
    hosts = [str(ip) for ip in network.hosts() if str(ip) != local_ip]
    camera_ports = (554, 8000, 37777, 8800, 8899, 9000)
    open_ports = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=96) as executor:
        futures = {
            executor.submit(_port_is_open, host, port): (host, port)
            for host in hosts
            for port in camera_ports
        }
        for future in concurrent.futures.as_completed(futures):
            if future.result():
                host, port = futures[future]
                open_ports.setdefault(host, []).append(port)

    cameras = []
    for host in sorted(open_ports, key=ipaddress.ip_address):
        ports = sorted(open_ports[host])
        if 37777 in ports:
            brand = "Imou / Dahua"
        elif 8000 in ports:
            brand = "EZVIZ / Hikvision"
        elif 8899 in ports:
            brand = "V380"
        elif 9000 in ports:
            brand = "Posible V380 / cámara IP"
        elif 554 in ports:
            brand = "Cámara RTSP"
        else:
            continue
        cameras.append(
            {
                "id": f"discovered-{host.replace('.', '-')}",
                "name": f"{brand} {host}",
                "brand": brand,
                "host": host,
                "configured": host in configured_hosts,
                "ports": ports,
                "rtsp_available": 554 in ports,
                "onvif_available": 8899 in ports,
                "v380_native_candidate": 8800 in ports or 9000 in ports,
            }
        )
    return cameras


app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True


@app.after_request
def disable_viewer_cache(response):
    if flask_request.path == "/":
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response


class CameraAnalytics:
    def __init__(self):
        self.cameras = {camera["id"]: camera for camera in load_cameras()}
        preferred_camera_id = None
        if os.getenv("CAMERA_STORAGE", "env").lower() == "mysql":
            try:
                from camera_store import get_active_camera_id

                preferred_camera_id = get_active_camera_id()
            except Exception:
                preferred_camera_id = None
        self.active_camera_id = (
            preferred_camera_id
            if preferred_camera_id in self.cameras
            else next(iter(self.cameras), None)
        )
        # Frigate is the production source of detections, recordings and events.
        # The legacy model remains opt-in only for isolated/offline experiments.
        self.model = YOLO(str(MODEL_PATH)) if LOCAL_AI_ENABLED else None
        self.face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        self.known_face_names = []
        self.known_face_encodings = []
        self.latest_frame = None
        self.latest_jpeg = None
        self.latest_frame_version = 0
        self.notification_config = load_notification_config()
        self.status = {
            "ai_engine": "local" if LOCAL_AI_ENABLED else "frigate",
            "person_count": 0,
            "face_count": 0,
            "recognized_people": [],
            "unknown_faces": 0,
            "camera_online": False,
            "face_recognition_enabled": face_recognition is not None,
            "last_update": None,
            "active_camera_id": self.active_camera_id,
            "active_camera_name": self._active_camera()["name"] if self.active_camera_id else None,
            "notification_configured": bool(
                self.notification_config.get("enabled")
                and self.notification_config.get("url")
                and self.notification_config.get("phone")
            ),
            "last_notification_status": (
                "disabled"
                if not self.notification_config.get("enabled")
                else "pending"
                if self.notification_config.get("phone")
                else "not_configured"
            ),
            "last_notification_at": None,
        }
        self.events = []
        self.visit_events = []
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.camera_changed = threading.Event()
        self.frame_index = 0
        self.analysis_index = 0
        self.last_report_at = 0.0
        self.last_person_boxes = []
        self.last_face_labels = []
        self.last_face_save_labels = []
        self.last_snapshot = {
            "person_count": 0,
            "face_count": 0,
            "recognized_people": [],
            "unknown_faces": 0,
        }
        self.fps_started_at = time.monotonic()
        self.fps_frames = 0
        self.last_visit_saved = {}
        self.store_occupied = False
        self.empty_since = time.time()
        self.camera_failures = {}
        self.camera_last_recovery = {}

        REPORTS_DIR.mkdir(exist_ok=True)
        KNOWN_FACES_DIR.mkdir(exist_ok=True)
        VISITS_DIR.mkdir(exist_ok=True)
        self._ensure_report_header()
        self._ensure_visits_header()
        self._load_known_faces()

    def _ensure_report_header(self):
        if REPORT_CSV.exists():
            return
        with REPORT_CSV.open("w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(
                [
                    "fecha_hora",
                    "personas",
                    "rostros",
                    "rostros_desconocidos",
                    "personas_reconocidas",
                ]
            )

    def _ensure_visits_header(self):
        if VISITS_CSV.exists():
            return
        with VISITS_CSV.open("w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(["fecha_hora", "nombre", "archivo", "x1", "y1", "x2", "y2"])

    def _load_known_faces(self):
        if face_recognition is None:
            return

        image_paths = []
        for pattern in ("*.jpg", "*.jpeg", "*.png"):
            image_paths.extend(KNOWN_FACES_DIR.rglob(pattern))

        for image_path in image_paths:
            image = face_recognition.load_image_file(str(image_path))
            encodings = face_recognition.face_encodings(image)
            if not encodings:
                continue

            name = image_path.parent.name if image_path.parent != KNOWN_FACES_DIR else image_path.stem
            self.known_face_names.append(name)
            self.known_face_encodings.append(encodings[0])

    def start(self):
        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()

    def _active_camera(self):
        return self.cameras.get(self.active_camera_id)

    def _run(self):
        while not self.stop_event.is_set():
            camera = self._active_camera()
            if camera is None:
                self._set_camera_status(False)
                time.sleep(1)
                continue

            self.camera_changed.clear()
            capture = cv2.VideoCapture(
                camera["rtsp_url"],
                cv2.CAP_FFMPEG,
                [
                    cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
                    6000,
                    cv2.CAP_PROP_READ_TIMEOUT_MSEC,
                    6000,
                ],
            )
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)

            if not capture.isOpened():
                self._set_camera_status(False)
                self._handle_camera_failure(camera)
                time.sleep(3)
                continue

            self._set_camera_status(True)
            camera_target_fps = float(camera.get("target_fps", TARGET_FPS))
            frame_interval = 1 / camera_target_fps if camera_target_fps > 0 else 0

            while not self.stop_event.is_set() and not self.camera_changed.is_set():
                loop_started_at = time.time()
                ok, frame = self._read_latest_frame(capture)
                if not ok:
                    self._set_camera_status(False)
                    self._handle_camera_failure(camera)
                    break

                self.camera_failures[camera["id"]] = 0

                frame = self._apply_camera_view(frame, camera)
                self.frame_index += 1
                if self.model is not None and (self.frame_index - 1) % ANALYZE_EVERY_FRAMES == 0:
                    processed_frame, snapshot = self._process_frame(frame)
                    self.last_snapshot = snapshot
                else:
                    processed_frame = self._resize_frame(frame, FRAME_WIDTH).copy()
                    snapshot = dict(self.last_snapshot)
                    if self.model is not None:
                        self._draw_person_boxes(processed_frame, self.last_person_boxes)
                        self._draw_face_boxes(processed_frame, self.last_face_labels)
                        self._draw_header(
                            processed_frame,
                            snapshot["person_count"],
                            snapshot["recognized_people"],
                            snapshot["unknown_faces"],
                        )

                if camera.get("grayscale", False):
                    processed_frame = cv2.cvtColor(
                        cv2.cvtColor(processed_frame, cv2.COLOR_BGR2GRAY),
                        cv2.COLOR_GRAY2BGR,
                    )

                jpeg_ok, jpeg_buffer = cv2.imencode(
                    ".jpg", processed_frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
                )
                with self.lock:
                    self.latest_frame = processed_frame
                    if jpeg_ok:
                        self.latest_jpeg = jpeg_buffer.tobytes()
                        self.latest_frame_version += 1
                    self.status.update(snapshot)
                    self.status["camera_online"] = True
                    self.status["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    self.fps_frames += 1
                    fps_elapsed = time.monotonic() - self.fps_started_at
                    if fps_elapsed >= 1:
                        self.status["display_fps"] = round(self.fps_frames / fps_elapsed, 1)
                        self.fps_frames = 0
                        self.fps_started_at = time.monotonic()

                self._write_report_if_needed(snapshot)
                elapsed = time.time() - loop_started_at
                if frame_interval > elapsed:
                    time.sleep(frame_interval - elapsed)

            capture.release()
            if not self.camera_changed.is_set():
                time.sleep(1)

    def _handle_camera_failure(self, camera):
        camera_id = camera["id"]
        self.camera_failures[camera_id] = self.camera_failures.get(camera_id, 0) + 1
        if "v380" not in camera["brand"].lower() or self.camera_failures[camera_id] < 3:
            return
        now = time.monotonic()
        if now - self.camera_last_recovery.get(camera_id, 0) < 60:
            return
        self.camera_last_recovery[camera_id] = now
        self.camera_failures[camera_id] = 0
        try:
            from camera_store import get_runtime_camera

            stored = get_runtime_camera(camera_id)
            restarted = _start_v380_bridge(stored, 3, force_restart=True)
            camera.update(restarted)
        except Exception as error:
            app.logger.warning("No se pudo recuperar el puente V380: %s", error)

    def _read_latest_frame(self, capture):
        for _ in range(max(0, DROP_BUFFER_FRAMES)):
            capture.grab()
        return capture.read()

    def _apply_camera_view(self, frame, camera):
        if "v380" not in camera["brand"].lower():
            return frame
        view = camera.get("view_mode", "full")
        height = frame.shape[0]
        split = height // 3
        if view == "upper":
            return frame[:split, :]
        if view == "lower":
            return frame[split:, :]
        return frame

    def _process_frame(self, frame):
        self.analysis_index += 1
        original_frame = frame
        display_frame = self._resize_frame(frame, FRAME_WIDTH)
        inference_frame = self._resize_frame(frame, PROCESS_WIDTH)

        results = self.model.predict(
            inference_frame,
            conf=CONFIDENCE,
            classes=[0],
            imgsz=YOLO_IMAGE_SIZE,
            verbose=False,
        )
        boxes = results[0].boxes
        person_count = len(boxes) if boxes is not None else 0
        person_boxes = self._person_boxes_for_display(boxes, inference_frame, display_frame)
        self.last_person_boxes = person_boxes

        annotated = display_frame.copy()
        self._draw_person_boxes(annotated, person_boxes)
        face_labels = self.last_face_labels
        face_save_labels = self.last_face_save_labels

        if (self.analysis_index - 1) % max(1, FACE_SCAN_EVERY) == 0:
            face_frame = self._resize_frame(original_frame, FACE_DETECT_WIDTH)
            detected_face_labels = self._recognize_faces(face_frame)
            face_labels = self._scale_face_labels(detected_face_labels, face_frame, display_frame)
            face_save_labels = self._scale_face_labels(detected_face_labels, face_frame, original_frame)
            face_labels, face_save_labels = self._filter_faces_inside_people(
                face_labels, face_save_labels, person_boxes
            )
            self.last_face_labels = face_labels
            self.last_face_save_labels = face_save_labels

        self._draw_face_boxes(annotated, face_labels)

        recognized = sorted({label["name"] for label in face_labels if label["name"] != "Desconocido"})
        unknown_faces = sum(1 for label in face_labels if label["name"] == "Desconocido")
        self._handle_presence_notification(person_count)
        self._save_visit_images(original_frame, face_save_labels)

        self._draw_header(annotated, person_count, recognized, unknown_faces)

        snapshot = {
            "person_count": person_count,
            "face_count": len(face_labels),
            "recognized_people": recognized,
            "unknown_faces": unknown_faces,
        }
        return annotated, snapshot

    def _draw_face_boxes(self, frame, face_labels):
        for label in face_labels:
            x1, y1, x2, y2 = label["box"]
            color = (0, 180, 70) if label["name"] != "Desconocido" else (0, 150, 255)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(
                frame,
                label["name"],
                (x1, max(20, y1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                color,
                2,
                cv2.LINE_AA,
            )

    def _person_boxes_for_display(self, boxes, inference_frame, display_frame):
        if boxes is None:
            return []

        infer_height, infer_width = inference_frame.shape[:2]
        display_height, display_width = display_frame.shape[:2]
        scale_x = display_width / infer_width
        scale_y = display_height / infer_height

        person_boxes = []
        for box in boxes.xyxy.cpu().numpy():
            x1, y1, x2, y2 = box[:4]
            person_boxes.append(
                (
                    int(x1 * scale_x),
                    int(y1 * scale_y),
                    int(x2 * scale_x),
                    int(y2 * scale_y),
                )
            )
        return person_boxes

    def _draw_person_boxes(self, frame, person_boxes):
        for x1, y1, x2, y2 in person_boxes:
            cv2.rectangle(frame, (x1, y1), (x2, y2), (65, 180, 255), 2)
            cv2.putText(
                frame,
                "Persona",
                (x1, max(20, y1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.62,
                (65, 180, 255),
                2,
                cv2.LINE_AA,
            )

    def _filter_faces_inside_people(self, display_labels, original_labels, person_boxes):
        if not person_boxes:
            return [], []

        filtered_display = []
        filtered_original = []
        for display_label, original_label in zip(display_labels, original_labels):
            if self._face_belongs_to_person(display_label["box"], person_boxes):
                filtered_display.append(display_label)
                filtered_original.append(original_label)
        return filtered_display, filtered_original

    def _face_belongs_to_person(self, face_box, person_boxes):
        x1, y1, x2, y2 = face_box
        center_x = (x1 + x2) / 2
        center_y = (y1 + y2) / 2

        for px1, py1, px2, py2 in person_boxes:
            person_width = px2 - px1
            person_height = py2 - py1
            if person_width <= 0 or person_height <= 0:
                continue

            expanded_x1 = px1 - person_width * 0.08
            expanded_x2 = px2 + person_width * 0.08
            expanded_y1 = py1 - person_height * 0.08
            expanded_y2 = py2 + person_height * 0.08

            if expanded_x1 <= center_x <= expanded_x2 and expanded_y1 <= center_y <= expanded_y2:
                return True
        return False

    def _handle_presence_notification(self, person_count):
        now = time.time()

        if person_count > 0:
            self.empty_since = None
            if not self.store_occupied:
                self.store_occupied = True
                self._notify_person_detected()
            return

        if self.store_occupied:
            if self.empty_since is None:
                self.empty_since = now
            if now - self.empty_since >= EMPTY_RESET_SECONDS:
                self.store_occupied = False
        else:
            self.empty_since = now

    def _notify_person_detected(self):
        thread = threading.Thread(target=self._send_notification, daemon=True)
        thread.start()

    def _send_notification(self):
        notify_url = self.notification_config.get("url", "")
        notify_phone = self.notification_config.get("phone", "")
        notify_message = self.notification_config.get("message", "")
        if not self.notification_config.get("enabled"):
            with self.lock:
                self.status["last_notification_status"] = "disabled"
            return
        if not notify_url or not notify_phone:
            with self.lock:
                self.status["last_notification_status"] = "not_configured"
            return
        payload = json.dumps(
            {
                "telefono": notify_phone,
                "mensajeTexto": notify_message,
            }
        ).encode("utf-8")
        http_request = request.Request(
            notify_url,
            data=payload,
            headers={"content-type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(http_request, timeout=5):
                with self.lock:
                    self.status["last_notification_status"] = "sent"
                    self.status["last_notification_at"] = datetime.now().strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
        except (OSError, URLError):
            with self.lock:
                self.status["last_notification_status"] = "error"

    def _save_visit_images(self, original_frame, face_labels):
        if not face_labels:
            return

        now = time.time()
        timestamp = datetime.now()
        rows = []
        new_events = []

        save_items = [
            {"name": label["name"], "box": label["box"], "kind": "rostro"}
            for label in face_labels
        ]

        for index, item in enumerate(save_items):
            label = item
            name = label["name"]
            visitor_key = self._visit_key(label, index)
            if now - self.last_visit_saved.get(visitor_key, 0) < VISIT_SAVE_SECONDS:
                continue

            if item["kind"] == "rostro":
                x1, y1, x2, y2 = self._face_context_box(original_frame, label["box"])
            else:
                x1, y1, x2, y2 = self._clamp_box(original_frame, label["box"], PERSON_PADDING)
            visit_image = original_frame[y1:y2, x1:x2]
            if visit_image.size == 0:
                continue
            visit_image = self._enlarge_small_face(visit_image, item["kind"])

            safe_name = "".join(char for char in name if char.isalnum() or char in ("-", "_"))
            safe_name = safe_name or "Desconocido"
            filename = f"{timestamp.strftime('%Y%m%d_%H%M%S')}_{item['kind']}_{safe_name}_{index}.jpg"
            path = VISITS_DIR / filename
            cv2.imwrite(str(path), visit_image, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])

            date_text = timestamp.strftime("%Y-%m-%d %H:%M:%S")
            rows.append([date_text, name, str(path), x1, y1, x2, y2])
            new_events.append(
                {
                    "time": date_text,
                    "name": name,
                    "file": str(path),
                    "url": f"/visitas/{filename}",
                    "kind": item["kind"],
                }
            )
            self.last_visit_saved[visitor_key] = now

        if not rows:
            return

        with VISITS_CSV.open("a", newline="", encoding="utf-8") as file:
            csv.writer(file).writerows(rows)

        with self.lock:
            self.visit_events = new_events + self.visit_events
            self.visit_events = self.visit_events[:50]

    def _scale_face_labels(self, labels, source_frame, target_frame):
        source_height, source_width = source_frame.shape[:2]
        target_height, target_width = target_frame.shape[:2]
        scale_x = target_width / source_width
        scale_y = target_height / source_height
        scaled = []
        for label in labels:
            x1, y1, x2, y2 = label["box"]
            scaled.append(
                {
                    "name": label["name"],
                    "box": (
                        int(x1 * scale_x),
                        int(y1 * scale_y),
                        int(x2 * scale_x),
                        int(y2 * scale_y),
                    ),
                }
            )
        return scaled

    def _scale_box_to_original(self, box, display_frame, original_frame):
        display_height, display_width = display_frame.shape[:2]
        original_height, original_width = original_frame.shape[:2]
        scale_x = original_width / display_width
        scale_y = original_height / display_height
        x1, y1, x2, y2 = box
        return (
            int(x1 * scale_x),
            int(y1 * scale_y),
            int(x2 * scale_x),
            int(y2 * scale_y),
        )

    def _enlarge_small_face(self, image, kind):
        if (
            kind != "rostro"
            or not UPSCALE_FACE_CROP
            or FACE_SAVE_WIDTH <= 0
            or image.shape[1] >= FACE_SAVE_WIDTH
        ):
            return image

        scale = FACE_SAVE_WIDTH / image.shape[1]
        target_size = (FACE_SAVE_WIDTH, int(image.shape[0] * scale))
        return cv2.resize(image, target_size, interpolation=cv2.INTER_CUBIC)

    def _face_context_box(self, frame, face_box):
        height, width = frame.shape[:2]
        x1, y1, x2, y2 = face_box
        face_width = max(1, x2 - x1)
        face_height = max(1, y2 - y1)
        center_x = (x1 + x2) / 2
        center_y = (y1 + y2) / 2

        crop_width = max(face_width * FACE_CONTEXT_SCALE, FACE_MIN_CROP_WIDTH)
        crop_height = max(face_height * FACE_CONTEXT_SCALE, crop_width * 0.9)

        left = int(center_x - crop_width / 2)
        right = int(center_x + crop_width / 2)
        top = int(center_y - crop_height * 0.42)
        bottom = int(center_y + crop_height * 0.58)

        if left < 0:
            right -= left
            left = 0
        if right > width:
            left -= right - width
            right = width
        if top < 0:
            bottom -= top
            top = 0
        if bottom > height:
            top -= bottom - height
            bottom = height

        return (
            max(0, left),
            max(0, top),
            min(width, right),
            min(height, bottom),
        )

    def _visit_key(self, label, index):
        name = label["name"]
        if name != "Desconocido":
            return name

        x1, y1, x2, y2 = label["box"]
        center_x = int(((x1 + x2) / 2) // 80)
        center_y = int(((y1 + y2) / 2) // 80)
        return f"Desconocido_{center_x}_{center_y}_{index}"

    def _clamp_box(self, frame, box, padding):
        height, width = frame.shape[:2]
        x1, y1, x2, y2 = box
        return (
            max(0, x1 - padding),
            max(0, y1 - padding),
            min(width, x2 + padding),
            min(height, y2 + padding),
        )

    def _resize_frame(self, frame, target_width):
        height, width = frame.shape[:2]
        if width <= target_width:
            return frame
        scale = target_width / width
        return cv2.resize(frame, (target_width, int(height * scale)), interpolation=cv2.INTER_AREA)

    def _recognize_faces(self, frame):
        if face_recognition is not None and self.known_face_encodings:
            return self._recognize_with_face_recognition(frame)
        return self._detect_faces_only(frame)

    def _recognize_with_face_recognition(self, frame):
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        small_frame = cv2.resize(rgb_frame, (0, 0), fx=0.5, fy=0.5)
        locations = face_recognition.face_locations(small_frame, model="hog")
        encodings = face_recognition.face_encodings(small_frame, locations)

        labels = []
        for location, encoding in zip(locations, encodings):
            name = "Desconocido"
            matches = face_recognition.compare_faces(
                self.known_face_encodings, encoding, tolerance=0.5
            )
            distances = face_recognition.face_distance(self.known_face_encodings, encoding)
            if len(distances) > 0:
                best_index = distances.argmin()
                if matches[best_index]:
                    name = self.known_face_names[best_index]

            top, right, bottom, left = location
            labels.append(
                {
                    "name": name,
                    "box": (left * 2, top * 2, right * 2, bottom * 2),
                }
            )
        return labels

    def _detect_faces_only(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)
        faces = self.face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.08,
            minNeighbors=4,
            minSize=(36, 36),
        )
        return [
            {"name": "Desconocido", "box": (x, y, x + w, y + h)}
            for (x, y, w, h) in faces
        ]

    def _draw_header(self, frame, person_count, recognized, unknown_faces):
        cv2.rectangle(frame, (0, 0), (frame.shape[1], 76), (18, 22, 28), -1)
        text = f"Personas en local: {person_count}"
        cv2.putText(frame, text, (18, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (255, 255, 255), 2)

        names = ", ".join(recognized) if recognized else "Sin reconocidos"
        face_text = f"Rostros: {len(recognized) + unknown_faces} | {names}"
        cv2.putText(frame, face_text, (18, 62), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (220, 235, 245), 2)

    def _write_report_if_needed(self, snapshot):
        now = time.time()
        if now - self.last_report_at < REPORT_EVERY_SECONDS:
            return
        self.last_report_at = now

        row = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            snapshot["person_count"],
            snapshot["face_count"],
            snapshot["unknown_faces"],
            ", ".join(snapshot["recognized_people"]),
        ]

        with REPORT_CSV.open("a", newline="", encoding="utf-8") as file:
            csv.writer(file).writerow(row)

        event = {
            "time": row[0],
            "person_count": row[1],
            "face_count": row[2],
            "unknown_faces": row[3],
            "recognized_people": snapshot["recognized_people"],
        }
        with self.lock:
            self.events.insert(0, event)
            self.events = self.events[:50]

    def _set_camera_status(self, online):
        with self.lock:
            self.status["camera_online"] = online
            self.status["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def get_status(self):
        with self.lock:
            return dict(self.status)

    def get_cameras(self):
        with self.lock:
            active_camera_id = self.active_camera_id
            active_online = self.status["camera_online"]
        return [
            {
                "id": camera["id"],
                "name": camera["name"],
                "brand": camera["brand"],
                "model": camera.get("model", ""),
                "target_fps": camera.get("target_fps", 10),
                "grayscale": camera.get("grayscale", False),
                "host": camera["host"],
                "view_mode": camera.get("view_mode", "full"),
                "views": ["full", "upper", "lower"]
                if "v380" in camera["brand"].lower()
                else ["full"],
                "configured": True,
                "active": camera["id"] == active_camera_id,
                "online": active_online if camera["id"] == active_camera_id else None,
            }
            for camera in self.cameras.values()
        ]

    def get_camera_configuration(self, camera_id):
        camera = self.cameras.get(camera_id)
        if camera is None:
            raise KeyError(camera_id)
        if os.getenv("CAMERA_STORAGE", "env").lower() == "mysql":
            from camera_store import get_runtime_camera

            stored = get_runtime_camera(camera_id)
        else:
            stored = camera
        result = {
            "id": camera_id,
            "name": stored["name"],
            "brand": stored["brand"],
            "model": stored.get("model", ""),
            "target_fps": stored.get("target_fps", 10),
            "grayscale": stored.get("grayscale", False),
            "host": stored.get("host", ""),
            "username": stored.get("username", ""),
            "connection_mode": stored["integration_type"].lower(),
            "frigate_camera_name": stored.get("frigate_camera_name", ""),
        }
        if stored["integration_type"] == "V380":
            result["device_id"] = stored.get("device_id", "")
        else:
            parsed = urlsplit(stored["rtsp_url"])
            result["path"] = urlunsplit(("", "", parsed.path, parsed.query, ""))
        return result

    def update_camera_configuration(self, camera_id, payload):
        if os.getenv("CAMERA_STORAGE", "env").lower() != "mysql":
            raise RuntimeError("La edición requiere el almacenamiento MySQL activo.")
        camera = self.cameras.get(camera_id)
        if camera is None:
            raise KeyError(camera_id)
        from camera_store import get_runtime_camera, update_camera

        stored = get_runtime_camera(camera_id)
        name = str(payload.get("name", "")).strip()[:160]
        model = str(payload.get("model", "")).strip()[:120]
        try:
            target_fps = int(payload.get("target_fps", stored.get("target_fps", 10)))
        except (TypeError, ValueError) as error:
            raise ValueError("Los FPS deben ser un número entero.") from error
        if not 1 <= target_fps <= 30:
            raise ValueError("Selecciona entre 1 y 30 FPS.")
        grayscale = bool(payload.get("grayscale", False))
        frigate_camera_name = validate_frigate_camera_name(
            payload.get("frigate_camera_name")
        )
        if not name:
            raise ValueError("Escribe un alias para la cámara.")
        password = str(payload.get("password", ""))
        restart_required = False
        if stored["integration_type"] == "V380":
            host = str(payload.get("host", stored.get("host", ""))).strip()
            username = str(payload.get("username", stored.get("username", ""))).strip()
            device_id = str(payload.get("device_id", stored.get("device_id", ""))).strip()
            try:
                if not ipaddress.ip_address(host).is_private:
                    raise ValueError
            except ValueError as error:
                raise ValueError("Introduce una dirección IP privada válida.") from error
            secret = {
                "host": host,
                "port": int(stored.get("port", 8800)),
                "device_id": device_id,
                "username": username,
                "password": password or stored.get("password", ""),
                "quality": stored.get("quality", "sd"),
                "rtsp_port": int(stored.get("rtsp_port", 8555)),
                "http_port": int(stored.get("http_port", 8081)),
            }
            if not all((username, device_id, secret["password"])):
                raise ValueError("Completa ID, usuario y contraseña V380.")
            restart_required = any(
                secret[key] != stored.get(key) for key in ("host", "username", "device_id", "password")
            )
            updated = update_camera(
                camera_id,
                name=name,
                model=model,
                secret=secret,
                frigate_camera_name=frigate_camera_name,
                target_fps=target_fps,
                grayscale=grayscale,
            )
            with self.lock:
                camera["name"] = updated["name"]
                camera["model"] = updated["model"]
                camera["target_fps"] = updated["target_fps"]
                camera["grayscale"] = updated["grayscale"]
        else:
            host = str(payload.get("host", stored.get("host", ""))).strip()
            username = str(payload.get("username", stored.get("username", ""))).strip()
            path = str(payload.get("path", "")).strip()
            try:
                if not ipaddress.ip_address(host).is_private:
                    raise ValueError
            except ValueError as error:
                raise ValueError("Introduce una dirección IP privada válida.") from error
            parsed = urlsplit(stored["rtsp_url"])
            existing_path = urlunsplit(("", "", parsed.path, parsed.query, ""))
            connection_changed = any(
                (
                    host != (parsed.hostname or ""),
                    username != unquote(parsed.username or ""),
                    path != existing_path,
                    bool(password),
                )
            )
            password = password or unquote(parsed.password or "")
            if not username or not password or not path:
                raise ValueError("Completa usuario, contraseña y ruta RTSP.")
            if not path.startswith("/"):
                path = f"/{path}"
            secret = None
            if connection_changed:
                rtsp_url = (
                    f"rtsp://{quote(username, safe='')}:{quote(password, safe='')}"
                    f"@{host}:{parsed.port or 554}{path}"
                )
                capture = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
                try:
                    connected, _ = capture.read() if capture.isOpened() else (False, None)
                finally:
                    capture.release()
                if not connected:
                    raise ConnectionError("No fue posible abrir el video con la nueva configuración.")
                secret = {
                    "rtsp_url": rtsp_url,
                    "onvif_port": int(stored.get("onvif_port", 80)),
                }
            updated = update_camera(
                camera_id,
                name=name,
                model=model,
                secret=secret,
                frigate_camera_name=frigate_camera_name,
                target_fps=target_fps,
                grayscale=grayscale,
            )
            updated["view_mode"] = camera.get("view_mode", "full")
            with self.lock:
                self.cameras[camera_id] = updated
        with self.lock:
            if camera_id == self.active_camera_id:
                self.status["active_camera_name"] = name
        if not restart_required and camera_id == self.active_camera_id:
            self.camera_changed.set()
        return {"id": camera_id, "name": name, "restart_required": restart_required}

    def select_camera(self, camera_id):
        camera = self.cameras.get(camera_id)
        if camera is None:
            raise KeyError(camera_id)
        with self.lock:
            already_active = (
                camera_id == self.active_camera_id and self.status["camera_online"]
            )
        if already_active:
            return camera
        with self.lock:
            self.active_camera_id = camera_id
            camera.setdefault("view_mode", "full")
            self.latest_frame = None
            self.latest_jpeg = None
            self.fps_started_at = time.monotonic()
            self.fps_frames = 0
            self.analysis_index = 0
            self.last_person_boxes = []
            self.last_face_labels = []
            self.last_face_save_labels = []
            self.last_snapshot = {
                "person_count": 0,
                "face_count": 0,
                "recognized_people": [],
                "unknown_faces": 0,
            }
            self.status.update(
                {
                    "active_camera_id": camera_id,
                    "active_camera_name": camera["name"],
                    "camera_online": False,
                    "person_count": 0,
                    "face_count": 0,
                    "recognized_people": [],
                    "unknown_faces": 0,
                    "display_fps": 0,
                }
            )
        self.camera_changed.set()
        if os.getenv("CAMERA_STORAGE", "env").lower() == "mysql":
            from camera_store import save_active_camera_id

            save_active_camera_id(camera_id)
        return camera

    def set_camera_view(self, camera_id, view):
        camera = self.cameras.get(camera_id)
        if camera is None:
            raise KeyError(camera_id)
        allowed = {"full", "upper", "lower"} if "v380" in camera["brand"].lower() else {"full"}
        if view not in allowed:
            raise ValueError("Vista de cámara no válida.")
        camera["view_mode"] = view
        if camera_id == self.active_camera_id:
            self.latest_frame = None
            self.latest_jpeg = None
            self.camera_changed.set()
        return view

    def add_camera(
        self,
        host,
        name,
        brand,
        username,
        password,
        path,
        model="",
        target_fps=10,
        grayscale=False,
        onvif_port=80,
        rtsp_url=None,
        frigate_camera_name=None,
    ):
        if rtsp_url is None:
            path = path.strip()
            if not path.startswith("/"):
                path = f"/{path}"
            # Conserva consultas RTSP comunes y codifica únicamente las credenciales.
            rtsp_url = (
                f"rtsp://{quote(username, safe='')}:{quote(password, safe='')}"
                f"@{host}:554{path}"
            )
        capture = cv2.VideoCapture(
            rtsp_url,
            cv2.CAP_FFMPEG,
            [
                cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
                6000,
                cv2.CAP_PROP_READ_TIMEOUT_MSEC,
                6000,
            ],
        )
        try:
            connected, _ = capture.read() if capture.isOpened() else (False, None)
        finally:
            capture.release()
        if not connected:
            raise ConnectionError("No fue posible abrir el video con esas credenciales y ruta.")

        used_indexes = {
            int(camera_id.split("-")[1])
            for camera_id in self.cameras
            if camera_id.startswith("camera-") and camera_id.split("-")[1].isdigit()
        }
        index = next((value for value in range(2, 9) if value not in used_indexes), None)
        if index is None:
            raise RuntimeError("Se alcanzó el máximo de ocho cámaras configuradas.")
        if os.getenv("CAMERA_STORAGE", "env").lower() == "mysql":
            from camera_store import save_camera

            camera = save_camera(
                name=name,
                brand=brand,
                model=model,
                integration_type="RTSP",
                secret={"rtsp_url": rtsp_url, "onvif_port": onvif_port},
                frigate_camera_name=frigate_camera_name,
                target_fps=target_fps,
                grayscale=grayscale,
            )
        else:
            camera = _camera_config(f"camera-{index}", name, rtsp_url, brand, onvif_port)
        with self.lock:
            self.cameras[camera["id"]] = camera
        if os.getenv("CAMERA_STORAGE", "env").lower() != "mysql":
            env_path = BASE_DIR / ".env"
            set_key(str(env_path), f"CAMERA_{index}_RTSP_URL", rtsp_url, quote_mode="auto")
            set_key(str(env_path), f"CAMERA_{index}_NAME", name, quote_mode="auto")
            set_key(str(env_path), f"CAMERA_{index}_BRAND", brand, quote_mode="auto")
            set_key(
                str(env_path),
                f"CAMERA_{index}_ONVIF_PORT",
                str(onvif_port),
                quote_mode="never",
            )
        return camera

    def add_v380_camera(
        self,
        *,
        host,
        name,
        model,
        device_id,
        username,
        password,
        frigate_camera_name=None,
        target_fps=10,
        grayscale=False,
    ):
        if os.getenv("CAMERA_STORAGE", "env").lower() != "mysql":
            raise RuntimeError("Activa el almacenamiento MySQL antes de agregar otra V380.")
        from camera_store import save_camera

        offset = sum(
            1 for camera in self.cameras.values() if camera["integration_type"] == "V380"
        )
        secret = {
            "host": host,
            "port": 8800,
            "device_id": device_id,
            "username": username,
            "password": password,
            "quality": "sd",
            "rtsp_port": 8555 + offset,
            "http_port": 8081 + offset,
        }
        candidate = {
            "id": f"candidate-{device_id}",
            "name": name,
            "brand": "V380",
            "model": model,
            "integration_type": "V380",
            **secret,
        }
        candidate = _start_v380_bridge(candidate, 3 + offset)
        capture = cv2.VideoCapture(
            candidate["rtsp_url"],
            cv2.CAP_FFMPEG,
            [
                cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
                10000,
                cv2.CAP_PROP_READ_TIMEOUT_MSEC,
                10000,
            ],
        )
        try:
            connected, _ = capture.read() if capture.isOpened() else (False, None)
        finally:
            capture.release()
        if not connected:
            raise ConnectionError("La V380 autenticó, pero no entregó vídeo.")
        stored = save_camera(
            name=name,
            brand="V380",
            model=model,
            integration_type="V380",
            secret=secret,
            frigate_camera_name=frigate_camera_name,
            target_fps=target_fps,
            grayscale=grayscale,
        )
        stored.update(
            {
                "host": "127.0.0.1",
                "rtsp_url": candidate["rtsp_url"],
                "username": "",
                "password": "",
                "onvif_port": candidate["onvif_port"],
            }
        )
        with self.lock:
            self.cameras[stored["id"]] = stored
        return stored

    def move_ptz(self, action, speed=0.55, duration=0.28):
        camera = self._active_camera()
        if camera is None:
            raise RuntimeError("No hay una cámara activa.")

        if "v380" in camera["brand"].lower():
            movements = {
                "left": ("left",),
                "right": ("right",),
                "up": ("up",),
                "down": ("down",),
                "up-left": ("up", "left"),
                "up-right": ("up", "right"),
                "down-left": ("down", "left"),
                "down-right": ("down", "right"),
            }
            if action not in movements:
                raise RuntimeError("La V380 no ofrece zoom mediante el puente local.")
            try:
                for movement in movements[action]:
                    endpoint = (
                        f"http://{camera['host']}:{camera['onvif_port']}/api/ptz/{movement}"
                    )
                    command = request.Request(endpoint, data=b"", method="POST")
                    with request.urlopen(command, timeout=3) as response:
                        if response.status != 200:
                            raise RuntimeError("El puente V380 rechazó el movimiento.")
                return
            except (OSError, URLError) as error:
                raise RuntimeError("El puente local de la V380 no está disponible.") from error

        if ONVIFCamera is None:
            raise RuntimeError("Instala onvif-zeep para controlar PTZ.")

        vectors = {
            "left": (-1, 0, 0),
            "right": (1, 0, 0),
            "up": (0, 1, 0),
            "down": (0, -1, 0),
            "up-left": (-0.7, 0.7, 0),
            "up-right": (0.7, 0.7, 0),
            "down-left": (-0.7, -0.7, 0),
            "down-right": (0.7, -0.7, 0),
            "zoom-in": (0, 0, 1),
            "zoom-out": (0, 0, -1),
        }
        if action not in vectors:
            raise ValueError("Movimiento PTZ no válido.")

        speed = min(1.0, max(0.1, float(speed)))
        duration = min(1.0, max(0.1, float(duration)))
        pan, tilt, zoom = vectors[action]
        client = ONVIFCamera(
            camera["host"],
            camera["onvif_port"],
            camera["username"],
            camera["password"],
            no_cache=True,
        )
        media = client.create_media_service()
        profile = media.GetProfiles()[0]
        ptz = client.create_ptz_service()
        options = ptz.GetConfigurationOptions(
            {"ConfigurationToken": profile.PTZConfiguration.token}
        )
        pan_tilt_spaces = options.Spaces.ContinuousPanTiltVelocitySpace or []
        zoom_spaces = options.Spaces.ContinuousZoomVelocitySpace or []
        is_imou = "imou" in camera["brand"].lower() or "dahua" in camera["brand"].lower()
        pan_tilt_space = (
            pan_tilt_spaces[0].URI
            if pan_tilt_spaces
            else "http://www.onvif.org/ver10/tptz/PanTiltSpaces/VelocityGenericSpace"
            if is_imou
            else None
        )
        movement = ptz.create_type("ContinuousMove")
        movement.ProfileToken = profile.token
        if zoom:
            if not zoom_spaces:
                raise RuntimeError("La cámara no ofrece zoom mediante ONVIF.")
            movement.Velocity = {
                "Zoom": {"x": zoom * speed, "space": zoom_spaces[0].URI}
            }
        else:
            if not pan_tilt_space:
                raise RuntimeError("La cámara no ofrece movimiento mediante ONVIF.")
            movement.Velocity = {
                "PanTilt": {
                    "x": pan * speed,
                    "y": tilt * speed,
                    "space": pan_tilt_space,
                }
            }
        try:
            ptz.ContinuousMove(movement)
            time.sleep(duration)
        finally:
            ptz.Stop(
                {
                    "ProfileToken": profile.token,
                    "PanTilt": not bool(zoom),
                    "Zoom": bool(zoom),
                }
            )

    def ptz_capabilities(self):
        camera = self._active_camera()
        if camera is None:
            return {"pan_tilt": False, "zoom": False}
        if "v380" in camera["brand"].lower():
            try:
                endpoint = f"http://{camera['host']}:{camera['onvif_port']}/api/status"
                with request.urlopen(endpoint, timeout=2) as response:
                    return {"pan_tilt": response.status == 200, "zoom": False}
            except (OSError, URLError):
                return {"pan_tilt": False, "zoom": False}
        if ONVIFCamera is None:
            return {"pan_tilt": False, "zoom": False}
        try:
            client = ONVIFCamera(
                camera["host"],
                camera["onvif_port"],
                camera["username"],
                camera["password"],
                no_cache=True,
            )
            media = client.create_media_service()
            profile = media.GetProfiles()[0]
            ptz = client.create_ptz_service()
            options = ptz.GetConfigurationOptions(
                {"ConfigurationToken": profile.PTZConfiguration.token}
            )
            is_imou = "imou" in camera["brand"].lower() or "dahua" in camera["brand"].lower()
            return {
                "pan_tilt": bool(options.Spaces.ContinuousPanTiltVelocitySpace) or is_imou,
                "zoom": bool(options.Spaces.ContinuousZoomVelocitySpace),
            }
        except Exception:
            return {"pan_tilt": False, "zoom": False}

    def get_events(self):
        with self.lock:
            return list(self.events)

    def get_visits(self):
        with self.lock:
            return list(self.visit_events)

    def clear_history(self):
        with self.lock:
            self.events = []
            self.visit_events = []
            self.last_visit_saved = {}
            self.last_report_at = 0.0

        self._rewrite_report_header()
        self._rewrite_visits_header()

        for image_path in VISITS_DIR.glob("*"):
            if image_path.is_file():
                image_path.unlink(missing_ok=True)

    def _rewrite_report_header(self):
        with REPORT_CSV.open("w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(
                [
                    "fecha_hora",
                    "personas",
                    "rostros",
                    "rostros_desconocidos",
                    "personas_reconocidas",
                ]
            )

    def _rewrite_visits_header(self):
        with VISITS_CSV.open("w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(["fecha_hora", "nombre", "archivo", "x1", "y1", "x2", "y2"])

    def get_jpeg(self):
        with self.lock:
            return self.latest_jpeg

    def get_jpeg_packet(self):
        with self.lock:
            return self.latest_jpeg, self.latest_frame_version


class CameraPreviewHub:
    """Mantiene una vista ligera de todas las cámaras sin ejecutar IA adicional."""

    def __init__(self, camera_analytics):
        self.analytics = camera_analytics
        self.lock = threading.Lock()
        self.states = {}

    def ensure_workers(self):
        for camera_id in list(self.analytics.cameras):
            self.ensure_worker(camera_id)

    def ensure_worker(self, camera_id):
        with self.lock:
            state = self.states.setdefault(
                camera_id,
                {"jpeg": None, "version": 0, "online": False, "started": False},
            )
            if state["started"]:
                return
            state["started"] = True
        threading.Thread(target=self._run, args=(camera_id,), daemon=True).start()

    def _set_offline(self, camera_id):
        with self.lock:
            if camera_id in self.states:
                self.states[camera_id]["online"] = False

    def _run(self, camera_id):
        while not self.analytics.stop_event.is_set():
            camera = self.analytics.cameras.get(camera_id)
            if camera is None:
                self._set_offline(camera_id)
                return
            with self.lock:
                paused = self.states[camera_id].get("paused", False)
            if camera_id == self.analytics.active_camera_id or paused:
                time.sleep(0.25)
                continue

            source_url = camera["rtsp_url"]
            with self.lock:
                self.states[camera_id]["capturing"] = True
            capture = cv2.VideoCapture(
                source_url,
                cv2.CAP_FFMPEG,
                [
                    cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
                    5000,
                    cv2.CAP_PROP_READ_TIMEOUT_MSEC,
                    5000,
                ],
            )
            if not capture.isOpened():
                self._set_offline(camera_id)
                with self.lock:
                    self.states[camera_id]["capturing"] = False
                time.sleep(10)
                continue
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            try:
                last_preview_at = 0.0
                while not self.analytics.stop_event.is_set():
                    current = self.analytics.cameras.get(camera_id)
                    with self.lock:
                        paused = self.states[camera_id].get("paused", False)
                    if (
                        current is None
                        or camera_id == self.analytics.active_camera_id
                        or paused
                        or current.get("rtsp_url") != source_url
                    ):
                        break
                    ok, frame = capture.read()
                    if not ok:
                        self._set_offline(camera_id)
                        break
                    now = time.monotonic()
                    preview_fps = min(8, max(1, int(current.get("target_fps", 10))))
                    if now - last_preview_at < 1 / preview_fps:
                        continue
                    last_preview_at = now
                    preview = self.analytics._resize_frame(frame, 360)
                    if current.get("grayscale", False):
                        preview = cv2.cvtColor(
                            cv2.cvtColor(preview, cv2.COLOR_BGR2GRAY),
                            cv2.COLOR_GRAY2BGR,
                        )
                    ok, buffer = cv2.imencode(
                        ".jpg", preview, [cv2.IMWRITE_JPEG_QUALITY, 65]
                    )
                    if not ok:
                        continue
                    with self.lock:
                        state = self.states[camera_id]
                        state["jpeg"] = buffer.tobytes()
                        state["version"] += 1
                        state["online"] = True
            finally:
                capture.release()
                with self.lock:
                    if camera_id in self.states:
                        self.states[camera_id]["capturing"] = False
            time.sleep(0.5)

    def reserve_for_primary(self, camera_id, timeout=7.0):
        self.ensure_worker(camera_id)
        with self.lock:
            self.states[camera_id]["paused"] = True
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.lock:
                capturing = self.states[camera_id].get("capturing", False)
            if not capturing:
                return
            time.sleep(0.05)

    def release_primary_reservation(self, camera_id):
        with self.lock:
            if camera_id in self.states:
                self.states[camera_id]["paused"] = False

    def get_packet(self, camera_id):
        if camera_id not in self.analytics.cameras:
            raise KeyError(camera_id)
        if camera_id == self.analytics.active_camera_id:
            frame, version = self.analytics.get_jpeg_packet()
            if frame is not None:
                # Separa el contador del visor principal del contador de miniatura.
                return frame, version + 1_000_000_000
        self.ensure_worker(camera_id)
        with self.lock:
            state = self.states[camera_id]
            return state["jpeg"], state["version"]

    def camera_online(self, camera_id):
        if camera_id == self.analytics.active_camera_id:
            return bool(self.analytics.get_status().get("camera_online"))
        with self.lock:
            return bool(self.states.get(camera_id, {}).get("online"))


analytics = CameraAnalytics()
preview_hub = CameraPreviewHub(analytics)
discovered_cameras = []


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/video_feed")
def video_feed():
    def generate():
        last_version = -1
        while True:
            frame, version = analytics.get_jpeg_packet()
            if frame is None or version == last_version:
                time.sleep(0.01)
                continue
            last_version = version
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"

    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/camera_feed/<camera_id>")
def camera_feed(camera_id):
    if camera_id not in analytics.cameras:
        return jsonify({"error": "La cámara no está configurada."}), 404
    preview_hub.ensure_worker(camera_id)

    def generate():
        last_version = -1
        while True:
            try:
                frame, version = preview_hub.get_packet(camera_id)
            except KeyError:
                return
            if frame is None or version == last_version:
                time.sleep(0.03)
                continue
            last_version = version
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"

    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/api/status")
def api_status():
    return jsonify(analytics.get_status())


@app.get("/api/local-scope")
def api_local_scope():
    try:
        from camera_store import local_scope_catalog

        return jsonify(local_scope_catalog())
    except Exception:
        app.logger.exception("No se pudo consultar la identidad de Vigilay Local")
        return jsonify({"error": "No se pudo consultar la empresa y sede configuradas."}), 503


@app.put("/api/local-scope")
def api_configure_local_scope():
    payload = flask_request.get_json(silent=True) or {}
    try:
        from camera_store import configure_local_scope, local_scope_catalog

        previous = local_scope_catalog().get("configured")
        configured = configure_local_scope(
            tenant_id=str(payload.get("tenant_id") or "").strip() or None,
            tenant_name=str(payload.get("tenant_name") or "").strip(),
            site_id=str(payload.get("site_id") or "").strip() or None,
            site_name=str(payload.get("site_name") or "").strip(),
            address=str(payload.get("address") or "").strip(),
        )
        changed = bool(
            previous
            and (
                previous.get("tenant_id") != configured["tenant_id"]
                or previous.get("site_id") != configured["site_id"]
            )
        )
        return jsonify({"ok": True, "configured": configured, "restart_required": changed})
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except Exception:
        app.logger.exception("No se pudo configurar la identidad de Vigilay Local")
        return jsonify({"error": "No se pudo guardar la empresa y sede."}), 503


@app.get("/api/cameras")
def api_cameras():
    preview_hub.ensure_workers()
    ptz_capabilities = (
        analytics.ptz_capabilities()
        if analytics.get_status().get("camera_online")
        else {"pan_tilt": False, "zoom": False}
    )
    configured = analytics.get_cameras()
    for camera in configured:
        camera["online"] = preview_hub.camera_online(camera["id"])
    return jsonify(
        {
            "configured": configured,
            "discovered": discovered_cameras,
            "ptz_available": any(ptz_capabilities.values()),
            "ptz_capabilities": ptz_capabilities,
        }
    )


@app.get("/api/cameras/status")
def api_camera_statuses():
    preview_hub.ensure_workers()
    return jsonify(
        {
            camera_id: {"online": preview_hub.camera_online(camera_id)}
            for camera_id in analytics.cameras
        }
    )


@app.post("/api/cameras/discover")
def api_discover_cameras():
    global discovered_cameras
    try:
        discovered_cameras = discover_network_cameras(list(analytics.cameras.values()))
        return jsonify({"cameras": discovered_cameras})
    except OSError as error:
        return jsonify({"error": f"No se pudo explorar la red local: {error}"}), 503


@app.post("/api/cameras/<camera_id>/select")
def api_select_camera(camera_id):
    try:
        already_active = (
            camera_id == analytics.active_camera_id
            and analytics.get_status().get("camera_online")
        )
        if not already_active:
            preview_hub.reserve_for_primary(camera_id)
        camera = analytics.select_camera(camera_id)
    except KeyError:
        return jsonify({"error": "La cámara no está configurada."}), 404
    finally:
        preview_hub.release_primary_reservation(camera_id)
    return jsonify(
        {
            "ok": True,
            "id": camera["id"],
            "name": camera["name"],
            "already_active": already_active,
        }
    )


@app.get("/api/cameras/<camera_id>/configuration")
def api_camera_configuration(camera_id):
    try:
        return jsonify(analytics.get_camera_configuration(camera_id))
    except KeyError:
        return jsonify({"error": "La cámara no está configurada."}), 404


@app.get("/api/frigate/cameras")
def api_frigate_cameras():
    try:
        return jsonify([{"name": name} for name in load_frigate_camera_names()])
    except RuntimeError as error:
        return jsonify({"error": str(error)}), 502


@app.put("/api/cameras/<camera_id>")
def api_update_camera(camera_id):
    try:
        result = analytics.update_camera_configuration(
            camera_id, flask_request.get_json(silent=True) or {}
        )
        return jsonify({"ok": True, **result})
    except KeyError:
        return jsonify({"error": "La cámara no está configurada."}), 404
    except (ValueError, ConnectionError) as error:
        return jsonify({"error": str(error)}), 400
    except Exception as error:
        app.logger.warning("No se pudo editar la cámara %s: %s", camera_id, error)
        return jsonify({"error": "No se pudo guardar la configuración."}), 500


@app.post("/api/cameras/<camera_id>/view")
def api_camera_view(camera_id):
    payload = flask_request.get_json(silent=True) or {}
    try:
        view = analytics.set_camera_view(camera_id, str(payload.get("view", "full")))
    except KeyError:
        return jsonify({"error": "La cámara no está configurada."}), 404
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    return jsonify({"ok": True, "view": view})


@app.post("/api/cameras/configure")
def api_configure_camera():
    payload = flask_request.get_json(silent=True) or {}
    host = str(payload.get("host", "")).strip()
    discovered = next((camera for camera in discovered_cameras if camera["host"] == host), None)
    try:
        if not ipaddress.ip_address(host).is_private:
            raise ValueError
    except ValueError:
        return jsonify({"error": "Introduce una dirección IP privada válida."}), 400

    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))
    path = str(payload.get("path", "")).strip()
    connection_mode = str(payload.get("connection_mode", "rtsp")).strip().lower()
    brand = str(payload.get("brand", discovered["brand"] if discovered else "GENERIC")).upper()
    if brand not in {"EZVIZ", "IMOU", "V380", "GENERIC"}:
        return jsonify({"error": "Selecciona una marca compatible."}), 400
    model = str(payload.get("model", "")).strip()[:120]
    try:
        target_fps = int(payload.get("target_fps", 10))
    except (TypeError, ValueError):
        return jsonify({"error": "Los FPS deben ser un número entero."}), 400
    if not 1 <= target_fps <= 30:
        return jsonify({"error": "Selecciona entre 1 y 30 FPS."}), 400
    grayscale = bool(payload.get("grayscale", False))
    name = str(payload.get("name", "")).strip() or brand
    if not username:
        return jsonify({"error": "Completa el usuario de la cámara."}), 400
    if connection_mode == "onvif" and not (discovered and discovered.get("onvif_available")):
        return jsonify({"error": "Esta cámara no tiene disponible el puerto ONVIF 8899."}), 409
    if connection_mode != "onvif" and brand != "V380" and (not password or not path):
        return jsonify({"error": "Completa contraseña y ruta RTSP."}), 400
    try:
        frigate_camera_name = validate_frigate_camera_name(
            payload.get("frigate_camera_name")
        )
        if brand == "V380":
            device_id = str(payload.get("device_id", "")).strip()
            if not password or not device_id:
                return jsonify({"error": "Completa ID, usuario y contraseña V380."}), 400
            camera = analytics.add_v380_camera(
                host=host,
                name=name,
                model=model,
                device_id=device_id,
                username=username,
                password=password,
                frigate_camera_name=frigate_camera_name,
                target_fps=target_fps,
                grayscale=grayscale,
            )
            analytics.select_camera(camera["id"])
            return jsonify({"ok": True, "id": camera["id"], "name": camera["name"]})
        onvif_port = 8899 if connection_mode == "onvif" else 80
        rtsp_url = (
            discover_onvif_rtsp(host, onvif_port, username, password)
            if connection_mode == "onvif"
            else None
        )
        camera = analytics.add_camera(
            host,
            name,
            brand,
            username,
            password,
            path,
            model,
            target_fps,
            grayscale,
            onvif_port,
            rtsp_url,
            frigate_camera_name,
        )
        analytics.select_camera(camera["id"])
    except ConnectionError as error:
        return jsonify({"error": str(error)}), 401
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except Exception as error:
        app.logger.warning("No se pudo configurar la cámara %s: %s", host, error)
        return jsonify({"error": "No se pudo guardar la cámara."}), 500
    return jsonify({"ok": True, "id": camera["id"], "name": camera["name"]})


@app.post("/api/ptz")
def api_ptz():
    payload = flask_request.get_json(silent=True) or {}
    try:
        analytics.move_ptz(payload.get("action", ""), payload.get("speed", 0.55))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except Exception as error:
        app.logger.warning("No se pudo ejecutar PTZ: %s", error)
        return jsonify({"error": "La cámara no aceptó el movimiento PTZ."}), 502
    return jsonify({"ok": True})


@app.get("/api/ptz/capabilities")
def api_ptz_capabilities():
    if not analytics.get_status().get("camera_online"):
        return jsonify({"pan_tilt": False, "zoom": False})
    return jsonify(analytics.ptz_capabilities())


@app.route("/api/events")
def api_events():
    return jsonify(analytics.get_events())


@app.route("/api/visits")
def api_visits():
    return jsonify(analytics.get_visits())


@app.post("/api/clear-history")
def api_clear_history():
    analytics.clear_history()
    return jsonify({"ok": True})


@app.route("/visitas/<path:filename>")
def visit_image(filename):
    return send_from_directory(VISITS_DIR, filename)


if __name__ == "__main__":
    stream_agent = None
    if os.getenv("START_STREAM_AGENT_WITH_LOCAL", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        from vigilay.config import settings as platform_settings
        from vigilay.stream_agent import CameraStreamResolver, LocalStreamAgent

        platform_settings.cache_clear()
        stream_agent = LocalStreamAgent(
            resolver=CameraStreamResolver(
                v380_starter=lambda camera: _start_v380_bridge(camera, 3)
            )
        )
        stream_agent.start()
        app.logger.info("Agente de transmisión en vivo iniciado dentro de Vigilay Local.")
    analytics.start()
    try:
        app.run(host="0.0.0.0", port=5000, threaded=True)
    finally:
        if stream_agent:
            stream_agent.stop()
