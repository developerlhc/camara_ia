import csv
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib import request
from urllib.error import URLError

import cv2
from flask import Flask, Response, jsonify, render_template, send_from_directory
from ultralytics import YOLO

try:
    import face_recognition
except ImportError:
    face_recognition = None


BASE_DIR = Path(__file__).resolve().parent
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
CAMERA_WIDTH = int(os.getenv("CAMERA_WIDTH", "1920"))
CAMERA_HEIGHT = int(os.getenv("CAMERA_HEIGHT", "1080"))
TARGET_FPS = float(os.getenv("TARGET_FPS", "10"))
DROP_BUFFER_FRAMES = int(os.getenv("DROP_BUFFER_FRAMES", "14"))
FACE_SCAN_EVERY = int(os.getenv("FACE_SCAN_EVERY", "5"))
REPORT_EVERY_SECONDS = int(os.getenv("REPORT_EVERY_SECONDS", "5"))
VISIT_SAVE_SECONDS = int(os.getenv("VISIT_SAVE_SECONDS", "30"))
FACE_PADDING = int(os.getenv("FACE_PADDING", "28"))
PERSON_PADDING = int(os.getenv("PERSON_PADDING", "18"))
JPEG_QUALITY = int(os.getenv("JPEG_QUALITY", "98"))
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


app = Flask(__name__)


class CameraAnalytics:
    def __init__(self):
        self.model = YOLO(str(MODEL_PATH))
        self.face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        self.known_face_names = []
        self.known_face_encodings = []
        self.latest_frame = None
        self.status = {
            "person_count": 0,
            "face_count": 0,
            "recognized_people": [],
            "unknown_faces": 0,
            "camera_online": False,
            "face_recognition_enabled": face_recognition is not None,
            "last_update": None,
        }
        self.events = []
        self.visit_events = []
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.frame_index = 0
        self.last_report_at = 0.0
        self.last_face_labels = []
        self.last_face_save_labels = []
        self.last_visit_saved = {}
        self.store_occupied = False
        self.empty_since = time.time()

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

    def _run(self):
        while not self.stop_event.is_set():
            capture = cv2.VideoCapture(RTSP_URL, cv2.CAP_FFMPEG)
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)

            if not capture.isOpened():
                self._set_camera_status(False)
                time.sleep(3)
                continue

            self._set_camera_status(True)
            frame_interval = 1 / TARGET_FPS if TARGET_FPS > 0 else 0

            while not self.stop_event.is_set():
                loop_started_at = time.time()
                ok, frame = self._read_latest_frame(capture)
                if not ok:
                    self._set_camera_status(False)
                    break

                processed_frame, snapshot = self._process_frame(frame)

                with self.lock:
                    self.latest_frame = processed_frame
                    self.status.update(snapshot)
                    self.status["camera_online"] = True
                    self.status["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                self._write_report_if_needed(snapshot)
                elapsed = time.time() - loop_started_at
                if frame_interval > elapsed:
                    time.sleep(frame_interval - elapsed)

            capture.release()
            time.sleep(1)

    def _read_latest_frame(self, capture):
        for _ in range(max(0, DROP_BUFFER_FRAMES)):
            capture.grab()
        return capture.read()

    def _process_frame(self, frame):
        self.frame_index += 1
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

        annotated = display_frame.copy()
        self._draw_person_boxes(annotated, person_boxes)
        face_labels = self.last_face_labels
        face_save_labels = self.last_face_save_labels

        if self.frame_index % FACE_SCAN_EVERY == 0:
            face_frame = self._resize_frame(original_frame, FACE_DETECT_WIDTH)
            detected_face_labels = self._recognize_faces(face_frame)
            face_labels = self._scale_face_labels(detected_face_labels, face_frame, display_frame)
            face_save_labels = self._scale_face_labels(detected_face_labels, face_frame, original_frame)
            face_labels, face_save_labels = self._filter_faces_inside_people(
                face_labels, face_save_labels, person_boxes
            )
            self.last_face_labels = face_labels
            self.last_face_save_labels = face_save_labels

        for label in face_labels:
            x1, y1, x2, y2 = label["box"]
            color = (0, 180, 70) if label["name"] != "Desconocido" else (0, 150, 255)
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
            cv2.putText(
                annotated,
                label["name"],
                (x1, max(20, y1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                color,
                2,
                cv2.LINE_AA,
            )

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
        payload = json.dumps(
            {
                "telefono": NOTIFY_PHONE,
                "mensajeTexto": NOTIFY_MESSAGE,
            }
        ).encode("utf-8")
        http_request = request.Request(
            NOTIFY_URL,
            data=payload,
            headers={"content-type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(http_request, timeout=5):
                pass
        except (OSError, URLError):
            pass

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
            if self.latest_frame is None:
                return None
            ok, buffer = cv2.imencode(".jpg", self.latest_frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
            if not ok:
                return None
            return buffer.tobytes()


analytics = CameraAnalytics()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/video_feed")
def video_feed():
    def generate():
        while True:
            frame = analytics.get_jpeg()
            if frame is None:
                time.sleep(0.2)
                continue
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
            time.sleep(0.03)

    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/api/status")
def api_status():
    return jsonify(analytics.get_status())


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
    if not RTSP_URL:
        raise RuntimeError("Configura RTSP_URL para iniciar la cámara de Vigilay.")
    analytics.start()
    app.run(host="0.0.0.0", port=5000, threaded=True)
