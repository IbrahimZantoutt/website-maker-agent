import json
import subprocess
import tempfile
import os
import glob
import re
import difflib

# ── Configuration ─────────────────────────────────────────────────────────────

MODELS = [
    "minimax-m2.5:cloud",
    "qwen2.5-coder:7b",
]
MODEL     = MODELS[0]
MAX_STEPS = 200

# Directory of this file — excluded from file tree, search, and edits
AGENT_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Tool Schemas (what the model sees) ────────────────────────────────────────

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
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": (
                "Surgically replace a string in a file.\n"
                "  replace_all=false (default): old_string must appear EXACTLY once — "
                "add more context to make it unique, or set replace_all=true.\n"
                "  replace_all=true: replaces every occurrence."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path":        {"type": "string",  "description": "Path to the file."},
                    "old_string":  {"type": "string",  "description": "Exact text to find."},
                    "new_string":  {"type": "string",  "description": "Text to replace it with."},
                    "replace_all": {"type": "boolean", "description": "Replace all occurrences. Default false."}
                },
                "required": ["path", "old_string", "new_string"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write (create or overwrite) a file with the given content. Use for new files or full rewrites.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path":    {"type": "string", "description": "Path to write."},
                    "content": {"type": "string", "description": "Full file content."}
                },
                "required": ["path", "content"]
            }
        }
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
                "required": ["command"]
            }
        }
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
                "required": ["code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": (
                "Search the filesystem.\n"
                "  mode='files'   — find files by glob pattern (e.g. '*.py')\n"
                "  mode='content' — grep inside files for a regex pattern"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob (files) or regex (content)."},
                    "path":    {"type": "string", "description": "Directory to search. Default: current directory."},
                    "mode":    {"type": "string", "enum": ["files", "content"], "description": "Search mode."}
                },
                "required": ["pattern"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": (
                "Ask the user a question and wait for their response. "
                "Use ONLY when genuinely blocked — ambiguous scope, key decision requiring human preference, "
                "or missing information that cannot be inferred from the codebase. "
                "Do NOT use for things resolvable by reading files or applying best practices."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The question to ask the user."},
                    "choices": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional 2-4 choices. If provided, user picks one; otherwise free text."
                    }
                },
                "required": ["question"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web for documentation, API references, CVEs, best practices, "
                "package info, error messages, or any technical topic. "
                "Returns titles, URLs, and content snippets from top results."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query":       {"type": "string",  "description": "Search query string."},
                    "max_results": {"type": "integer", "description": "Number of results to return (1-10). Default: 5."}
                },
                "required": ["query"]
            }
        }
    }
]

# ── Helpers ───────────────────────────────────────────────────────────────────

_TREE_SKIP = {
    ".git", "__pycache__", ".venv", "venv", ".env",
    "node_modules", ".pytest_cache", ".mypy_cache", "dist", "build",
    "project_context",
}


def _is_agent_path(path: str) -> bool:
    """Return True if the resolved path is inside the agent's own directory."""
    try:
        return (os.path.abspath(path).startswith(AGENT_DIR + os.sep) or
                os.path.abspath(path) == AGENT_DIR)
    except Exception:
        return False


def build_file_tree(root: str = ".", max_depth: int = 4) -> str:
    """Return a compact ASCII tree of the working directory."""
    lines = []

    def _walk(path: str, prefix: str, depth: int):
        if depth > max_depth:
            return
        try:
            entries = sorted(
                os.listdir(path),
                key=lambda e: (os.path.isfile(os.path.join(path, e)), e.lower())
            )
        except PermissionError:
            return
        entries = [
            e for e in entries
            if e not in _TREE_SKIP
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
    lines = list(difflib.unified_diff(
        before.splitlines(),
        after.splitlines(),
        fromfile=f"a/{os.path.basename(path)}",
        tofile=f"b/{os.path.basename(path)}",
        lineterm="",
        n=2,
    ))
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
        # Preserve existing id or generate a synthetic one; add type field
        tc_id = _get(tc, "id") or f"call_{i}"
        out.append({
            "id":       tc_id,
            "type":     "function",
            "function": {"name": name, "arguments": args},
        })
    return out


def _parse_inline_tool_calls(content: str) -> list:
    """Fallback parser for models that output tool calls as JSON text in content."""
    if not content:
        return []
    text = re.sub(r'```(?:json|python)?\s*', '', content).strip()

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
    for match in re.finditer(r'\{(?:[^{}]|\{[^{}]*\})*\}', content, re.DOTALL):
        try:
            obj = json.loads(match.group())
            if isinstance(obj, dict):
                call = _extract(obj)
                if call and call not in calls:
                    calls.append(call)
        except Exception:
            pass
    return calls


# ── Tool Implementations ──────────────────────────────────────────────────────

def tool_read_file(path: str) -> str:
    try:
        path = os.path.expanduser(path)
        if _is_agent_path(path):
            return "[error] Cannot access agent internals — this folder is off-limits."
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        lines = content.splitlines()
        if len(lines) > 300:
            content = "\n".join(lines[:300]) + f"\n\n[... truncated — {len(lines)} total lines]"
        return content
    except FileNotFoundError:
        return f"[error] File not found: {path}"
    except Exception as e:
        return f"[error] {e}"


def tool_run(code: str) -> str:
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False, encoding="utf-8") as f:
        f.write(code)
        tmp_path = f.name
    try:
        result = subprocess.run(
            ["python", tmp_path],
            capture_output=True, text=True, timeout=15
        )
        output = result.stdout
        if result.stderr:
            output += f"\n[stderr]\n{result.stderr}"
        return output.strip() or "[no output]"
    except subprocess.TimeoutExpired:
        return "[error] Execution timed out (15 s)"
    except Exception as e:
        return f"[error] {e}"
    finally:
        os.unlink(tmp_path)


def tool_search(pattern: str, path: str = ".", mode: str = "files") -> str:
    path = os.path.expanduser(path)
    if mode == "files":
        hits = sorted(set(
            glob.glob(os.path.join(path, "**", pattern), recursive=True) +
            glob.glob(os.path.join(path, pattern))
        ))
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
        return "[error] Command timed out (30 s)"
    except Exception as e:
        return f"[error] {e}"


def tool_web_search(query: str, max_results: int = 5) -> str:
    """Search the web using DuckDuckGo — no API key required."""
    max_results = max(1, min(int(max_results), 10))
    # Try duckduckgo_search package (pip install duckduckgo-search)
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
            body = (r.get('body') or '').strip()[:300]
            if body:
                lines.append(f"    {body}")
            lines.append("")
        return "\n".join(lines)
    except ImportError:
        pass
    except Exception:
        pass
    # Fallback: DuckDuckGo Instant Answer API (no install required)
    try:
        import urllib.request
        import urllib.parse
        import json as _json
        params = urllib.parse.urlencode(
            {"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"}
        )
        req = urllib.request.Request(
            f"https://api.duckduckgo.com/?{params}",
            headers={"User-Agent": "Mozilla/5.0 (compatible; MultiAgent/1.0)"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read().decode())
        lines = [f"=== Web Search (Instant Answers): {query} ===\n"]
        if data.get("Abstract"):
            lines.append(f"Abstract: {data['Abstract']}")
            lines.append(f"Source: {data.get('AbstractSource', '')} — {data.get('AbstractURL', '')}\n")
        count = 0
        for topic in data.get("RelatedTopics", []):
            if count >= max_results:
                break
            if isinstance(topic, dict) and topic.get("Text"):
                lines.append(f"• {topic['Text'][:250]}")
                if topic.get("FirstURL"):
                    lines.append(f"  {topic['FirstURL']}")
                count += 1
        if len(lines) < 3:
            return (f"[Limited results for '{query}']. "
                    "For full web search: pip install duckduckgo-search")
        return "\n".join(lines)
    except Exception as e:
        return f"[web_search error: {e}. Install: pip install duckduckgo-search]"


# ── Thread-safe Tool Dispatch Factory ─────────────────────────────────────────

def make_tool_dispatch(edit_approval_fn=None, ask_user_fn=None) -> dict:
    """
    Returns a tool dispatch dict with callbacks captured as closures.
    Thread-safe: each specialist agent gets its own dispatch dict,
    so parallel agents never overwrite each other's callbacks.
    """

    def tool_edit_file(path: str, old_string: str, new_string: str,
                       replace_all: bool = False) -> str:
        try:
            path = os.path.expanduser(path)
            if _is_agent_path(path):
                return "[error] Cannot access agent internals — this folder is off-limits."
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            count = content.count(old_string)
            if count == 0:
                return f"[error] String not found in {path}"
            if count > 1 and not replace_all:
                return (
                    f"[error] String appears {count} times. "
                    f"Set replace_all=true to fix all occurrences, "
                    f"or include more surrounding context to make it unique."
                )
            new_content = (
                content.replace(old_string, new_string) if replace_all
                else content.replace(old_string, new_string, 1)
            )
            diff = _make_diff(path, content, new_content)
            if edit_approval_fn is not None:
                if not edit_approval_fn(path, old_string, new_string, diff):
                    return f"[skipped] Edit to {path} rejected by user"
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
                return "[error] Cannot access agent internals — this folder is off-limits."
            if edit_approval_fn is not None:
                preview = "\n".join(content.splitlines()[:20])
                suffix = "\n..." if len(content.splitlines()) > 20 else ""
                if not edit_approval_fn(path, "", content, f"(new file)\n{preview}{suffix}"):
                    return f"[skipped] Write to {path} rejected by user"
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            lines = content.splitlines()
            total = len(lines)
            PREVIEW = 10
            diff_lines = [
                f"--- a/{os.path.basename(path)}",
                f"+++ b/{os.path.basename(path)}",
                f"@@ -0,0 +1,{total} @@",
            ] + [f"+{l}" for l in lines[:PREVIEW]]
            if total > PREVIEW:
                diff_lines.append(f"+... ({total - PREVIEW} more lines)")
            return f"[ok] Wrote {total} lines to {path}\n" + "\n".join(diff_lines)
        except Exception as e:
            return f"[error] {e}"

    def tool_ask_user(question: str, choices: list = None) -> str:
        choices = choices or []
        if ask_user_fn is not None:
            return ask_user_fn(question, choices)
        print(f"\n? {question}")
        if choices:
            for i, c in enumerate(choices, 1):
                print(f"  {i}. {c}")
            while True:
                try:
                    idx = int(input("Enter number: ").strip()) - 1
                    if 0 <= idx < len(choices):
                        return choices[idx]
                    print(f"Please enter 1-{len(choices)}")
                except (ValueError, EOFError):
                    return choices[0]
        else:
            try:
                return input("> ").strip()
            except EOFError:
                return ""

    return {
        "read_file":  tool_read_file,
        "edit_file":  tool_edit_file,
        "write_file": tool_write_file,
        "run_shell":  tool_run_shell,
        "run":        tool_run,
        "search":     tool_search,
        "ask_user":   tool_ask_user,
        "web_search": tool_web_search,
    }
