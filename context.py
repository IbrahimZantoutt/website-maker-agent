"""
ProjectContext — shared living document passed to every agent.
"""
import json
import os
import threading


class ProjectContext:
    def __init__(self, task: str = "", cwd: str = ""):
        self._lock = threading.Lock()
        self._data = {
            "task": task,
            "cwd": cwd,
            "task_type": "",
            "tech_detected": "",
            "plan": {},
            "phase": "",
            "agent_outputs": {},
            "decisions": [],
        }

    def update(self, key: str, value):
        with self._lock:
            self._data[key] = value

    def get(self, key: str, default=None):
        with self._lock:
            return self._data.get(key, default)

    def record_agent_output(self, agent_id: str, output: str):
        with self._lock:
            self._data["agent_outputs"][agent_id] = output

    def to_dict(self) -> dict:
        with self._lock:
            return dict(self._data)

    def to_json(self) -> str:
        with self._lock:
            return json.dumps(self._data, indent=2, default=str)

    def save(self, directory: str):
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, "context.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_json())
