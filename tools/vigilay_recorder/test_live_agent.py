import threading
from types import SimpleNamespace

from tools.vigilay_recorder import live_agent


class Output(list):
    def close(self):
        return None


class Process:
    def __init__(self):
        self.stdout = Output(["frame=1\n"])
        self.running = True
        self.terminated = False

    def poll(self):
        return None if self.running else 0

    def terminate(self):
        self.terminated = True
        self.running = False

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.running = False


def test_integrated_live_agent_starts_once_reports_ready_and_stops(monkeypatch):
    camera = SimpleNamespace(id="camera-1", source="rtsp://camera/live", enabled=True)
    config = SimpleNamespace(
        site_id="site-id",
        gateway_token="x" * 40,
        api_url="https://vigilay.example",
        cameras=(camera,),
    )
    process = Process()
    commands = []
    jobs = [{"camera_id": camera.id, "publish_url": "https://cloudflare.example/publish"}]
    statuses = []

    def popen(command, **_kwargs):
        commands.append(command)
        return process

    agent = live_agent.SiteLiveAgent(config, threading.Event(), popen=popen)

    def post(path, payload):
        if path.endswith("poll"):
            return {"streams": list(jobs)}
        statuses.append(payload["status"])
        return {}

    monkeypatch.setattr(live_agent, "ffmpeg_executable", lambda: "vigilay-ffmpeg.exe")
    agent._post = post
    agent.reconcile()
    for thread in threading.enumerate():
        if thread.name == "live-progress-camera-1":
            thread.join(timeout=1)
    agent.reconcile()
    assert len(commands) == 1
    assert statuses == ["starting", "live"]
    assert "rtsp://camera/live" in commands[0]
    buffer_option = commands[0].index("-ts_buffer_size")
    assert commands[0][buffer_option + 1] == "16777216"

    jobs.clear()
    agent.reconcile()
    assert process.terminated is True
    assert not agent.publishers
