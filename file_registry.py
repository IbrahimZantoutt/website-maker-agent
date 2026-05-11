"""
File Registry — prevents write conflicts between parallel agents.
"""
import threading
import time
from typing import Optional

from event_bus import EventBus


class FileRegistry:
    def __init__(self, bus: EventBus):
        self._bus = bus
        self._lock = threading.Lock()
        # filepath → agent_id that owns it
        self._claims: dict[str, str] = {}
        # filepath → set of agent_ids that have read it
        self._reads_log: dict[str, set] = {}
        # agent_id → set of stale filepaths
        self._stale: dict[str, set] = {}

    def claim(self, filepath: str, agent_id: str, timeout: float = 30.0) -> tuple[bool, Optional[str]]:
        """
        Claim a file for writing. Blocks and retries if another agent holds it.
        Returns (True, None) on success or (False, reason) on timeout.
        """
        filepath = filepath.replace("\\", "/")
        deadline = time.time() + timeout

        while True:
            with self._lock:
                owner = self._claims.get(filepath)
                if owner is None or owner == agent_id:
                    self._claims[filepath] = agent_id
                    break
                current_owner = owner

            # Owned by another agent — wait and retry
            if time.time() >= deadline:
                self._bus.publish({
                    "from_id": agent_id,
                    "from_type": "registry",
                    "event_type": "conflict_raised",
                    "payload": {
                        "filepath": filepath,
                        "blocked_agent": agent_id,
                        "owning_agent": current_owner,
                        "reason": f"{agent_id} timed out waiting for {filepath} (held by {current_owner})",
                    },
                    "target": None,
                })
                return (False, f"Timed out: {filepath} held by {current_owner}")

            time.sleep(2)

        self._bus.publish({
            "from_id": agent_id,
            "from_type": "registry",
            "event_type": "file_claimed",
            "payload": {"filepath": filepath, "agent_id": agent_id},
            "target": None,
        })
        return (True, None)

    def release(self, filepath: str, agent_id: str):
        filepath = filepath.replace("\\", "/")
        with self._lock:
            if self._claims.get(filepath) == agent_id:
                del self._claims[filepath]

        self._bus.publish({
            "from_id": agent_id,
            "from_type": "registry",
            "event_type": "file_released",
            "payload": {"filepath": filepath, "agent_id": agent_id},
            "target": None,
        })

    def log_read(self, filepath: str, agent_id: str):
        filepath = filepath.replace("\\", "/")
        with self._lock:
            if filepath not in self._reads_log:
                self._reads_log[filepath] = set()
            self._reads_log[filepath].add(agent_id)

    def notify_file_written(self, filepath: str, writer_id: str, summary: str):
        """Called after a file is written. Flags stale reads for other agents."""
        filepath = filepath.replace("\\", "/")
        with self._lock:
            readers = self._reads_log.get(filepath, set()) - {writer_id}
            for reader_id in readers:
                if reader_id not in self._stale:
                    self._stale[reader_id] = set()
                self._stale[reader_id].add(filepath)

        # Notify each reader that their cached view is stale
        for reader_id in readers:
            self._bus.publish({
                "from_id": "registry",
                "from_type": "registry",
                "event_type": "direct_message",
                "payload": {
                    "message": (
                        f"File {filepath} was modified by {writer_id}. "
                        f"Changes: {summary}. Re-read before using."
                    ),
                },
                "target": reader_id,
            })

    def get_stale_files(self, agent_id: str) -> set:
        with self._lock:
            return set(self._stale.get(agent_id, set()))

    def clear_stale(self, agent_id: str, filepath: str):
        with self._lock:
            if agent_id in self._stale:
                self._stale[agent_id].discard(filepath)

    def get_claimed_files(self) -> dict[str, str]:
        with self._lock:
            return dict(self._claims)

    def is_claimed(self, filepath: str) -> Optional[str]:
        filepath = filepath.replace("\\", "/")
        with self._lock:
            return self._claims.get(filepath)
