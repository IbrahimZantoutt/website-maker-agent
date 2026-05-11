import json
import os


class ProjectContext:
    """
    Shared living context document maintained throughout orchestration.
    Every agent reads from and writes to this, ensuring nothing is lost
    between agent invocations.
    """

    def __init__(self, task: str = "", cwd: str = ""):
        self._data = {
            "task": task,
            "cwd": cwd,
            "task_type": "",
            "tech_detected": "",
            "plan": {},
            "phase": "intake",
            "agent_outputs": {},
            "decisions": [],
            "user_answers": {},
        }

    def update(self, key: str, value):
        self._data[key] = value

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def set_phase(self, phase: str):
        self._data["phase"] = phase

    def record_agent_output(self, agent_id: str, output: str):
        self._data["agent_outputs"][agent_id] = output

    def record_decision(self, decision: str):
        self._data["decisions"].append(decision)

    def record_user_answer(self, question: str, answer: str):
        self._data["user_answers"][question] = answer

    def to_json(self) -> str:
        return json.dumps(self._data, indent=2, default=str)

    def to_dict(self) -> dict:
        return dict(self._data)

    def save(self, directory: str):
        """Persist context to disk so agents can read it via read_file."""
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, "context.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_json())
        return path
