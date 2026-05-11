"""
Code Analyst — read-only codebase analysis agent.
"""
import os
import re
import glob as _glob
import collections

_SKIP = {
    ".git", "__pycache__", ".venv", "venv", "node_modules",
    ".pytest_cache", ".mypy_cache", "dist", "build", "project_context",
}


def _skip(path: str) -> bool:
    return bool(set(path.replace("\\", "/").split("/")) & _SKIP)


# ── Tool implementations ─────────────────────────────────────────────────────


def _dependency_scanner(path: str = ".") -> str:
    manifests = [
        ("package.json", "npm/Node.js"), ("requirements.txt", "pip/Python"),
        ("Pipfile", "pipenv"), ("pyproject.toml", "poetry/Python"),
        ("go.mod", "Go modules"), ("Cargo.toml", "Rust/Cargo"),
        ("pom.xml", "Maven/Java"), ("build.gradle", "Gradle/Java"),
        ("composer.json", "PHP Composer"), ("Gemfile", "Ruby Bundler"),
    ]
    results = []
    for filename, ecosystem in manifests:
        fp = os.path.join(path, filename)
        if os.path.exists(fp):
            try:
                with open(fp, encoding="utf-8") as f:
                    content = f.read()
                results.append(f"=== {ecosystem} ({filename}) ===\n{content[:3000]}")
            except Exception as e:
                results.append(f"=== {ecosystem} ({filename}) === [error: {e}]")

    locks = ["package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Cargo.lock", "go.sum"]
    found_locks = [lf for lf in locks if os.path.exists(os.path.join(path, lf))]
    if found_locks:
        results.append("=== Lock files present ===\n" + "\n".join(found_locks))

    return "\n\n".join(results) if results else "[No dependency manifests found]"


def _tech_stack_identifier(path: str = ".") -> str:
    ext_counts = collections.Counter()
    for fp in _glob.glob(os.path.join(path, "**", "*"), recursive=True):
        if os.path.isfile(fp) and not _skip(fp):
            ext = os.path.splitext(fp)[1].lower()
            if ext:
                ext_counts[ext] += 1

    lang_map = {
        ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
        ".jsx": "React/JSX", ".tsx": "React/TSX", ".vue": "Vue.js",
        ".svelte": "Svelte", ".go": "Go", ".rs": "Rust", ".java": "Java",
        ".rb": "Ruby", ".php": "PHP", ".cs": "C#", ".html": "HTML",
        ".css": "CSS", ".scss": "SCSS", ".sql": "SQL",
    }

    lines = ["=== Language distribution (by file count) ==="]
    for ext, count in ext_counts.most_common(20):
        lang = lang_map.get(ext, ext)
        lines.append(f"  {lang} ({ext}): {count} files")

    framework_signals = {
        "next.config.js": "Next.js", "next.config.ts": "Next.js",
        "nuxt.config.ts": "Nuxt.js", "vite.config.ts": "Vite",
        "vite.config.js": "Vite", "angular.json": "Angular",
        "svelte.config.js": "SvelteKit", "manage.py": "Django",
        "tailwind.config.js": "Tailwind CSS", "tailwind.config.ts": "Tailwind CSS",
        "prisma/schema.prisma": "Prisma ORM", "docker-compose.yml": "Docker Compose",
        "jest.config.js": "Jest", "vitest.config.ts": "Vitest",
    }
    found = list(dict.fromkeys(
        fw for sig, fw in framework_signals.items()
        if os.path.exists(os.path.join(path, sig))
    ))
    if found:
        lines.append("\n=== Detected frameworks / tools ===")
        for fw in found:
            lines.append(f"  + {fw}")

    return "\n".join(lines)


def _api_surface_mapper(path: str = ".") -> str:
    patterns = [
        (r'@app\.(get|post|put|delete|patch)\s*\(["\']([^"\']+)', "FastAPI/Flask", 2),
        (r'router\.(get|post|put|delete|patch)\s*\(["\']([^"\']+)', "Express", 2),
        (r'app\.(get|post|put|delete|patch)\s*\(["\']([^"\']+)', "Express app", 2),
        (r'path\s*\(["\']([^"\']+)["\']', "Django URL", 1),
    ]
    endpoints = []
    src_exts = {".py", ".js", ".ts", ".rb", ".php", ".go"}

    for fp in _glob.glob(os.path.join(path, "**", "*"), recursive=True):
        if not os.path.isfile(fp) or _skip(fp):
            continue
        if os.path.splitext(fp)[1].lower() not in src_exts:
            continue
        try:
            with open(fp, encoding="utf-8", errors="ignore") as f:
                for lineno, line in enumerate(f, 1):
                    for pattern, framework, group in patterns:
                        m = re.search(pattern, line, re.IGNORECASE)
                        if m:
                            method = m.group(1).upper() if group == 2 else "ROUTE"
                            ep = m.group(group) if len(m.groups()) >= group else "?"
                            rel = os.path.relpath(fp, path)
                            endpoints.append(f"{rel}:{lineno}  [{framework}] {method} {ep}")
                            break
        except Exception:
            pass
        if len(endpoints) >= 150:
            break

    if not endpoints:
        return "[No API route definitions detected]"
    return f"Found {len(endpoints)} endpoint(s):\n" + "\n".join(endpoints)


def _complexity_analyzer(path: str = ".") -> str:
    findings = []
    for fp in _glob.glob(os.path.join(path, "**", "*.py"), recursive=True):
        if _skip(fp):
            continue
        try:
            with open(fp, encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            rel = os.path.relpath(fp, path)
            func_start, func_name, max_nest = 0, "", 0
            in_func = False
            for i, line in enumerate(lines):
                indent = len(line) - len(line.lstrip(" "))
                nesting = indent // 4
                max_nest = max(max_nest, nesting)
                fn_m = re.match(r'\s*def\s+(\w+)', line)
                if fn_m:
                    if in_func:
                        body = i - func_start
                        if body > 60:
                            findings.append(f"  {rel}:{func_start+1} {func_name}() — {body} lines")
                        if max_nest >= 5:
                            findings.append(f"  {rel}:{func_start+1} {func_name}() — nesting depth {max_nest}")
                    func_name = fn_m.group(1)
                    func_start = i
                    max_nest = 0
                    in_func = True
        except Exception:
            pass

    return ("High-complexity functions:\n" + "\n".join(findings)) if findings \
        else "[No high-complexity functions detected]"


def _pattern_detector(path: str = ".") -> str:
    smell_re_list = [
        (re.compile(r'except\s*:'), "Bare except", {".py"}),
        (re.compile(r'\beval\s*\('), "eval() usage", {".py", ".js", ".ts"}),
        (re.compile(r'SELECT\s+\*\s+FROM', re.I), "SELECT *", {".py", ".js", ".ts", ".php"}),
        (re.compile(r'console\.log\(', re.I), "console.log", {".js", ".ts"}),
        (re.compile(r'debugger;'), "debugger statement", {".js", ".ts"}),
        (re.compile(r'global\s+\w+'), "Global variable", {".py"}),
    ]
    findings = []
    for fp in _glob.glob(os.path.join(path, "**", "*"), recursive=True):
        if not os.path.isfile(fp) or _skip(fp):
            continue
        ext = os.path.splitext(fp)[1]
        try:
            with open(fp, encoding="utf-8", errors="ignore") as f:
                for lineno, line in enumerate(f, 1):
                    for pattern, label, exts in smell_re_list:
                        if ext in exts and pattern.search(line):
                            rel = os.path.relpath(fp, path)
                            findings.append(f"  [{label}] {rel}:{lineno}: {line.strip()[:80]}")
        except Exception:
            pass
        if len(findings) >= 60:
            break

    return "\n".join(findings) if findings else "[No common anti-patterns detected]"


# ── Tool schemas ─────────────────────────────────────────────────────────────

_EXTRA_TOOLS = [
    {"type": "function", "function": {
        "name": "dependency_scanner",
        "description": "Parse all dependency manifests and return their contents.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Project root. Default: current directory."}
        }, "required": []}
    }},
    {"type": "function", "function": {
        "name": "tech_stack_identifier",
        "description": "Identify tech stack from file extensions and framework config files.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Project root. Default: current directory."}
        }, "required": []}
    }},
    {"type": "function", "function": {
        "name": "api_surface_mapper",
        "description": "Find all API endpoint definitions in the codebase.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Project root. Default: current directory."}
        }, "required": []}
    }},
    {"type": "function", "function": {
        "name": "complexity_analyzer",
        "description": "Detect high-complexity Python functions (deep nesting, long bodies).",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Project root. Default: current directory."}
        }, "required": []}
    }},
    {"type": "function", "function": {
        "name": "pattern_detector",
        "description": "Detect anti-patterns: bare excepts, eval(), SELECT *, console.log, etc.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Project root. Default: current directory."}
        }, "required": []}
    }},
]

# ── Agent spec ───────────────────────────────────────────────────────────────

SPEC = {
    "name": "Code Analyst",
    "icon": "magnifier",
    "color": "#79c0ff",
    "description": "Analyzes existing codebase — tech stack, architecture, dependencies, problems",
    "agent_type": "analyst",

    "restricted_tools": ["edit_file", "write_file"],

    "extra_tools": _EXTRA_TOOLS,
    "extra_dispatch": {
        "dependency_scanner": _dependency_scanner,
        "tech_stack_identifier": _tech_stack_identifier,
        "api_surface_mapper": _api_surface_mapper,
        "complexity_analyzer": _complexity_analyzer,
        "pattern_detector": _pattern_detector,
    },

    "system_prompt": """You are the Code Analyst agent in a multi-agent development system.

YOUR ROLE: Perform deep analysis of the assigned codebase subtree and publish structured findings.
You are the knowledge foundation — execution agents build on your findings.

SPECIALIZED TOOLS:
- dependency_scanner(path)      — parse all package manifests
- tech_stack_identifier(path)   — identify languages + frameworks
- api_surface_mapper(path)      — find all API endpoints
- complexity_analyzer(path)     — flag complex functions
- pattern_detector(path)        — detect anti-patterns

WORKFLOW:
1. tech_stack_identifier → overview
2. dependency_scanner → dependencies
3. api_surface_mapper → public interfaces
4. pattern_detector → problems
5. read_file → deep-read key files
6. search → find patterns

RULES:
- Do NOT modify any files — analysis only
- Be thorough: missed context causes execution agents to fail
- Focus on what is relevant to the task
- When done, output a structured analysis summary as your final message""",
}
