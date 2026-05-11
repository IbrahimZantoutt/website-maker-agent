"""
Tool schemas (what the LLM sees) and implementations (what actually runs).
"""
import json
import subprocess
import tempfile
import os
import glob
import re
import difflib

from config import AGENT_DIR, TREE_SKIP

# ── Tool Schemas ─────────────────────────────────────────────────────────────

BASE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file from disk.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file."}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": (
                "Surgically replace a string in a file.\n"
                "  replace_all=false (default): old_string must appear EXACTLY once.\n"
                "  replace_all=true: replaces every occurrence."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file."},
                    "old_string": {"type": "string", "description": "Exact text to find."},
                    "new_string": {"type": "string", "description": "Text to replace it with."},
                    "replace_all": {
                        "type": "boolean",
                        "description": "Replace all occurrences. Default false.",
                    },
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write (create or overwrite) a file with the given content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to write."},
                    "content": {"type": "string", "description": "Full file content."},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": "Run any shell command and return stdout + stderr.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute."}
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run",
            "description": "Execute a Python code snippet directly and return its output.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python source code to execute."}
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": (
                "Search the filesystem.\n"
                "  mode='files'   — find files by glob pattern\n"
                "  mode='content' — grep inside files for a regex pattern"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob (files) or regex (content)."},
                    "path": {
                        "type": "string",
                        "description": "Directory to search. Default: current directory.",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["files", "content"],
                        "description": "Search mode.",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for documentation, API references, best practices, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query string."},
                    "max_results": {
                        "type": "integer",
                        "description": "Number of results (1-10). Default: 5.",
                    },
                },
                "required": ["query"],
            },
        },
    },
]

MESSAGE_AGENT_TOOL = {
    "type": "function",
    "function": {
        "name": "message_agent",
        "description": (
            "Send a message to another active agent or to the user.\n"
            "Use this to coordinate: share API contracts, notify about completed components, "
            "request info, or reply to the user.\n"
            "Pass 'user' as target_id to message the human operator."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "target_id": {
                    "type": "string",
                    "description": "The agent instance ID to message (e.g. 'frontend_0', 'backend_1') or 'user'.",
                },
                "message": {"type": "string", "description": "The message content."},
            },
            "required": ["target_id", "message"],
        },
    },
}

# ── Helpers ───────────────────────────────────────────────────────────────────


def _is_agent_path(path: str) -> bool:
    try:
        resolved = os.path.abspath(path)
        return resolved.startswith(AGENT_DIR + os.sep) or resolved == AGENT_DIR
    except Exception:
        return False


def build_file_tree(root: str = ".", max_depth: int = 4) -> str:
    lines = []

    def _walk(path: str, prefix: str, depth: int):
        if depth > max_depth:
            return
        try:
            entries = sorted(
                os.listdir(path),
                key=lambda e: (os.path.isfile(os.path.join(path, e)), e.lower()),
            )
        except PermissionError:
            return
        entries = [
            e
            for e in entries
            if e not in TREE_SKIP
            and not e.startswith(".")
            and not _is_agent_path(os.path.join(path, e))
        ]
        for i, entry in enumerate(entries):
            is_last = i == len(entries) - 1
            full = os.path.join(path, entry)
            connector = "└── " if is_last else "├── "
            if os.path.isdir(full):
                lines.append(f"{prefix}{connector}{entry}/")
                _walk(full, prefix + ("    " if is_last else "│   "), depth + 1)
            else:
                lines.append(f"{prefix}{connector}{entry}")

    root_abs = os.path.abspath(root)
    lines.append(os.path.basename(root_abs) + "/")
    _walk(root_abs, "", 0)
    return "\n".join(lines)


def _make_diff(path: str, before: str, after: str) -> str:
    lines = list(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=f"a/{os.path.basename(path)}",
            tofile=f"b/{os.path.basename(path)}",
            lineterm="",
            n=2,
        )
    )
    return "\n".join(lines)


def _get(obj, *keys):
    for k in keys:
        if obj is None:
            return None
        obj = obj.get(k) if isinstance(obj, dict) else getattr(obj, k, None)
    return obj


def _normalise_tool_calls(raw_calls: list) -> list:
    out = []
    for i, tc in enumerate(raw_calls):
        name = _get(tc, "function", "name")
        args = _get(tc, "function", "arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        tc_id = _get(tc, "id") or f"call_{i}"
        out.append(
            {
                "id": tc_id,
                "type": "function",
                "function": {"name": name, "arguments": args},
            }
        )
    return out


def _parse_inline_tool_calls(content: str) -> list:
    if not content:
        return []
    text = re.sub(r"```(?:json|python)?\s*", "", content).strip()

    def _extract(obj: dict):
        if "name" in obj and "arguments" in obj:
            args = obj["arguments"]
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            return {"function": {"name": obj["name"], "arguments": args}}
        if "function" in obj and isinstance(obj["function"], dict):
            fn = obj["function"]
            if "name" in fn:
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}
                return {"function": {"name": fn["name"], "arguments": args}}
        return None

    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            call = _extract(obj)
            if call:
                return [call]
    except json.JSONDecodeError:
        pass

    calls = []
    for match in re.finditer(r"\{(?:[^{}]|\{[^{}]*\})*\}", content, re.DOTALL):
        try:
            obj = json.loads(match.group())
            if isinstance(obj, dict):
                call = _extract(obj)
                if call and call not in calls:
                    calls.append(call)
        except Exception:
            pass
    return calls


# ── Tool Implementations ─────────────────────────────────────────────────────


def tool_read_file(path: str) -> str:
    try:
        path = os.path.expanduser(path)
        if _is_agent_path(path):
            return "[error] Cannot access agent internals."
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        lines = content.splitlines()
        if len(lines) > 300:
            content = (
                "\n".join(lines[:300])
                + f"\n\n[... truncated — {len(lines)} total lines]"
            )
        return content
    except FileNotFoundError:
        return f"[error] File not found: {path}"
    except Exception as e:
        return f"[error] {e}"


def tool_edit_file(
    path: str, old_string: str, new_string: str, replace_all: bool = False
) -> str:
    try:
        path = os.path.expanduser(path)
        if _is_agent_path(path):
            return "[error] Cannot access agent internals."
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        count = content.count(old_string)
        if count == 0:
            return f"[error] String not found in {path}"
        if count > 1 and not replace_all:
            return (
                f"[error] String appears {count} times. "
                f"Set replace_all=true or add more context."
            )
        new_content = (
            content.replace(old_string, new_string)
            if replace_all
            else content.replace(old_string, new_string, 1)
        )
        diff = _make_diff(path, content, new_content)
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
        replaced = count if replace_all else 1
        return f"[ok] Replaced {replaced} occurrence(s) in {path}\n{diff}"
    except FileNotFoundError:
        return f"[error] File not found: {path}"
    except Exception as e:
        return f"[error] {e}"


def tool_write_file(path: str, content: str) -> str:
    try:
        path = os.path.expanduser(path)
        if _is_agent_path(path):
            return "[error] Cannot access agent internals."
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        total = len(content.splitlines())
        return f"[ok] Wrote {total} lines to {path}"
    except Exception as e:
        return f"[error] {e}"


def tool_run_shell(command: str) -> str:
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=30
        )
        output = result.stdout
        if result.stderr:
            output += f"\n[stderr]\n{result.stderr}"
        return output.strip() or "[no output]"
    except subprocess.TimeoutExpired:
        return "[error] Command timed out (30s)"
    except Exception as e:
        return f"[error] {e}"


def tool_run(code: str) -> str:
    with tempfile.NamedTemporaryFile(
        suffix=".py", mode="w", delete=False, encoding="utf-8"
    ) as f:
        f.write(code)
        tmp_path = f.name
    try:
        result = subprocess.run(
            ["python", tmp_path], capture_output=True, text=True, timeout=15
        )
        output = result.stdout
        if result.stderr:
            output += f"\n[stderr]\n{result.stderr}"
        return output.strip() or "[no output]"
    except subprocess.TimeoutExpired:
        return "[error] Execution timed out (15s)"
    except Exception as e:
        return f"[error] {e}"
    finally:
        os.unlink(tmp_path)


def tool_search(pattern: str, path: str = ".", mode: str = "files") -> str:
    path = os.path.expanduser(path)
    if mode == "files":
        hits = sorted(
            set(
                glob.glob(os.path.join(path, "**", pattern), recursive=True)
                + glob.glob(os.path.join(path, pattern))
            )
        )
        hits = [h for h in hits if not _is_agent_path(h)]
        return "\n".join(hits) or f"[no files matching '{pattern}' in '{path}']"

    hits = []
    for fp in glob.glob(os.path.join(path, "**", "*"), recursive=True):
        if not os.path.isfile(fp) or _is_agent_path(fp):
            continue
        try:
            with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                for lineno, line in enumerate(f, 1):
                    if re.search(pattern, line):
                        hits.append(f"{fp}:{lineno}: {line.rstrip()}")
                        if len(hits) >= 50:
                            return "\n".join(hits) + "\n[truncated at 50 results]"
        except Exception:
            pass
    return "\n".join(hits) or f"[no content matches for '{pattern}' in '{path}']"


def tool_web_search(query: str, max_results: int = 5) -> str:
    max_results = max(1, min(int(max_results), 10))
    try:
        from duckduckgo_search import DDGS

        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        if not results:
            return f"[No web results for '{query}']"
        lines = [f"=== Web Search: {query} ===\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"[{i}] {r.get('title', 'Untitled')}")
            lines.append(f"    URL: {r.get('href', '')}")
            body = (r.get("body") or "").strip()[:300]
            if body:
                lines.append(f"    {body}")
            lines.append("")
        return "\n".join(lines)
    except ImportError:
        pass
    except Exception:
        pass
    try:
        import urllib.request
        import urllib.parse

        params = urllib.parse.urlencode(
            {"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"}
        )
        req = urllib.request.Request(
            f"https://api.duckduckgo.com/?{params}",
            headers={"User-Agent": "Mozilla/5.0 (compatible; MultiAgent/2.0)"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        lines = [f"=== Web Search (Instant Answers): {query} ===\n"]
        if data.get("Abstract"):
            lines.append(f"Abstract: {data['Abstract']}")
            lines.append(
                f"Source: {data.get('AbstractSource', '')} — {data.get('AbstractURL', '')}\n"
            )
        count = 0
        for topic in data.get("RelatedTopics", []):
            if count >= max_results:
                break
            if isinstance(topic, dict) and topic.get("Text"):
                lines.append(f"- {topic['Text'][:250]}")
                if topic.get("FirstURL"):
                    lines.append(f"  {topic['FirstURL']}")
                count += 1
        if len(lines) < 3:
            return f"[Limited results for '{query}']. pip install duckduckgo-search for better results."
        return "\n".join(lines)
    except Exception as e:
        return f"[web_search error: {e}]"


# ── Tool Dispatch Factory ────────────────────────────────────────────────────


def make_tool_dispatch() -> dict:
    return {
        "read_file": tool_read_file,
        "edit_file": tool_edit_file,
        "write_file": tool_write_file,
        "run_shell": tool_run_shell,
        "run": tool_run,
        "search": tool_search,
        "web_search": tool_web_search,
    }
