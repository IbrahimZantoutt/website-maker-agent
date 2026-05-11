"""
Agent registry and specialist agent runner.

Each agent file exports a SPEC dict that may include:
  - name, icon, color, description, system_prompt  (required)
  - restricted_tools: list[str]   — base tools to REMOVE for this agent
  - extra_tools:      list[dict]  — additional tool schemas to ADD
  - extra_dispatch:   dict        — implementations for extra_tools
"""
import json
import sys
import os

import ollama

_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _parent not in sys.path:
    sys.path.insert(0, _parent)

from tools import (
    BASE_TOOLS, AGENT_DIR, make_tool_dispatch,
    _get, _normalise_tool_calls, _parse_inline_tool_calls,
)

from .code_analyst   import SPEC as _code_analyst_spec
from .legacy_analyst import SPEC as _legacy_analyst_spec
from .architect      import SPEC as _architect_spec
from .frontend       import SPEC as _frontend_spec
from .backend        import SPEC as _backend_spec
from .integration    import SPEC as _integration_spec
from .devops         import SPEC as _devops_spec
from .qa_testing     import SPEC as _qa_testing_spec
from .security       import SPEC as _security_spec

AGENT_REGISTRY: dict = {
    "code_analyst":   _code_analyst_spec,
    "legacy_analyst": _legacy_analyst_spec,
    "architect":      _architect_spec,
    "frontend":       _frontend_spec,
    "backend":        _backend_spec,
    "integration":    _integration_spec,
    "devops":         _devops_spec,
    "qa_testing":     _qa_testing_spec,
    "security":       _security_spec,
}


def run_specialist_agent(
    agent_id: str,
    agent_task: str,
    context_str: str,
    model: str,
    max_steps: int,
    on_event,
    edit_approval_fn=None,
    ask_user_fn=None,
) -> str:
    spec        = AGENT_REGISTRY.get(agent_id, {})
    agent_name  = spec.get("name",  agent_id)
    agent_color = spec.get("color", "#c9d1d9")

    def emit(ev_type: str, **kwargs):
        if on_event:
            on_event({
                "type":        ev_type,
                "agent":       agent_id,
                "agent_name":  agent_name,
                "agent_color": agent_color,
                **kwargs,
            })

    emit("agent_start")

    # ── Build per-agent tool set ───────────────────────────────────────────────
    restricted = set(spec.get("restricted_tools", []))

    # Filter base tools
    agent_tools = [
        t for t in BASE_TOOLS
        if t["function"]["name"] not in restricted
    ]
    # Add agent-specific extras
    agent_tools += spec.get("extra_tools", [])

    # Build dispatch: filtered base + agent extras
    base_dispatch = make_tool_dispatch(edit_approval_fn, ask_user_fn)
    for r in restricted:
        base_dispatch.pop(r, None)
    all_dispatch = {**base_dispatch, **spec.get("extra_dispatch", {})}

    # ── Build system prompt ────────────────────────────────────────────────────
    base_prompt = spec.get("system_prompt", f"You are the {agent_name} agent.")

    # Build tools summary for the prompt
    tool_names = [t["function"]["name"] for t in agent_tools]
    tools_list = "\n".join(f"  {n}(...)" for n in tool_names)

    system_prompt = (
        f"{base_prompt}\n\n"
        "═══ PROJECT CONTEXT ═══\n"
        f"{context_str}\n"
        "═══ END CONTEXT ═══\n\n"
        f"YOUR TOOLS ({len(agent_tools)} available):\n"
        f"{tools_list}\n\n"
        "STRICT RULES:\n"
        f"  - NEVER access, read, edit, or run files inside the system directory: {AGENT_DIR}\n"
        "    (read_file/edit_file/write_file will return an error if you try — don't attempt it)\n"
        "  - NEVER describe a change without applying it — always use edit_file or write_file\n"
        "  - ALWAYS read a file before editing it\n"
        "  - NEVER say 'please run' or 'please do' — do it yourself with tools\n"
        "  - Write your report file when finished"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": agent_task},
    ]

    final_content = ""

    for step in range(1, max_steps + 1):
        resp = ollama.chat(model=model, messages=messages, tools=agent_tools)

        msg        = resp.message if hasattr(resp, "message") else resp["message"]
        content    = _get(msg, "content") or ""
        raw_calls  = _get(msg, "tool_calls") or []
        tool_calls = _normalise_tool_calls(raw_calls)

        if not tool_calls:
            tool_calls = _parse_inline_tool_calls(content)
            if tool_calls:
                emit("agent_fallback", count=len(tool_calls))
                content = ""
                # Assign synthetic ids to inline-parsed calls (they have none)
                for i, tc in enumerate(tool_calls):
                    tc.setdefault("id",   f"call_{step}_{i}")
                    tc.setdefault("type", "function")

        if not tool_calls:
            final_content = content
            emit("agent_done", output=content[:500])
            return content

        messages.append({
            "role":       "assistant",
            "content":    content,
            "tool_calls": tool_calls,
        })

        emit("agent_step", n=step)

        for tc in tool_calls:
            fn   = tc["function"]["name"]
            args = tc["function"]["arguments"]

            args_str = json.dumps(args, ensure_ascii=False)
            if len(args_str) > 120:
                args_str = args_str[:120] + "\u2026"

            emit("agent_tool_call", name=fn, args=args, args_str=args_str)

            handler = all_dispatch.get(fn)
            if handler:
                try:
                    result = handler(**args)
                except TypeError as e:
                    result = (
                        f"[tool error: {e}]\n"
                        f"Hint: check that argument names/types match the tool schema and retry."
                    )
                except Exception as e:
                    result = f"[tool error: {type(e).__name__}: {e}]"
            else:
                result = f"[unknown tool: {fn}]"

            preview = result[:300] + ("\u2026" if len(result) > 300 else "")
            emit("agent_tool_result", text=result, preview=preview)

            # Truncate before adding to context — prevents context window overflow
            MAX_RESULT_CHARS = 4000
            result_for_msg = (
                result if len(result) <= MAX_RESULT_CHARS
                else result[:MAX_RESULT_CHARS] + f"\n[truncated — {len(result)} total chars]"
            )
            messages.append({
                "role":         "tool",
                "tool_call_id": tc.get("id", ""),
                "content":      result_for_msg,
            })

    # Loop exhausted without a clean stop — notify UI and return whatever we have
    emit("max_steps")
    emit("agent_done", output=final_content[:500])
    return final_content
