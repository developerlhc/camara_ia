import json
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from tools.v380_motion_recorder.recorder import MotionDetector, MotionRecorder, RecorderConfig


def config(tmp_path: Path, **changes):
    values = {
        "source": "rtsp://127.0.0.1:8556/live",
        "output": tmp_path,
        "warmup_frames": 2,
        "min_area_percent": 0.2,
    }
    values.update(changes)
    return RecorderConfig(**values)


def test_detector_ignores_static_image_and_detects_change(tmp_path):
    detector = MotionDetector(config(tmp_path))
    still = np.zeros((240, 320, 3), dtype=np.uint8)
    assert detector.detect(still)[0] is False
    assert detector.detect(still)[0] is False
    changed = still.copy()
    cv2.rectangle(changed, (30, 30), (180, 180), (255, 255, 255), -1)
    moving, percent = detector.detect(changed)
    assert moving is True
    assert percent > 0.2


def test_unique_path_does_not_overwrite_existing_clip(tmp_path):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"existing")
    assert MotionRecorder._unique_path(clip) == tmp_path / "clip_2.mp4"


def test_prebuffer_has_bounded_size(tmp_path):
    recorder = MotionRecorder(config(tmp_path, fps=10, pre_roll=3))
    assert recorder.buffer.maxlen == 30


def test_creates_playable_clip_and_metadata(tmp_path):
    recorder = MotionRecorder(config(tmp_path, fps=5, pre_roll=1, min_free_gb=0))
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    cv2.rectangle(frame, (20, 20), (80, 80), (255, 255, 255), -1)
    recorder._remember(datetime.now().astimezone(), frame)
    recorder._start_clip(frame.shape, time.monotonic())
    for _ in range(4):
        recorder.writer.write(frame)
        recorder.frames_written += 1
    recorder._finish_clip("test")

    videos = list(tmp_path.rglob("*.mp4"))
    assert len(videos) == 1
    assert videos[0].stat().st_size > 0
    assert videos[0].with_suffix(".json").exists()
    metadata = json.loads(videos[0].with_suffix(".json").read_text(encoding="utf-8"))
    assert metadata["codec"] == "h264"
    capture = cv2.VideoCapture(str(videos[0]))
    assert capture.isOpened()
    assert int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) == 5
    capture.release()
