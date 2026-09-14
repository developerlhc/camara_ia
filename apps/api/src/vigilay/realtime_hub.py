"""Process-local fan-out for outbound site-agent WebSockets."""

import asyncio
import threading


class AgentHub:
    def __init__(self):
        self._lock = threading.Lock()
        self._listeners = {}

    def register(self, site_id: str):
        listener = (asyncio.get_running_loop(), asyncio.Queue(maxsize=20))
        with self._lock:
            self._listeners.setdefault(site_id, set()).add(listener)
        return listener

    def unregister(self, site_id: str, listener):
        with self._lock:
            listeners = self._listeners.get(site_id, set())
            listeners.discard(listener)
            if not listeners:
                self._listeners.pop(site_id, None)

    def notify(self, site_id: str, message: dict):
        with self._lock:
            listeners = tuple(self._listeners.get(site_id, ()))
        for loop, queue in listeners:
            loop.call_soon_threadsafe(self._put, queue, message)

    @staticmethod
    def _put(queue, message):
        if queue.full():
            queue.get_nowait()
        queue.put_nowait(message)


agent_hub = AgentHub()


def notify_site(site_id: str, event_type: str, resource_id: str):
    agent_hub.notify(site_id, {"type": "wake", "event": event_type, "resourceId": resource_id})
