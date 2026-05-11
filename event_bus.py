"""
Event Bus — thread-safe pub/sub for inter-agent communication.
"""
import queue
import threading
import time
import uuid
from typing import Callable, Optional


class EventBus:
    def __init__(self):
        self._lock = threading.Lock()
        self._log: list[dict] = []
        # agent_id → callback(event)
        self._subscribers: dict[str, Callable] = {}

    def register(self, subscriber_id: str, callback: Callable):
        with self._lock:
            self._subscribers[subscriber_id] = callback

    def unregister(self, subscriber_id: str):
        with self._lock:
            self._subscribers.pop(subscriber_id, None)

    def publish(self, event: dict):
        event.setdefault("event_id", str(uuid.uuid4()))
        event.setdefault("timestamp", time.time())

        with self._lock:
            self._log.append(event)
            subs = dict(self._subscribers)

        target = event.get("target")
        for sub_id, callback in subs.items():
            # Broadcast (target=None) goes to everyone.
            # Directed events go only to the target subscriber.
            if target is None or target == sub_id:
                try:
                    callback(event)
                except Exception:
                    pass

    def get_log(
        self,
        since: Optional[float] = None,
        limit: Optional[int] = None,
        event_types: Optional[set] = None,
    ) -> list[dict]:
        with self._lock:
            events = list(self._log)
        if since is not None:
            events = [e for e in events if e.get("timestamp", 0) > since]
        if event_types:
            events = [e for e in events if e.get("event_type") in event_types]
        if limit is not None:
            events = events[-limit:]
        return events

    def get_recent(self, minutes: float = 10, limit: int = 30) -> list[dict]:
        cutoff = time.time() - (minutes * 60)
        return self.get_log(since=cutoff, limit=limit)

    def get_events_from(self, from_id: str) -> list[dict]:
        with self._lock:
            return [e for e in self._log if e.get("from_id") == from_id]

    def clear(self):
        with self._lock:
            self._log.clear()
            self._subscribers.clear()


def make_agent_inbox(bus: EventBus, agent_id: str) -> queue.Queue:
    """Register an agent and return its inbox queue."""
    inbox = queue.Queue()

    def _on_event(event: dict):
        inbox.put(event)

    bus.register(agent_id, _on_event)
    return inbox


def drain_inbox(inbox: queue.Queue) -> list[dict]:
    """Non-blocking drain of all pending events from an inbox."""
    events = []
    while True:
        try:
            events.append(inbox.get_nowait())
        except queue.Empty:
            break
    return events
