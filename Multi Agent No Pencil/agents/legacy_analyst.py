import os
import re
import glob as _glob
import subprocess

_SKIP = {".git", "__pycache__", ".venv", "venv", "node_modules",
         ".pytest_cache", ".mypy_cache", "dist", "build", "project_context"}


def _skip(path: str) -> bool:
    return bool(set(path.replace("\\", "/").split("/")) & _SKIP)


# ── Tool implementations ──────────────────────────────────────────────────────

def _risk_assessor(path: str = ".") -> str:
    """Evaluate migration risk per module based on complexity and legacy patterns."""
    risk_signals = {
        "CRITICAL": [
            re.compile(r'stored.?procedure|exec\s*\(', re.I),
            re.compile(r'global\s+\w+.*=.*connection|db.*global', re.I),
            re.compile(r'com\s*\.\s*\w+|CreateObject\s*\(', re.I),    # COM/ActiveX
        ],
        "HIGH": [
            re.compile(r'mysql_query|mysql_connect', re.I),             # old PHP MySQL
            re.compile(r'document\.write\s*\(', re.I),                 # legacy JS
            re.compile(r'Application\s*\(|Session\s*\(', re.I),        # Classic ASP
            re.compile(r'Response\.Write|Request\.Form', re.I),        # Classic ASP
            re.compile(r'\$_GET|\$_POST|\$_REQUEST', re.I),            # old PHP superglobals
        ],
        "MEDIUM": [
            re.compile(r'jQuery|\$\s*\(', re.I),                       # jQuery
            re.compile(r'require\s*\(["\']\./', re.I),                  # CommonJS
            re.compile(r'var\s+\w+\s*=', re.I),                        # var (not let/const)
            re.compile(r'prototype\.\w+\s*=\s*function', re.I),        # prototype-based OOP
        ],
    }

    risk_map: dict = {"CRITICAL": [], "HIGH": [], "MEDIUM": []}

    for fp in _glob.glob(os.path.join(path, "**", "*"), recursive=True):
        if not os.path.isfile(fp) or _skip(fp):
            continue
        try:
            with open(fp, encoding="utf-8", errors="ignore") as f:
                content = f.read()
            rel = os.path.relpath(fp, path)
            for level, patterns in risk_signals.items():
                for pattern in patterns:
                    if pattern.search(content):
                        risk_map[level].append(rel)
                        break
        except Exception:
            pass

    lines = ["=== Migration Risk Assessment ==="]
    for level in ["CRITICAL", "HIGH", "MEDIUM"]:
        files = list(dict.fromkeys(risk_map[level]))  # dedup
        if files:
            lines.append(f"\n[{level}] — {len(files)} file(s):")
            for f in files[:20]:
                lines.append(f"  {f}")
    if not any(risk_map.values()):
        lines.append("  No high-risk legacy patterns detected")
    return "\n".join(lines)


def _data_flow_mapper(path: str = ".") -> str:
    """Trace data flows through ETL patterns, stored procedures, and batch jobs."""
    flow_patterns = [
        (re.compile(r'def\s+(extract|load|transform|etl|pipeline|batch|migrate)\w*', re.I), "ETL function"),
        (re.compile(r'cron|schedule|celery|beat|job.*queue', re.I),                         "Background job"),
        (re.compile(r'EXEC\s+\w+|CALL\s+\w+', re.I),                                       "Stored procedure call"),
        (re.compile(r'INSERT\s+INTO.*SELECT|CREATE.*AS\s+SELECT', re.I),                    "Data transformation SQL"),
        (re.compile(r'pd\.read_|DataFrame|\.to_csv|\.to_sql', re.I),                       "Pandas data pipeline"),
        (re.compile(r'kafka|rabbitmq|sqs|pubsub|event.*stream', re.I),                     "Message/event stream"),
        (re.compile(r'ftplib|paramiko|sftp|ftp.*upload|ftp.*download', re.I),              "FTP/SFTP data transfer"),
        (re.compile(r'xml\.etree|lxml|BeautifulSoup|csv\.reader', re.I),                   "Data parsing"),
    ]

    findings = []
    for fp in _glob.glob(os.path.join(path, "**", "*"), recursive=True):
        if not os.path.isfile(fp) or _skip(fp):
            continue
        try:
            with open(fp, encoding="utf-8", errors="ignore") as f:
                for lineno, line in enumerate(f, 1):
                    for pattern, label in flow_patterns:
                        if pattern.search(line):
                            rel = os.path.relpath(fp, path)
                            findings.append(f"  [{label}] {rel}:{lineno}: {line.strip()[:80]}")
                            break
        except Exception:
            pass
        if len(findings) >= 80:
            break

    return "\n".join(findings) if findings else "[No data flow patterns detected]"


def _compatibility_checker(technology: str = "") -> str:
    """Return modern equivalents for common legacy technologies."""
    equivalents = {
        "jquery":          "Modern alternatives: vanilla JS, Alpine.js, or React/Vue for complex UIs",
        "jquery ui":       "Replacement: a CSS framework (Tailwind) + headless UI library",
        "classic asp":     "Replacement: ASP.NET Core (C#) or Node.js/Express",
        "php 5":           "Upgrade: PHP 8.x — rewrite deprecated mysql_* to PDO/MySQLi",
        "mysql_*":         "Replacement: PDO or MySQLi with prepared statements",
        "vbscript":        "Replacement: JavaScript/TypeScript",
        "activex":         "Replacement: modern Web APIs (File API, WebSocket, etc.)",
        "com":             "Replacement: REST APIs or .NET Core libraries",
        "commonjs":        "Upgrade: ES Modules (import/export) + bundler (Vite/Webpack)",
        "var":             "Upgrade: use let/const — var has function scope and hoisting issues",
        "callback hell":   "Replacement: async/await with Promises",
        "prototypal":      "Replacement: ES6 classes or functional patterns",
        "cobol":           "Migration: Java/Spring or Python depending on domain",
        "fortran":         "Migration: Python (NumPy/SciPy) or Julia for scientific computing",
        "foxpro":          "Migration: PostgreSQL/SQLite with a modern ORM",
        "access mdb":      "Migration: SQLite or PostgreSQL",
        "soap":            "Replacement: REST API or GraphQL",
        "xml rpc":         "Replacement: JSON REST API",
        "struts":          "Upgrade: Spring Boot / Quarkus",
        "hibernate 3":     "Upgrade: Hibernate 6 or Spring Data JPA",
    }

    if technology:
        key = technology.lower()
        for k, v in equivalents.items():
            if k in key or key in k:
                return f"Legacy: {technology}\nModern equivalent: {v}"
        return f"[No specific guidance for '{technology}' — research current ecosystem alternatives]"

    lines = ["=== Modern equivalents for common legacy technologies ==="]
    for legacy, modern in equivalents.items():
        lines.append(f"\n  {legacy}:\n    {modern}")
    return "\n".join(lines)


def _pattern_detector_legacy(path: str = ".") -> str:
    """Detect legacy-specific patterns: God objects, stored procedure abuse, spaghetti routing."""
    patterns = [
        (re.compile(r'class\s+\w+'),                          "Class definition (check for God objects)"),
        (re.compile(r'EXEC\s*\(\s*@sql', re.I),              "Dynamic SQL exec (SQL injection risk)"),
        (re.compile(r'goto\s+\w+', re.I),                    "GOTO statement"),
        (re.compile(r'On\s+Error\s+Resume\s+Next', re.I),   "VBScript error suppression"),
        (re.compile(r'include\s*\(\s*\$', re.I),             "PHP dynamic include (LFI risk)"),
        (re.compile(r'extract\s*\(\s*\$_', re.I),            "PHP extract() from superglobal"),
        (re.compile(r'register_globals', re.I),              "register_globals (PHP security hole)"),
        (re.compile(r'magic_quotes', re.I),                  "magic_quotes (deprecated PHP)"),
    ]
    findings = []
    for fp in _glob.glob(os.path.join(path, "**", "*"), recursive=True):
        if not os.path.isfile(fp) or _skip(fp):
            continue
        try:
            with open(fp, encoding="utf-8", errors="ignore") as f:
                for lineno, line in enumerate(f, 1):
                    for pattern, label in patterns:
                        if pattern.search(line):
                            rel = os.path.relpath(fp, path)
                            findings.append(f"  [{label}] {rel}:{lineno}: {line.strip()[:80]}")
                            break
        except Exception:
            pass
        if len(findings) >= 60:
            break
    return "\n".join(findings) if findings else "[No legacy anti-patterns found]"


def _binary_inspector(path: str = ".") -> str:
    """Inspect compiled binaries, DLLs, and unknown files using available system tools."""
    import subprocess

    results = []
    binary_exts = {".dll", ".exe", ".so", ".dylib", ".class", ".jar",
                   ".pyc", ".pyd", ".bin", ".dat", ".db", ".mdb", ".accdb"}

    found_binaries = []
    for fp in _glob.glob(os.path.join(path, "**", "*"), recursive=True):
        if not os.path.isfile(fp) or _skip(fp):
            continue
        ext = os.path.splitext(fp)[1].lower()
        if ext in binary_exts:
            found_binaries.append(fp)

    if not found_binaries:
        results.append("[No binary files detected in standard extensions]")
    else:
        results.append(f"=== Binary Files Found ({len(found_binaries)}) ===")
        for fp in found_binaries[:20]:
            rel = os.path.relpath(fp, path)
            size_kb = os.path.getsize(fp) // 1024
            results.append(f"  {rel} ({size_kb} KB)")

    # Try 'file' command (Linux/macOS)
    if found_binaries:
        try:
            target = found_binaries[0]
            r = subprocess.run(["file", target], capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                results.append(f"\n=== file command output ===\n{r.stdout.strip()}")
        except (FileNotFoundError, Exception):
            pass

        # Try 'strings' command to extract readable text from binaries
        try:
            target = found_binaries[0]
            r = subprocess.run(["strings", "-n", "6", target],
                               capture_output=True, text=True, timeout=10)
            if r.returncode == 0 and r.stdout:
                lines = r.stdout.splitlines()[:30]
                results.append(f"\n=== strings output (first 30 readable strings) ===\n" +
                               "\n".join(f"  {l}" for l in lines))
        except (FileNotFoundError, Exception):
            pass

    # Check for .class / .jar (Java)
    java_binaries = [f for f in found_binaries if f.endswith((".class", ".jar"))]
    if java_binaries:
        results.append("\n=== Java Binaries Detected ===")
        results.append("  Decompile with: jadx, cfr, or fernflower")
        results.append("  jar -tf <file>.jar  — list contents of a JAR")
        for jf in java_binaries[:5]:
            try:
                r = subprocess.run(["jar", "-tf", jf], capture_output=True, text=True, timeout=10)
                if r.returncode == 0:
                    results.append(f"  JAR contents ({os.path.basename(jf)}):\n" +
                                  "\n".join(f"    {l}" for l in r.stdout.splitlines()[:15]))
            except Exception:
                pass

    # Check .pyc (Python bytecode)
    pyc_files = [f for f in found_binaries if f.endswith(".pyc")]
    if pyc_files:
        results.append("\n=== Python Bytecode (.pyc) ===")
        results.append("  Decompile with: uncompyle6 or decompile3")
        results.append("  Install: pip install uncompyle6")
        results.append(f"  Files found: {len(pyc_files)}")

    return "\n".join(results)


def _database_schema_reader(path: str = ".") -> str:
    """Read and summarize database schema definitions from SQL files and ORM models."""
    results = []

    # Find SQL schema files
    sql_files = []
    for pattern in ["*.sql", "schema*.sql", "migrations/*.sql", "**/*.sql"]:
        for fp in _glob.glob(os.path.join(path, "**", pattern), recursive=True):
            if os.path.isfile(fp) and not _skip(fp):
                sql_files.append(fp)
    sql_files = list(dict.fromkeys(sql_files))[:20]

    if sql_files:
        results.append(f"=== SQL Schema Files ({len(sql_files)}) ===")
        create_re = re.compile(
            r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`"\[]?(\w+)[`"\]]?\s*\(',
            re.IGNORECASE
        )
        col_re = re.compile(r'^\s+[`"\[]?(\w+)[`"\]]?\s+(\w+)', re.MULTILINE)
        for fp in sql_files[:10]:
            try:
                with open(fp, encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                rel = os.path.relpath(fp, path)
                tables = create_re.findall(content)
                results.append(f"\n  {rel}:")
                for table in tables[:15]:
                    results.append(f"    TABLE: {table}")
            except Exception:
                pass

    # Find Alembic migrations
    alembic_files = []
    for fp in _glob.glob(os.path.join(path, "**", "versions", "*.py"), recursive=True):
        if os.path.isfile(fp) and not _skip(fp):
            alembic_files.append(fp)
    if alembic_files:
        results.append(f"\n=== Alembic Migrations ({len(alembic_files)} files) ===")
        for fp in sorted(alembic_files)[-5:]:
            results.append(f"  {os.path.relpath(fp, path)}")

    # Find Django models
    for fp in _glob.glob(os.path.join(path, "**", "models.py"), recursive=True):
        if os.path.isfile(fp) and not _skip(fp):
            try:
                with open(fp, encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                class_re = re.compile(r'class\s+(\w+)\s*\(.*Model.*\):', re.IGNORECASE)
                field_re = re.compile(r'^\s+(\w+)\s*=\s*models\.(\w+)', re.MULTILINE)
                models = class_re.findall(content)
                if models:
                    rel = os.path.relpath(fp, path)
                    results.append(f"\n=== Django Models: {rel} ===")
                    for model in models[:15]:
                        results.append(f"  Model: {model}")
                    fields = field_re.findall(content)
                    for fname, ftype in fields[:20]:
                        results.append(f"    {fname}: {ftype}")
            except Exception:
                pass

    # Find Prisma schema
    for fp in _glob.glob(os.path.join(path, "**", "schema.prisma"), recursive=True):
        if os.path.isfile(fp):
            try:
                with open(fp, encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                rel = os.path.relpath(fp, path)
                model_re = re.compile(r'model\s+(\w+)\s*\{', re.IGNORECASE)
                models = model_re.findall(content)
                results.append(f"\n=== Prisma Schema: {rel} ===")
                for model in models:
                    results.append(f"  model {model}")
            except Exception:
                pass

    # Find .mdb / .accdb (Microsoft Access)
    access_files = [
        fp for fp in _glob.glob(os.path.join(path, "**", "*"), recursive=True)
        if os.path.isfile(fp) and fp.lower().endswith((".mdb", ".accdb"))
    ]
    if access_files:
        results.append(f"\n=== Microsoft Access Databases ({len(access_files)}) ===")
        results.append("  Cannot read binary .mdb directly without mdbtools.")
        results.append("  Install mdbtools (Linux): sudo apt install mdbtools")
        results.append("  Then: mdb-tables file.mdb | mdb-export file.mdb TableName")
        for f in access_files[:5]:
            results.append(f"  {os.path.relpath(f, path)}")

    if not results:
        return "[No database schema files found — checked: *.sql, models.py, schema.prisma, migrations/, *.mdb]"
    return "\n".join(results)


def _legacy_dependency_scanner(path: str = ".") -> str:
    """Scan legacy dependency manifests including old formats."""
    import collections

    manifests = [
        ("package.json",         "npm/Node.js"),
        ("bower.json",           "Bower (deprecated)"),
        ("requirements.txt",     "pip/Python"),
        ("Pipfile",              "pipenv"),
        ("pyproject.toml",       "poetry/Python"),
        ("go.mod",               "Go modules"),
        ("Cargo.toml",           "Rust/Cargo"),
        ("pom.xml",              "Maven/Java"),
        ("build.gradle",         "Gradle/Java"),
        ("composer.json",        "PHP Composer"),
        ("Gemfile",              "Ruby Bundler"),
        ("*.gemspec",            "Ruby gem spec"),
        ("packages.config",      ".NET (legacy NuGet)"),
        ("*.csproj",             ".NET project"),
        ("*.vbproj",             "VB.NET project"),
        ("mix.exs",              "Elixir Mix"),
        ("cpanfile",             "Perl CPAN"),
        ("conanfile.txt",        "C++ Conan"),
    ]

    results = []
    for filename, ecosystem in manifests:
        if "*" in filename:
            # glob pattern
            for fp in _glob.glob(os.path.join(path, "**", filename), recursive=True):
                if os.path.isfile(fp) and not _skip(fp):
                    try:
                        with open(fp, encoding="utf-8", errors="ignore") as f:
                            content = f.read(3000)
                        rel = os.path.relpath(fp, path)
                        results.append(f"=== {ecosystem} ({rel}) ===\n{content}")
                    except Exception as e:
                        results.append(f"=== {ecosystem} === [error: {e}]")
        else:
            fp = os.path.join(path, filename)
            if os.path.exists(fp):
                try:
                    with open(fp, encoding="utf-8", errors="ignore") as f:
                        content = f.read(3000)
                    results.append(f"=== {ecosystem} ({filename}) ===\n{content}")
                except Exception as e:
                    results.append(f"=== {ecosystem} ({filename}) === [error: {e}]")

    # Flag old/deprecated dependencies
    old_package_signals = [
        ("bower", "Bower is deprecated — migrate to npm/webpack"),
        ("grunt", "Grunt largely replaced by npm scripts or Vite"),
        ("gulp",  "Gulp largely replaced by npm scripts or Vite"),
        ("jquery", "jQuery may be unnecessary — check if vanilla JS or a framework fits"),
        ("moment", "Moment.js is legacy — migrate to day.js or date-fns"),
        ("request", "request (npm) is deprecated — use axios, got, or native fetch"),
        ("lodash", "Lodash may be partially replaceable with modern JS builtins"),
    ]

    if results:
        flagged = []
        all_content = "\n".join(results).lower()
        for pkg, note in old_package_signals:
            if pkg in all_content:
                flagged.append(f"  [LEGACY] {pkg}: {note}")
        if flagged:
            results.append("\n=== Legacy Package Warnings ===\n" + "\n".join(flagged))

    return "\n\n".join(results) if results else "[No dependency manifests found]"


# ── Tool schemas ──────────────────────────────────────────────────────────────

_EXTRA_TOOLS = [
    {
        "type": "function", "function": {
            "name": "risk_assessor",
            "description": "Evaluate migration risk per module. Returns CRITICAL/HIGH/MEDIUM risk files based on detected legacy patterns (COM/ActiveX, stored procedures, old PHP MySQL functions, jQuery, var-based JS).",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string", "description": "Project root. Default: current directory."}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "data_flow_mapper",
            "description": "Trace data flows: find ETL functions, batch jobs, stored procedure calls, data transformation SQL, Pandas pipelines, message queues, FTP transfers.",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string", "description": "Project root. Default: current directory."}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "compatibility_checker",
            "description": "Return modern equivalents for a legacy technology (jQuery, Classic ASP, PHP5 mysql_*, COBOL, SOAP, COM, etc.). Call with no arguments to get the full reference table.",
            "parameters": {"type": "object", "properties": {
                "technology": {"type": "string", "description": "Legacy technology name. Default: returns full reference table."}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "binary_inspector",
            "description": "Inspect compiled binaries, DLLs, .class/.jar files, .pyc files, and .mdb databases. Uses 'file', 'strings', and 'jar' commands where available.",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string", "description": "Project root. Default: current directory."}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "database_schema_reader",
            "description": "Read database schema from .sql files, Django models.py, Prisma schema.prisma, Alembic migrations, and .mdb/.accdb files. Returns table/model names and fields.",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string", "description": "Project root. Default: current directory."}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "legacy_dependency_scanner",
            "description": "Scan all dependency manifests including legacy formats: bower.json, packages.config, .csproj/.vbproj, cpanfile, conanfile. Also flags deprecated packages.",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string", "description": "Project root. Default: current directory."}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "pattern_detector_legacy",
            "description": "Detect legacy-specific anti-patterns: dynamic SQL exec, GOTO, VBScript error suppression, PHP register_globals, magic_quotes, dynamic includes.",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string", "description": "Project root. Default: current directory."}
            }, "required": []}
        }
    },
]

# ── Agent spec ────────────────────────────────────────────────────────────────

SPEC = {
    "name":        "Legacy Analyst",
    "icon":        "\U0001f3db\ufe0f",
    "color":       "#e3b341",
    "description": "Legacy system specialist — migration risk assessment, old technology mapping",

    "restricted_tools": ["edit_file"],   # read-only: analysis only

    "extra_tools":    _EXTRA_TOOLS,
    "extra_dispatch": {
        "risk_assessor":          _risk_assessor,
        "data_flow_mapper":       _data_flow_mapper,
        "compatibility_checker":  _compatibility_checker,
        "pattern_detector_legacy":    _pattern_detector_legacy,
        "binary_inspector":           _binary_inspector,
        "database_schema_reader":     _database_schema_reader,
        "legacy_dependency_scanner":  _legacy_dependency_scanner,
    },

    "system_prompt": """You are the Legacy Analyst agent in a multi-agent development system.

YOUR ROLE: Analyze legacy and older codebases with a focus on migration risk and modernization pathways. You specialize in systems built before modern practices.

SPECIALIZED TOOLS:
- risk_assessor(path)           — classify files by migration risk: CRITICAL/HIGH/MEDIUM
- data_flow_mapper(path)        — trace ETL, stored procedures, batch jobs, message queues
- compatibility_checker(tech)   — get modern equivalents for legacy technologies
- pattern_detector_legacy(path)      — find legacy anti-patterns (GOTO, dynamic SQL, etc.)
- binary_inspector(path)             — inspect DLLs, .class, .pyc, .mdb files
- database_schema_reader(path)       — read SQL schemas, Django models, Prisma, .mdb
- legacy_dependency_scanner(path)    — scan all dependency formats including Bower, NuGet, CPAN
- web_search(query)                  — research migration paths, find modern equivalents

ANALYSIS WORKFLOW:
1. risk_assessor → get risk map across all modules
2. pattern_detector_legacy → find specific anti-patterns
3. data_flow_mapper → understand how data moves through the system
4. compatibility_checker → for each legacy tech found, document the modern equivalent
5. read_file → deep-read the CRITICAL and HIGH risk files
6. search → find all references to critical business logic

RULES:
- Do NOT make any changes — analysis only (edit_file is disabled)
- Never underestimate risk — over-flagging is better than missing a hidden dependency
- Flag anything that could cause data loss during migration as CRITICAL

OUTPUT: Write your Legacy Analysis Report to project_context/legacy_analysis_report.md
Sections: ## Technology Inventory, ## Risk Matrix (CRITICAL/HIGH/MEDIUM/LOW), ## Business Logic Map, ## Data Flow, ## Migration Strategy Recommendation"""
}
