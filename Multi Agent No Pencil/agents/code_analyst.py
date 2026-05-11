import os
import re
import glob as _glob
import collections
import subprocess

_SKIP = {".git", "__pycache__", ".venv", "venv", "node_modules",
         ".pytest_cache", ".mypy_cache", "dist", "build", "project_context"}


def _skip(path: str) -> bool:
    return bool(set(path.replace("\\", "/").split("/")) & _SKIP)


# ── Tool implementations ──────────────────────────────────────────────────────

def _dependency_scanner(path: str = ".") -> str:
    """Scan all dependency manifests and return their contents."""
    manifests = [
        ("package.json",       "npm/Node.js"),
        ("requirements.txt",   "pip/Python"),
        ("Pipfile",            "pipenv"),
        ("pyproject.toml",     "poetry/Python"),
        ("go.mod",             "Go modules"),
        ("Cargo.toml",         "Rust/Cargo"),
        ("pom.xml",            "Maven/Java"),
        ("build.gradle",       "Gradle/Java"),
        ("composer.json",      "PHP Composer"),
        ("Gemfile",            "Ruby Bundler"),
        ("mix.exs",            "Elixir Mix"),
        ("Package.swift",      "Swift SPM"),
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

    locks = ["package-lock.json", "yarn.lock", "pnpm-lock.yaml",
             "poetry.lock", "Cargo.lock", "go.sum"]
    found_locks = [lf for lf in locks if os.path.exists(os.path.join(path, lf))]
    if found_locks:
        results.append("=== Lock files present ===\n" + "\n".join(found_locks))

    return "\n\n".join(results) if results else "[No dependency manifests found]"


def _tech_stack_identifier(path: str = ".") -> str:
    """Identify languages, frameworks, and tools from file extensions and config files."""
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
        ".rb": "Ruby", ".php": "PHP", ".cs": "C#", ".cpp": "C++", ".c": "C",
        ".swift": "Swift", ".kt": "Kotlin", ".dart": "Dart/Flutter",
        ".ex": "Elixir", ".hs": "Haskell", ".scala": "Scala",
        ".html": "HTML", ".css": "CSS", ".scss": "SCSS",
        ".sql": "SQL", ".tf": "Terraform", ".yaml": "YAML",
    }

    lines = ["=== Language distribution (by file count) ==="]
    for ext, count in ext_counts.most_common(20):
        lang = lang_map.get(ext, ext)
        lines.append(f"  {lang} ({ext}): {count} files")

    framework_signals = {
        "next.config.js": "Next.js", "next.config.ts": "Next.js",
        "nuxt.config.ts": "Nuxt.js", "vite.config.ts": "Vite",
        "vite.config.js": "Vite", "angular.json": "Angular",
        "svelte.config.js": "SvelteKit", "remix.config.js": "Remix",
        "manage.py": "Django", "wsgi.py": "WSGI/Django",
        "asgi.py": "ASGI/FastAPI", "main.go": "Go binary",
        "Cargo.toml": "Rust/Cargo", "docker-compose.yml": "Docker Compose",
        "docker-compose.yaml": "Docker Compose",
        "tailwind.config.js": "Tailwind CSS",
        "prisma/schema.prisma": "Prisma ORM",
        ".eslintrc.js": "ESLint", ".eslintrc.json": "ESLint",
        "jest.config.js": "Jest", "vitest.config.ts": "Vitest",
        "playwright.config.ts": "Playwright",
    }
    found = list(dict.fromkeys(
        fw for sig, fw in framework_signals.items()
        if os.path.exists(os.path.join(path, sig))
    ))
    if found:
        lines.append("\n=== Detected frameworks / tools ===")
        for fw in found:
            lines.append(f"  \u2713 {fw}")

    return "\n".join(lines)


def _api_surface_mapper(path: str = ".") -> str:
    """Scan source files to find all public API endpoint definitions."""
    patterns = [
        (r'@app\.(get|post|put|delete|patch|options)\s*\(["\']([^"\']+)', "FastAPI/Flask", 2),
        (r'router\.(get|post|put|delete|patch)\s*\(["\']([^"\']+)',        "Express",      2),
        (r'@(Get|Post|Put|Delete|Patch)\s*\(["\']([^"\']+)',              "NestJS/Spring", 2),
        (r'path\s*\(["\']([^"\']+)["\']',                                 "Django URL",    1),
        (r'Route::(get|post|put|delete|any)\s*\(["\']([^"\']+)',          "Laravel",       2),
        (r'app\.(get|post|put|delete|patch)\s*\(["\']([^"\']+)',          "Express app",   2),
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
                            method = m.group(1).upper() if group == 2 and len(m.groups()) >= 2 else "ROUTE"
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


def _dead_code_finder(path: str = ".") -> str:
    """Find dead code: TODO/FIXME markers and suspiciously large files."""
    marker_re = re.compile(
        r'#\s*(TODO|FIXME|HACK|XXX|DEPRECATED|REMOVE|DEAD\s+CODE|UNUSED)',
        re.IGNORECASE
    )
    todos, large_files = [], []

    for fp in _glob.glob(os.path.join(path, "**", "*"), recursive=True):
        if not os.path.isfile(fp) or _skip(fp):
            continue
        try:
            with open(fp, encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            for lineno, line in enumerate(lines, 1):
                if marker_re.search(line):
                    rel = os.path.relpath(fp, path)
                    todos.append(f"  {rel}:{lineno}: {line.strip()}")
                    if len(todos) >= 40:
                        break
            size = os.path.getsize(fp)
            if size > 40_000 and os.path.splitext(fp)[1] in {".py", ".js", ".ts"}:
                rel = os.path.relpath(fp, path)
                large_files.append(f"  {rel}: {len(lines)} lines ({size // 1024} KB)")
        except Exception:
            pass

    results = []
    if todos:
        results.append("=== TODO/FIXME/DEPRECATED markers ===\n" + "\n".join(todos))
    if large_files:
        results.append("=== Suspiciously large files ===\n" + "\n".join(large_files))
    return "\n\n".join(results) if results else "[No dead code markers found]"


def _complexity_analyzer(path: str = ".") -> str:
    """Flag high-complexity Python functions: deep nesting or long bodies."""
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
                            findings.append(f"  {rel}:{func_start+1} {func_name}() — {body} lines (too long)")
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


def _call_graph_builder(path: str = ".", entry_file: str = "") -> str:
    """Trace Python module import relationships to produce a dependency map."""
    import_re = re.compile(r'^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.,\s]+))')
    graph: dict = {}

    files = _glob.glob(os.path.join(path, "**", "*.py"), recursive=True)
    if entry_file:
        files = [f for f in files if entry_file in f] + \
                [f for f in files if entry_file not in f]

    for fp in files[:60]:
        if _skip(fp):
            continue
        try:
            rel = os.path.relpath(fp, path)
            imports = []
            with open(fp, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    m = import_re.match(line)
                    if m:
                        mod = (m.group(1) or m.group(2) or "").strip().split(",")[0].strip()
                        if mod:
                            imports.append(mod)
            if imports:
                graph[rel] = imports
        except Exception:
            pass

    if not graph:
        return "[No Python import relationships found]"
    lines = ["=== Module import graph ==="]
    for mod, deps in list(graph.items())[:50]:
        lines.append(f"  {mod}")
        for dep in deps[:8]:
            lines.append(f"    \u2514\u2500 {dep}")
    return "\n".join(lines)


def _pattern_detector(path: str = ".") -> str:
    """Detect common anti-patterns and code smells."""
    smell_re_list = [
        (re.compile(r'except\s*:'),                          "Bare except clause",           {".py"}),
        (re.compile(r'\beval\s*\('),                         "Use of eval()",                {".py", ".js", ".ts"}),
        (re.compile(r'print.*password', re.I),               "Potential password logging",   {".py"}),
        (re.compile(r'SELECT\s+\*\s+FROM', re.I),            "SELECT * (over-fetching)",     {".py", ".js", ".ts", ".php", ".rb"}),
        (re.compile(r'time\.sleep\(\d+\)'),                  "Blocking sleep in code",       {".py"}),
        (re.compile(r'TODO.*auth|auth.*TODO', re.I),         "Unfinished auth code",         {".py", ".js", ".ts"}),
        (re.compile(r'pass\s*$'),                            "Empty except/pass block",      {".py"}),
        (re.compile(r'global\s+\w+'),                        "Global variable usage",        {".py"}),
        (re.compile(r'console\.log\(', re.I),                "console.log in source",        {".js", ".ts"}),
        (re.compile(r'debugger;'),                           "debugger statement",           {".js", ".ts"}),
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


# ── Tool schemas ──────────────────────────────────────────────────────────────

_EXTRA_TOOLS = [
    {
        "type": "function", "function": {
            "name": "dependency_scanner",
            "description": "Parse all dependency manifests (package.json, requirements.txt, go.mod, Cargo.toml, pom.xml, etc.) and return their contents and ecosystems.",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string", "description": "Project root. Default: current directory."}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "tech_stack_identifier",
            "description": "Identify the tech stack from file extensions and known framework config files. Returns language distribution and detected frameworks.",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string", "description": "Project root. Default: current directory."}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "api_surface_mapper",
            "description": "Scan source files for public API endpoint definitions: FastAPI/Flask routes, Express routes, Django URLs, Laravel routes.",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string", "description": "Project root. Default: current directory."}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "dead_code_finder",
            "description": "Find dead code signals: TODO/FIXME/DEPRECATED markers and suspiciously large source files.",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string", "description": "Project root. Default: current directory."}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "complexity_analyzer",
            "description": "Detect high-complexity Python functions: deeply nested code (>= 5 levels) and very long function bodies (> 60 lines).",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string", "description": "Project root. Default: current directory."}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "call_graph_builder",
            "description": "Trace Python module import relationships to build a module dependency graph.",
            "parameters": {"type": "object", "properties": {
                "path":       {"type": "string", "description": "Project root. Default: current directory."},
                "entry_file": {"type": "string", "description": "Optional filename to prioritize as entry point."}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "pattern_detector",
            "description": "Detect anti-patterns and code smells: bare excepts, eval(), SELECT *, blocking sleep, password logging, global variables.",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string", "description": "Project root. Default: current directory."}
            }, "required": []}
        }
    },
]

# ── Agent spec ────────────────────────────────────────────────────────────────

SPEC = {
    "name":        "Code Analyst",
    "icon":        "\U0001f50d",
    "color":       "#79c0ff",
    "description": "Analyzes existing codebase — tech stack, architecture, dependencies, problems",

    "restricted_tools": ["edit_file"],   # read-only: analysis only

    "extra_tools":    _EXTRA_TOOLS,
    "extra_dispatch": {
        "dependency_scanner":    _dependency_scanner,
        "tech_stack_identifier": _tech_stack_identifier,
        "api_surface_mapper":    _api_surface_mapper,
        "dead_code_finder":      _dead_code_finder,
        "complexity_analyzer":   _complexity_analyzer,
        "call_graph_builder":    _call_graph_builder,
        "pattern_detector":      _pattern_detector,
    },

    "system_prompt": """You are the Code Analyst agent in a multi-agent development system.

YOUR ROLE: Perform a deep analysis of the existing codebase and produce a structured Analysis Report. You are the knowledge foundation — everything execution agents build will be informed by your findings.

SPECIALIZED TOOLS (use these before read_file for bulk analysis):
- dependency_scanner(path)      — parse all package manifests
- tech_stack_identifier(path)   — identify languages + frameworks
- api_surface_mapper(path)      — find all API endpoints
- dead_code_finder(path)        — locate TODO/FIXME and large files
- complexity_analyzer(path)     — flag complex functions
- call_graph_builder(path)      — trace module imports
- pattern_detector(path)        — detect anti-patterns and code smells

ANALYSIS WORKFLOW:
1. tech_stack_identifier → language/framework overview
2. dependency_scanner → understand all dependencies
3. call_graph_builder → understand module structure
4. api_surface_mapper → map all public interfaces
5. pattern_detector + dead_code_finder → find problems
6. complexity_analyzer → flag high-risk functions
7. read_file → deep-read specific files that need more detail
8. search → find patterns across the codebase

RULES:
- Do NOT modify any files — analysis only (edit_file is disabled)
- Be thorough: missed dependencies cause execution agents to fail
- Focus on what is relevant to the assigned task

OUTPUT: Write Analysis Report to project_context/analysis_report.md
Sections: ## Tech Stack, ## Architecture, ## Key Files, ## Dependencies, ## Problems, ## Integration Points, ## Task Notes"""
}
