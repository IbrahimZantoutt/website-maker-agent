"""
Agent Runtime — unified runner with peer awareness, proactive messaging,
file registry integration, and user message queue.
"""
import json
import os
import queue
import re
import time
from typing import Callable, Optional

import ollama

from config import AGENT_DIR, MAX_STEPS
from tools import (
    BASE_TOOLS, MESSAGE_AGENT_TOOL,
    make_tool_dispatch, _get, _normalise_tool_calls, _parse_inline_tool_calls,
)
from event_bus import EventBus, make_agent_inbox, drain_inbox
from file_registry import FileRegistry
from agents import AGENT_REGISTRY


# ── Proactive trigger detection ──────────────────────────────────────────────

_FUNC_DEF_RE = re.compile(
    r'(?:def|function|const|class|export\s+(?:default\s+)?(?:function|class))\s+(\w+)',
)
_ENDPOINT_RE = re.compile(
    r'@(?:app|router)\.\s*(?:get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)',
    re.IGNORECASE,
)
_COMPONENT_RE = re.compile(
    r'(?:export\s+(?:default\s+)?)?(?:function|const)\s+([A-Z]\w+)',
)


def _detect_definitions(content: str) -> list[dict]:
    """Parse written file content for function/component/endpoint definitions."""
    defs = []
    for m in _FUNC_DEF_RE.finditer(content):
        defs.append({"type": "function", "name": m.group(1)})
    for m in _COMPONENT_RE.finditer(content):
        if m.group(1) not in [d["name"] for d in defs]:
            defs.append({"type": "component", "name": m.group(1)})
    for m in _ENDPOINT_RE.finditer(content):
        defs.append({"type": "endpoint", "path": m.group(1)})
    return defs


def _file_relevant_to_agent(filepath: str, all_agents: dict) -> list[str]:
    """Return agent IDs whose task description mentions this filepath."""
    filepath_norm = filepath.replace("\\", "/")
    basename = os.path.basename(filepath_norm)
    relevant = []
    for agent_id, info in all_agents.items():
        task_text = info.get("task", "")
        likely_files = info.get("likely_files", [])
        # Check if the filepath or basename appears in the task or likely_files
        all_text = task_text + " " + " ".join(likely_files)
        if basename in all_text or filepath_norm in all_text.replace("\\", "/"):
            relevant.append(agent_id)
    return relevant


# ── Peer Awareness Block builder ─────────────────────────────────────────────

def _build_peer_block(
    agent_id: str,
    bus: EventBus,
    registry: FileRegistry,
    all_agents: dict,
    inbox_messages: list[dict],
) -> str:
    """Build the LIVE PEER AWARENESS block injected at the top of each LLM call."""
    lines = [
        "\n" + "=" * 58,
        "           LIVE PEER AWARENESS — READ FIRST           ",
        "=" * 58,
    ]

    # Active agents
    lines.append("\nACTIVE AGENTS RIGHT NOW:")
    for aid, info in all_agents.items():
        if aid == agent_id:
            continue
        status = info.get("status", "WORKING")
        current = info.get("current_action", "")
        lines.append(f"  {aid:<16} | {status:<8} | {current}")

    # Claimed files
    claimed = registry.get_claimed_files()
    if claimed:
        lines.append("\nFILES YOU SHOULD KNOW ABOUT:")
        for fp, owner in claimed.items():
            if owner != agent_id:
                lines.append(f"  ! {fp} — owned by {owner}. DO NOT TOUCH.")

    # Recent bus events (last 10 minutes, skip own events)
    recent = bus.get_recent(minutes=10, limit=20)
    external = [e for e in recent if e.get("from_id") != agent_id]
    if external:
        lines.append("\nRECENT BUS EVENTS:")
        for e in external[-10:]:
            ts = time.strftime("%H:%M", time.localtime(e.get("timestamp", 0)))
            from_id = e.get("from_id", "?")
            etype = e.get("event_type", "?")
            payload = e.get("payload", {})
            summary = ""
            if etype == "schema_committed":
                summary = payload.get("contract", str(payload)[:100])
            elif etype == "file_written":
                summary = f"{payload.get('filepath', '?')} — {payload.get('summary', '')[:80]}"
            elif etype == "function_defined":
                summary = f"{payload.get('name', '?')}()"
            elif etype == "direct_message":
                summary = payload.get("message", "")[:100]
            elif etype == "task_progress":
                summary = payload.get("summary", "")[:80]
            elif etype == "task_complete":
                summary = "completed"
            else:
                summary = str(payload)[:80]
            lines.append(f"  [{ts}] {from_id:<16} -> {etype}: {summary}")

    # Inbox (unread directed messages)
    inbox_directs = [
        m for m in inbox_messages
        if m.get("event_type") in ("direct_message", "user_message")
    ]
    if inbox_directs:
        lines.append("\nYOUR INBOX (unread messages):")
        for m in inbox_directs:
            from_id = m.get("from_id", "?")
            text = m.get("payload", {}).get("message", m.get("payload", {}).get("text", ""))
            lines.append(f"  FROM {from_id}: \"{text[:200]}\"")

    # Stale file warnings
    stale = registry.get_stale_files(agent_id)
    if stale:
        lines.append("\nSTALE FILE WARNINGS:")
        for fp in stale:
            lines.append(f"  ! You previously read {fp} — it was modified since then. Re-read before using.")

    lines.append("=" * 58 + "\n")
    return "\n".join(lines)


# ── Agent Runtime ────────────────────────────────────────────────────────────

class AgentRuntime:
    def __init__(
        self,
        instance_id: str,
        agent_type: str,
        task: str,
        context_str: str,
        model: str,
        bus: EventBus,
        registry: FileRegistry,
        all_agents: dict,
        on_event: Optional[Callable] = None,
        likely_files: Optional[list] = None,
    ):
        self.instance_id = instance_id
        self.agent_type = agent_type
        self.task = task
        self.context_str = context_str
        self.model = model
        self.bus = bus
        self.registry = registry
        self.all_agents = all_agents
        self.on_event = on_event
        self.likely_files = likely_files or []

        self.spec = AGENT_REGISTRY.get(agent_type, {})
        self.agent_name = self.spec.get("name", agent_type)
        self.agent_color = self.spec.get("color", "#c9d1d9")

        # Queues
        self.inbox = make_agent_inbox(bus, instance_id)
        self.user_message_queue: queue.Queue = queue.Queue()

        # State
        self.status = "STARTING"
        self.current_action = ""
        self.step = 0

    def emit(self, ev_type: str, **kwargs):
        if self.on_event:
            self.on_event({
                "type": ev_type,
                "agent": self.instance_id,
                "agent_type": self.agent_type,
                "agent_name": self.agent_name,
                "agent_color": self.agent_color,
                **kwargs,
            })

    def _publish_bus(self, event_type: str, payload: dict, target: str = None):
        self.bus.publish({
            "from_id": self.instance_id,
            "from_type": self.agent_type,
            "event_type": event_type,
            "payload": payload,
            "target": target,
        })

    def _handle_message_agent(self, target_id: str, message: str) -> str:
        """Handle the message_agent tool call."""
        if target_id == "user":
            self._publish_bus("user_reply", {"message": message, "from": self.instance_id})
            self.emit("agent_message_user", message=message)
            return f"[ok] Message sent to user."
        else:
            self._publish_bus("direct_message", {"message": message}, target=target_id)
            return f"[ok] Message sent to {target_id}."

    def _wrap_tool_with_registry(self, base_dispatch: dict) -> dict:
        """Wrap read_file/edit_file/write_file to integrate with file registry."""
        original_read = base_dispatch.get("read_file")
        original_edit = base_dispatch.get("edit_file")
        original_write = base_dispatch.get("write_file")

        def wrapped_read_file(path: str) -> str:
            result = original_read(path=path)
            if not result.startswith("[error]"):
                self.registry.log_read(path, self.instance_id)
                self.registry.clear_stale(self.instance_id, path.replace("\\", "/"))
            return result

        def wrapped_edit_file(path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
            # Claim the file
            ok, reason = self.registry.claim(path, self.instance_id)
            if not ok:
                return f"[error] Cannot claim {path}: {reason}"
            result = original_edit(path=path, old_string=old_string, new_string=new_string, replace_all=replace_all)
            if "[ok]" in result:
                summary = f"edited: replaced text in {os.path.basename(path)}"
                self._publish_bus("file_written", {"filepath": path, "summary": summary})
                self.registry.notify_file_written(path, self.instance_id, summary)
                self._fire_proactive_triggers(path, new_string)
            self.registry.release(path, self.instance_id)
            return result

        def wrapped_write_file(path: str, content: str) -> str:
            ok, reason = self.registry.claim(path, self.instance_id)
            if not ok:
                return f"[error] Cannot claim {path}: {reason}"
            result = original_write(path=path, content=content)
            if "[ok]" in result:
                summary = f"wrote {len(content.splitlines())} lines to {os.path.basename(path)}"
                self._publish_bus("file_written", {"filepath": path, "summary": summary})
                self.registry.notify_file_written(path, self.instance_id, summary)
                self._fire_proactive_triggers(path, content)
            self.registry.release(path, self.instance_id)
            return result

        dispatch = dict(base_dispatch)
        if original_read:
            dispatch["read_file"] = wrapped_read_file
        if original_edit:
            dispatch["edit_file"] = wrapped_edit_file
        if original_write:
            dispatch["write_file"] = wrapped_write_file
        dispatch["message_agent"] = self._handle_message_agent
        return dispatch

    def _fire_proactive_triggers(self, filepath: str, content: str):
        """After a write, detect definitions and notify relevant peers."""
        defs = _detect_definitions(content)

        for d in defs:
            if d["type"] == "endpoint":
                self._publish_bus("schema_committed", {
                    "contract": d["path"],
                    "file": filepath,
                })
            else:
                self._publish_bus("function_defined", {
                    "name": d.get("name", ""),
                    "type": d["type"],
                    "file": filepath,
                })

        # Notify agents whose task mentions this file
        relevant = _file_relevant_to_agent(filepath, self.all_agents)
        for aid in relevant:
            if aid != self.instance_id:
                self._publish_bus("direct_message", {
                    "message": f"I just wrote to {filepath}. You may want to re-read it.",
                }, target=aid)

    def run(self) -> str:
        """Main agent execution loop."""
        self.status = "WORKING"
        self._publish_bus("agent_started", {"task": self.task})
        self.emit("agent_start", task=self.task)

        # Build tool set
        restricted = set(self.spec.get("restricted_tools", []))
        agent_tools = [t for t in BASE_TOOLS if t["function"]["name"] not in restricted]
        agent_tools += self.spec.get("extra_tools", [])

        # Add message_agent for execution agents (not analysts)
        if self.agent_type != "code_analyst":
            agent_tools.append(MESSAGE_AGENT_TOOL)

        # Build dispatch
        base_dispatch = make_tool_dispatch()
        for r in restricted:
            base_dispatch.pop(r, None)
        base_dispatch.update(self.spec.get("extra_dispatch", {}))
        all_dispatch = self._wrap_tool_with_registry(base_dispatch)

        # Build system prompt
        base_prompt = self.spec.get("system_prompt", f"You are the {self.agent_name} agent.")
        tool_names = [t["function"]["name"] for t in agent_tools]
        tools_list = "\n".join(f"  {n}(...)" for n in tool_names)

        # Load instructions.md from agent system dir (if present)
        _instructions = ""
        _instructions_path = os.path.join(AGENT_DIR, "instructions.md")
        if os.path.exists(_instructions_path):
            try:
                with open(_instructions_path, "r", encoding="utf-8") as _f:
                    _instructions = _f.read().strip()
            except Exception:
                pass

        static_system = (
            f"{base_prompt}\n\n"
            "=== PROJECT CONTEXT ===\n"
            f"{self.context_str}\n"
            "=== END CONTEXT ===\n\n"
            f"YOUR TOOLS ({len(agent_tools)} available):\n"
            f"{tools_list}\n\n"
            "RULES:\n"
            f"  - NEVER access files inside: {AGENT_DIR}\n"
            "  - ALWAYS read a file before editing it\n"
            "  - NEVER describe a change without applying it — use tools\n"
            "  - Do NOT ask the user questions unless truly blocked — work autonomously\n"
        )

        if _instructions:
            static_system += (
                "\n=== PROJECT INSTRUCTIONS (read before acting) ===\n"
                f"{_instructions}\n"
                "=== END INSTRUCTIONS ===\n"
            )

        messages = [
            {"role": "user", "content": self.task},
        ]

        final_content = ""

        for step in range(1, MAX_STEPS + 1):
            self.step = step

            # Drain inbox and user messages
            inbox_events = drain_inbox(self.inbox)
            user_msgs = []
            while True:
                try:
                    user_msgs.append(self.user_message_queue.get_nowait())
                except queue.Empty:
                    break

            # Inject user messages as bus events so they appear in peer block
            for um in user_msgs:
                inbox_events.append({
                    "event_type": "user_message",
                    "from_id": "user",
                    "payload": {"text": um, "message": um},
                    "timestamp": time.time(),
                })

            # Build peer awareness block
            peer_block = _build_peer_block(
                self.instance_id, self.bus, self.registry,
                self.all_agents, inbox_events,
            )

            # System prompt = peer block + static system
            system_prompt = peer_block + static_system

            # Build messages for this call
            call_messages = [{"role": "system", "content": system_prompt}] + messages

            # LLM call
            resp = ollama.chat(model=self.model, messages=call_messages, tools=agent_tools)

            msg = resp.message if hasattr(resp, "message") else resp["message"]
            content = _get(msg, "content") or ""
            raw_calls = _get(msg, "tool_calls") or []
            tool_calls = _normalise_tool_calls(raw_calls)

            if not tool_calls:
                tool_calls = _parse_inline_tool_calls(content)
                if tool_calls:
                    content = ""
                    for i, tc in enumerate(tool_calls):
                        tc.setdefault("id", f"call_{step}_{i}")
                        tc.setdefault("type", "function")

            # No tool calls = agent is done
            if not tool_calls:
                final_content = content
                self.status = "DONE"
                self.current_action = "Complete"
                self._publish_bus("task_complete", {"summary": content[:500]})
                self.emit("agent_done", output=content[:500])
                self._update_all_agents_status("DONE", "Complete")
                break

            messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": tool_calls,
            })

            self.emit("agent_step", n=step)

            for tc in tool_calls:
                fn = tc["function"]["name"]
                args = tc["function"]["arguments"]

                args_str = json.dumps(args, ensure_ascii=False)
                if len(args_str) > 120:
                    args_str = args_str[:120] + "..."

                self.current_action = f"{fn}({args_str})"
                self._update_all_agents_status("WORKING", self.current_action)
                self.emit("agent_tool_call", name=fn, args=args, args_str=args_str)

                handler = all_dispatch.get(fn)
                if handler:
                    try:
                        result = handler(**args)
                    except TypeError as e:
                        result = f"[tool error: {e}]\nHint: check argument names/types."
                    except Exception as e:
                        result = f"[tool error: {type(e).__name__}: {e}]"
                else:
                    result = f"[unknown tool: {fn}]"

                preview = result[:300] + ("..." if len(result) > 300 else "")
                self.emit("agent_tool_result", text=result, preview=preview)

                # Detect blocked state from content
                if content and ("blocked" in content.lower() or "cannot proceed" in content.lower()):
                    self._publish_bus("task_blocked", {
                        "reason": content[:200],
                        "agent_id": self.instance_id,
                    })

                # Truncate for context
                MAX_RESULT = 4000
                result_for_msg = (
                    result if len(result) <= MAX_RESULT
                    else result[:MAX_RESULT] + f"\n[truncated — {len(result)} chars]"
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": result_for_msg,
                })

            # Emit progress
            self._publish_bus("task_progress", {
                "step": step,
                "summary": f"Step {step} complete — {len(tool_calls)} tool call(s)",
            })

        else:
            # Loop exhausted
            self.status = "DONE"
            self.emit("max_steps")
            self.emit("agent_done", output=final_content[:500])

        # Cleanup
        self.bus.unregister(self.instance_id)
        return final_content

    def _update_all_agents_status(self, status: str, action: str):
        """Update this agent's status in the shared all_agents dict."""
        if self.instance_id in self.all_agents:
            self.all_agents[self.instance_id]["status"] = status
            self.all_agents[self.instance_id]["current_action"] = action
