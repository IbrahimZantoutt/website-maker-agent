import os
import re
import glob as _glob
import subprocess

_SKIP = {".git", "__pycache__", ".venv", "venv", "node_modules",
         ".pytest_cache", ".mypy_cache", "dist", "build", "project_context"}


def _skip(path: str) -> bool:
    return bool(set(path.replace("\\", "/").split("/")) & _SKIP)


# ── Tool implementations ──────────────────────────────────────────────────────

def _secret_scanner(path: str = ".") -> str:
    """Grep source files for common secret/credential patterns."""
    patterns = [
        (r'(?i)(api[_-]?key|apikey)\s*[:=]\s*["\'][A-Za-z0-9_\-]{16,}["\']',    "API Key"),
        (r'(?i)(secret|token|password|passwd|pwd)\s*[:=]\s*["\'][^"\']{8,}["\']', "Secret/Password"),
        (r'(?i)aws_access_key_id\s*[:=]\s*["\'][A-Z0-9]{20}["\']',               "AWS Access Key"),
        (r'(?i)aws_secret_access_key\s*[:=]\s*["\'][A-Za-z0-9/+=]{40}["\']',     "AWS Secret Key"),
        (r'(?i)private[_-]key\s*[:=]\s*["\'][^"\']{20,}["\']',                   "Private Key"),
        (r'-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----',                       "PEM Private Key"),
        (r'(?i)(database_url|db_url|connection_string)\s*[:=]\s*["\'][^"\']{10,}["\']', "Database URL"),
        (r'(?i)bearer\s+[A-Za-z0-9\-._~+/]+=*',                                  "Bearer Token"),
        (r'ghp_[A-Za-z0-9]{36}',                                                  "GitHub PAT"),
        (r'sk-[A-Za-z0-9]{48}',                                                   "OpenAI API Key"),
    ]

    findings = []
    text_exts = {".py", ".js", ".ts", ".env", ".yml", ".yaml", ".json",
                 ".rb", ".php", ".go", ".rs", ".java", ".cs", ".sh", ".tf"}

    for fp in _glob.glob(os.path.join(path, "**", "*"), recursive=True):
        if not os.path.isfile(fp) or _skip(fp):
            continue
        if os.path.splitext(fp)[1].lower() not in text_exts:
            continue
        # Never scan .env.example, .env.sample (they're expected to have placeholders)
        if os.path.basename(fp) in {".env.example", ".env.sample", ".env.template"}:
            continue
        try:
            with open(fp, encoding="utf-8", errors="ignore") as f:
                for lineno, line in enumerate(f, 1):
                    for pattern, label in patterns:
                        if re.search(pattern, line):
                            rel = os.path.relpath(fp, path)
                            # Redact the actual value in output
                            redacted = re.sub(r'["\'][^"\']{8,}["\']', '"[REDACTED]"', line.strip())
                            findings.append(
                                f"  [CRITICAL] {label} — {rel}:{lineno}\n    {redacted[:120]}"
                            )
                            break
        except Exception:
            pass
        if len(findings) >= 50:
            break

    if not findings:
        return "[No hardcoded secrets detected in source files]"
    return (
        f"SECRETS FOUND — {len(findings)} potential hardcoded secret(s):\n\n"
        + "\n".join(findings)
    )


def _dependency_vulnerability_scanner(path: str = ".") -> str:
    """Run npm audit or pip-audit to check for known CVEs in dependencies."""
    results = []

    # npm audit
    if os.path.exists(os.path.join(path, "package.json")):
        try:
            r = subprocess.run(
                "npm audit --json", shell=True, capture_output=True, text=True,
                timeout=60, cwd=path
            )
            output = r.stdout or r.stderr
            try:
                import json
                data = json.loads(output)
                vulns = data.get("metadata", {}).get("vulnerabilities", {})
                total = sum(vulns.values()) if vulns else "?"
                results.append(
                    f"=== npm audit ===\n"
                    f"Vulnerabilities: {vulns}\n"
                    f"Total: {total}\n"
                    f"(Run 'npm audit' for full details)"
                )
            except Exception:
                results.append(f"=== npm audit ===\n{output[:2000]}")
        except Exception as e:
            results.append(f"=== npm audit ===\n[Error running npm audit: {e}]")

    # pip-audit
    if os.path.exists(os.path.join(path, "requirements.txt")) or \
       os.path.exists(os.path.join(path, "pyproject.toml")):
        try:
            r = subprocess.run(
                "pip-audit --format=columns 2>&1",
                shell=True, capture_output=True, text=True, timeout=60, cwd=path
            )
            output = (r.stdout + r.stderr).strip()
            results.append(f"=== pip-audit ===\n{output[:2000]}")
        except Exception:
            # Fallback: try pip check
            try:
                r = subprocess.run(
                    "pip check", shell=True, capture_output=True, text=True, timeout=30
                )
                results.append(f"=== pip check ===\n{(r.stdout + r.stderr).strip()[:1000]}")
            except Exception as e:
                results.append(f"=== pip-audit ===\n[Not installed. Install with: pip install pip-audit]")

    if not results:
        return "[No package manifests found to audit]"
    return "\n\n".join(results)


def _sast_runner(path: str = ".") -> str:
    """Run SAST scanners: Bandit (Python) and Semgrep (multi-language) if available."""
    results = []

    # Bandit — Python SAST
    has_py = any(
        os.path.splitext(fp)[1] == ".py"
        for fp in _glob.glob(os.path.join(path, "**", "*.py"), recursive=True)
        if not _skip(fp)
    )
    if has_py:
        try:
            r = subprocess.run(
                f"bandit -r {path} -f txt --exclude .venv,venv,node_modules 2>&1",
                shell=True, capture_output=True, text=True, timeout=90, cwd=path
            )
            output = (r.stdout + r.stderr).strip()
            if output:
                results.append(f"=== Bandit (Python SAST) ===\n{output[:4000]}")
            else:
                results.append("=== Bandit ===\n[No output — bandit may not be installed. Run: pip install bandit]")
        except Exception as e:
            results.append(f"=== Bandit ===\n[Error: {e}. Install: pip install bandit]")

    # Semgrep — multi-language
    try:
        r = subprocess.run(
            f"semgrep --config=auto {path} --text --no-git-ignore 2>&1",
            shell=True, capture_output=True, text=True, timeout=120, cwd=path
        )
        output = (r.stdout + r.stderr).strip()
        if "No files were scanned" not in output and output:
            results.append(f"=== Semgrep ===\n{output[:4000]}")
        else:
            results.append("=== Semgrep ===\n[Not found or no files matched. Install: pip install semgrep]")
    except Exception as e:
        results.append(f"=== Semgrep ===\n[Error: {e}]")

    return "\n\n".join(results) if results else "[No SAST tools ran. Install: pip install bandit semgrep]"


def _injection_detector(path: str = ".") -> str:
    """Scan for common injection vulnerability patterns."""
    patterns = [
        (r'f["\'].*SELECT.*\{',                               "SQL Injection (f-string in query)", {".py"}),
        (r'["\']SELECT.*["\' ]\s*\+',                         "SQL Injection (string concat)",     {".py", ".js", ".php"}),
        (r'cursor\.execute\s*\([^,)]*%[^,)]*%',              "SQL Injection (%-format in execute)", {".py"}),
        (r'innerHTML\s*=',                                     "XSS (innerHTML assignment)",         {".js", ".ts"}),
        (r'document\.write\s*\(',                             "XSS (document.write)",               {".js"}),
        (r'eval\s*\(',                                         "Code Injection (eval)",              {".js", ".ts", ".py"}),
        (r'subprocess\.call\s*\(.*\+',                       "Command Injection (concat in subprocess)", {".py"}),
        (r'os\.system\s*\(.*\+',                              "Command Injection (concat in os.system)", {".py"}),
        (r'shell=True.*user|user.*shell=True',               "Command Injection (shell=True with user data)", {".py"}),
        (r'(?i)redirect\s*\(\s*request\.',                   "Open Redirect (unvalidated redirect)", {".py", ".js"}),
        (r'(?i)send_file\s*\(\s*request\.',                  "Path Traversal (user-controlled path)", {".py"}),
        (r'__import__\s*\(',                                  "Dynamic Import (potential injection)", {".py"}),
    ]

    findings = []
    for fp in _glob.glob(os.path.join(path, "**", "*"), recursive=True):
        if not os.path.isfile(fp) or _skip(fp):
            continue
        ext = os.path.splitext(fp)[1].lower()
        try:
            with open(fp, encoding="utf-8", errors="ignore") as f:
                for lineno, line in enumerate(f, 1):
                    for pattern, label, exts in patterns:
                        if ext in exts and re.search(pattern, line, re.IGNORECASE):
                            rel = os.path.relpath(fp, path)
                            findings.append(
                                f"  [HIGH] {label}\n"
                                f"    {rel}:{lineno}: {line.strip()[:100]}"
                            )
                            break
        except Exception:
            pass
        if len(findings) >= 60:
            break

    if not findings:
        return "[No obvious injection patterns detected]"
    return (
        f"Injection patterns found — {len(findings)} potential issue(s):\n\n"
        + "\n".join(findings)
        + "\n\nNOTE: Review each finding in context — some may be false positives."
    )


def _auth_auditor(path: str = ".") -> str:
    """Check authentication implementation for common OWASP weaknesses."""
    issues = []

    auth_files = []
    for pattern in ["*auth*", "*login*", "*jwt*", "*session*", "*token*", "*oauth*"]:
        for fp in _glob.glob(os.path.join(path, "**", pattern), recursive=True):
            if os.path.isfile(fp) and not _skip(fp):
                auth_files.append(fp)

    if not auth_files:
        issues.append("  [INFO] No auth-related files detected by filename pattern")

    checks = [
        (re.compile(r'(?i)md5\s*\(|hashlib\.md5'),     "[HIGH] MD5 used (weak hashing — use bcrypt/argon2)"),
        (re.compile(r'(?i)sha1\s*\(|hashlib\.sha1'),   "[HIGH] SHA1 used for password (weak — use bcrypt/argon2)"),
        (re.compile(r'(?i)jwt\.decode.*verify.*false', re.I), "[CRITICAL] JWT signature verification disabled"),
        (re.compile(r'(?i)secret\s*=\s*["\']secret["\']|secret\s*=\s*["\']password["\']'), "[CRITICAL] Trivially weak JWT secret"),
        (re.compile(r'(?i)@login_required|@auth\.required|authenticate'),    "[INFO] Auth decorator present"),
        (re.compile(r'(?i)rate.?limit|throttle'),      "[INFO] Rate limiting found"),
        (re.compile(r'(?i)bcrypt|argon2|pbkdf2'),      "[INFO] Strong password hashing in use"),
        (re.compile(r'(?i)csrf'),                       "[INFO] CSRF protection referenced"),
    ]

    for fp in auth_files[:20]:
        try:
            with open(fp, encoding="utf-8", errors="ignore") as f:
                content = f.read()
            rel = os.path.relpath(fp, path)
            for pattern, label in checks:
                if pattern.search(content):
                    issues.append(f"  {label} — {rel}")
        except Exception:
            pass

    return "\n".join(issues) if issues else "[Auth audit: no auth files found for inspection]"


def _csp_analyzer(path: str = ".") -> str:
    """Check for Content Security Policy and other security headers."""
    header_patterns = {
        "Content-Security-Policy":    re.compile(r'content.security.policy', re.I),
        "HSTS":                       re.compile(r'strict.transport.security', re.I),
        "X-Frame-Options":            re.compile(r'x.frame.options', re.I),
        "X-Content-Type-Options":     re.compile(r'x.content.type.options', re.I),
        "Referrer-Policy":            re.compile(r'referrer.policy', re.I),
        "Permissions-Policy":         re.compile(r'permissions.policy', re.I),
    }

    found_headers: set = set()
    for fp in _glob.glob(os.path.join(path, "**", "*"), recursive=True):
        if not os.path.isfile(fp) or _skip(fp):
            continue
        try:
            with open(fp, encoding="utf-8", errors="ignore") as f:
                content = f.read()
            for header, pattern in header_patterns.items():
                if pattern.search(content):
                    found_headers.add(header)
        except Exception:
            pass

    lines = ["=== Security Headers Analysis ==="]
    for header in header_patterns:
        status = "\u2713 Found" if header in found_headers else "\u2717 MISSING"
        lines.append(f"  {status}: {header}")

    if len(found_headers) < 3:
        lines.append("\n[RECOMMENDATION] Add missing security headers to your HTTP server/middleware")
        lines.append("  FastAPI: use starlette middleware or SecurityHeaders library")
        lines.append("  Express: use the 'helmet' package")
        lines.append("  Nginx: add headers in server block")

    return "\n".join(lines)


def _permission_auditor(path: str = ".") -> str:
    """Audit authorization and access control: CORS, missing auth guards, admin exposure, RBAC issues."""
    issues = []
    infos  = []

    # ── CORS checks ────────────────────────────────────────────────────────────
    cors_patterns = [
        (re.compile(r'(?i)(allow.?origin|Access-Control-Allow-Origin)\s*[:=]\s*["\']?\*'),
         "[HIGH] CORS wildcard (*) — allows any origin to access the API"),
        (re.compile(r'(?i)cors.*allow_credentials.*true|allow_credentials.*true.*cors', re.DOTALL),
         "[CRITICAL] CORS wildcard with allow_credentials=True — credential theft risk"),
        (re.compile(r'(?i)CORSMiddleware|cors.*origins\s*=\s*\['),
         "[INFO] CORS middleware configured"),
    ]

    # ── Authorization guard checks ──────────────────────────────────────────────
    auth_guard_patterns = [
        (re.compile(r'(?i)@(app|router)\.(get|post|put|delete|patch)\s*\('),
         "route"),
        (re.compile(r'(?i)@login_required|Depends\s*\(\s*get_current_user|require_auth|@auth\.'),
         "guard"),
    ]

    # ── Admin endpoint exposure ─────────────────────────────────────────────────
    admin_patterns = [
        re.compile(r'(?i)/(admin|dashboard|management|internal|debug|console|actuator)'),
    ]

    # ── RBAC / role check patterns ──────────────────────────────────────────────
    rbac_patterns = [
        (re.compile(r'(?i)(role|permission|scope)\s*[:=]'),   "[INFO] Role/permission check found"),
        (re.compile(r'(?i)is_admin|is_superuser|is_staff'),   "[INFO] Admin privilege check found"),
        (re.compile(r'(?i)Security\s*\(\s*scopes'),           "[INFO] OAuth scope enforcement found"),
    ]

    text_exts = {".py", ".js", ".ts", ".yml", ".yaml", ".json", ".env", ".conf", ".nginx"}

    route_lines    = []  # (file, lineno, line)
    guard_files    = set()
    admin_exposure = []

    for fp in _glob.glob(os.path.join(path, "**", "*"), recursive=True):
        if not os.path.isfile(fp) or _skip(fp):
            continue
        ext = os.path.splitext(fp)[1].lower()
        if ext not in text_exts:
            continue
        try:
            with open(fp, encoding="utf-8", errors="ignore") as f:
                content = f.read()
                lines   = content.splitlines()
            rel = os.path.relpath(fp, path)

            # CORS
            for pattern, label in cors_patterns:
                if pattern.search(content):
                    if "[INFO]" in label:
                        infos.append(f"  {label} — {rel}")
                    else:
                        issues.append(f"  {label} — {rel}")

            # Route vs guard detection
            for lineno, line in enumerate(lines, 1):
                if auth_guard_patterns[0][0].search(line):
                    route_lines.append((rel, lineno, line.strip()))
                if auth_guard_patterns[1][0].search(line):
                    guard_files.add(rel)

            # Admin exposure
            for lineno, line in enumerate(lines, 1):
                for pat in admin_patterns:
                    if pat.search(line) and ("@" in line or "path" in line.lower() or "route" in line.lower()):
                        admin_exposure.append(f"    {rel}:{lineno}: {line.strip()[:100]}")

            # RBAC
            for pattern, label in rbac_patterns:
                if pattern.search(content):
                    infos.append(f"  {label} — {rel}")

        except Exception:
            pass

    # Assess unguarded routes
    guarded_files = len(guard_files)
    total_routes  = len(route_lines)
    if total_routes > 0 and guarded_files == 0:
        issues.append(
            f"  [HIGH] {total_routes} route(s) found but NO auth guard imports detected — "
            f"possible missing authorization"
        )
    elif total_routes > 0:
        infos.append(
            f"  [INFO] {total_routes} route(s) scanned; auth guards found in: {', '.join(sorted(guard_files))}"
        )

    if admin_exposure:
        issues.append(
            f"  [MEDIUM] Admin/internal endpoints detected — ensure they require elevated privileges:\n"
            + "\n".join(admin_exposure[:10])
        )

    # File-system permissions for sensitive files (Unix-style check where available)
    sensitive_files = [".env", "secrets.json", "credentials.json", "private_key.pem",
                       "id_rsa", "id_ed25519", ".htpasswd"]
    for name in sensitive_files:
        for fp in _glob.glob(os.path.join(path, "**", name), recursive=True):
            if os.path.isfile(fp):
                try:
                    mode  = oct(os.stat(fp).st_mode)[-3:]
                    rel   = os.path.relpath(fp, path)
                    if mode not in {"600", "400"}:
                        issues.append(f"  [HIGH] Sensitive file with permissive permissions ({mode}) — {rel}  (should be 600)")
                    else:
                        infos.append(f"  [INFO] Sensitive file has correct permissions ({mode}) — {rel}")
                except Exception:
                    pass

    out = ["=== Permission & Authorization Audit ===\n"]
    if issues:
        out.append(f"ISSUES FOUND ({len(issues)}):")
        out.extend(issues)
    else:
        out.append("[OK] No critical authorization issues detected by automated scan")

    if infos:
        out.append("\nINFO / Positive signals:")
        out.extend(infos)

    out.append(
        "\nMANUAL CHECKLIST:\n"
        "  [ ] Every API route that modifies state requires authentication\n"
        "  [ ] Admin endpoints restricted to admin role only\n"
        "  [ ] CORS origins are an explicit allowlist (not *)\n"
        "  [ ] Sensitive file permissions are 600 or 400\n"
        "  [ ] JWT/session tokens validated on every protected request\n"
        "  [ ] Principle of least privilege applied to DB user credentials"
    )

    return "\n".join(out)


# ── Tool schemas ──────────────────────────────────────────────────────────────

_EXTRA_TOOLS = [
    {
        "type": "function", "function": {
            "name": "secret_scanner",
            "description": "Scan all source files for hardcoded secrets, API keys, passwords, tokens, and credentials. Reports file and line number.",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string", "description": "Project root. Default: current directory."}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "dependency_vulnerability_scanner",
            "description": "Run npm audit and/or pip-audit to check all dependencies for known CVEs.",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string", "description": "Project root. Default: current directory."}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "sast_runner",
            "description": "Run SAST tools: Bandit for Python, Semgrep for multi-language. Returns findings with severity and location.",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string", "description": "Project root. Default: current directory."}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "injection_detector",
            "description": "Scan for injection vulnerabilities: SQL injection, XSS (innerHTML), command injection, path traversal, open redirect patterns.",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string", "description": "Project root. Default: current directory."}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "auth_auditor",
            "description": "Audit authentication implementation: check for weak hashing (MD5/SHA1), disabled JWT verification, trivial secrets, missing CSRF protection.",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string", "description": "Project root. Default: current directory."}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "csp_analyzer",
            "description": "Check for presence of HTTP security headers: CSP, HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy.",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string", "description": "Project root. Default: current directory."}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "permission_auditor",
            "description": "Audit authorization and access control: CORS wildcard detection, unguarded API routes, admin endpoint exposure, RBAC patterns, and sensitive file permissions.",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string", "description": "Project root. Default: current directory."}
            }, "required": []}
        }
    },
]

# ── Agent spec ────────────────────────────────────────────────────────────────

SPEC = {
    "name":        "Security Agent",
    "icon":        "\U0001f6e1\ufe0f",
    "color":       "#ff7b72",
    "description": "Security auditing, vulnerability detection, OWASP Top 10, hardening",

    # Audit only — no code modifications
    "restricted_tools": ["edit_file"],

    "extra_tools":    _EXTRA_TOOLS,
    "extra_dispatch": {
        "secret_scanner":                   _secret_scanner,
        "dependency_vulnerability_scanner": _dependency_vulnerability_scanner,
        "sast_runner":                      _sast_runner,
        "injection_detector":               _injection_detector,
        "auth_auditor":                     _auth_auditor,
        "csp_analyzer":                     _csp_analyzer,
        "permission_auditor":               _permission_auditor,
    },

    "system_prompt": """You are the Security Agent in a multi-agent development system.

YOUR ROLE: Audit all new and modified code for security vulnerabilities. You are the final gate before the task is considered complete.

SPECIALIZED TOOLS AVAILABLE TO YOU:
- secret_scanner(path)                    — find hardcoded secrets and credentials
- dependency_vulnerability_scanner(path)  — run npm audit / pip-audit for CVEs
- sast_runner(path)                       — run Bandit and Semgrep
- injection_detector(path)                — detect SQL injection, XSS, command injection
- auth_auditor(path)                      — check auth implementation weaknesses
- csp_analyzer(path)                      — check security headers
- permission_auditor(path)                — audit CORS, unguarded routes, admin exposure, RBAC, file permissions
- web_search(query)                       — search for CVE details, security advisories, and OWASP guidance

AUDIT CHECKLIST (run in this order):
1. secret_scanner — check for hardcoded credentials first
2. dependency_vulnerability_scanner — known CVEs in dependencies
3. injection_detector — injection attack surfaces
4. auth_auditor — authentication weaknesses
5. permission_auditor — authorization, CORS, and access control gaps
6. csp_analyzer — missing security headers
7. sast_runner — run automated SAST tools
8. Use web_search to look up any CVE IDs or unfamiliar vulnerability patterns
9. Use read_file for manual review of any suspicious files flagged above

SEVERITY LEVELS:
- Critical: Actively exploitable, immediate breach risk
- High: Significant attack surface under normal conditions
- Medium: Exploitable under specific conditions
- Low: Defense-in-depth best practice

RULES:
- Do NOT make any code changes — audit only (edit_file is disabled for you)
- Any Critical finding = overall status FAIL, no exceptions
- Provide specific file:line references for every finding

OUTPUT:
Write your Security Report to project_context/security_report.md using write_file.
MANDATORY: First line of report must be either: status: PASS or status: FAIL
Then: findings ranked by severity, fix recommendations, tool scan summaries."""
}
