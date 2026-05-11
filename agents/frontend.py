"""
Frontend Agent — UI, components, styling, state, routing.
"""
import os
import re
import glob as _glob

_SKIP = {
    ".git", "__pycache__", ".venv", "venv", "node_modules",
    ".pytest_cache", "dist", "build", "project_context",
}


def _skip(path: str) -> bool:
    return bool(set(path.replace("\\", "/").split("/")) & _SKIP)


# ── Tool implementations ─────────────────────────────────────────────────────


def _css_analyzer(path: str = ".") -> str:
    results = []
    high_spec = re.compile(r'(#\w+\s+){2,}|(\.\w+\s+){4,}|!important')
    css_var = re.compile(r'--[\w-]+\s*:')
    used_var = re.compile(r'var\s*\(\s*--[\w-]+')

    all_vars, used_vars = set(), set()
    high_spec_findings = []

    for ext in ("*.css", "*.scss", "*.less"):
        for fp in _glob.glob(os.path.join(path, "**", ext), recursive=True):
            if _skip(fp) or not os.path.isfile(fp):
                continue
            try:
                with open(fp, encoding="utf-8", errors="ignore") as f:
                    for lineno, line in enumerate(f, 1):
                        if high_spec.search(line):
                            rel = os.path.relpath(fp, path)
                            high_spec_findings.append(f"  {rel}:{lineno}: {line.strip()[:80]}")
                        for m in css_var.finditer(line):
                            all_vars.add(m.group().strip(": "))
                        for m in used_var.finditer(line):
                            used_vars.add(m.group().replace("var(", "").strip())
            except Exception:
                pass

    if high_spec_findings:
        results.append("=== High specificity / !important ===\n" + "\n".join(high_spec_findings[:20]))
    unused = all_vars - used_vars
    if unused:
        results.append("=== Unused CSS properties ===\n" + "\n".join(f"  {v}" for v in sorted(unused)[:20]))
    return "\n\n".join(results) if results else "[No CSS issues detected]"


def _accessibility_checker(path: str = ".") -> str:
    issues = []
    checks = [
        (re.compile(r'<img(?![^>]*\balt\s*=)', re.I), "[A] img missing alt"),
        (re.compile(r'<button(?![^>]*aria-)', re.I), "[A] button missing aria"),
        (re.compile(r'<input(?![^>]*\b(?:id|aria-label))', re.I), "[A] input missing id/aria"),
        (re.compile(r'<div\s+onClick|<span\s+onClick', re.I), "[A] Non-interactive element with click"),
    ]

    html_exts = {".html", ".jsx", ".tsx", ".vue", ".svelte"}
    for fp in _glob.glob(os.path.join(path, "**", "*"), recursive=True):
        if not os.path.isfile(fp) or _skip(fp):
            continue
        if os.path.splitext(fp)[1].lower() not in html_exts:
            continue
        try:
            with open(fp, encoding="utf-8", errors="ignore") as f:
                for lineno, line in enumerate(f, 1):
                    for pattern, label in checks:
                        if pattern.search(line):
                            rel = os.path.relpath(fp, path)
                            issues.append(f"  {label} — {rel}:{lineno}")
                            break
        except Exception:
            pass
        if len(issues) >= 40:
            break

    return "\n".join(issues) if issues else "[No obvious accessibility issues]"


def _component_library_lookup(framework: str, component: str = "") -> str:
    docs = {
        "react": {
            "": "React UI libraries: shadcn/ui (Radix+Tailwind), MUI, Ant Design, Chakra UI, Headless UI",
            "dialog": "shadcn/ui: <Dialog><DialogContent>...</DialogContent></Dialog>",
            "form": "React Hook Form: const { register, handleSubmit } = useForm()\nZod validation: z.object({ email: z.string().email() })",
            "table": "TanStack Table v8: useReactTable({ columns, data, getCoreRowModel })",
        },
        "vue": {
            "": "Vue UI: Vuetify, Element Plus, PrimeVue, Naive UI, shadcn-vue",
        },
        "tailwind": {
            "": "Tailwind: flex items-center justify-between gap-4 | grid grid-cols-3 gap-6 | sm:flex-col md:flex-row | dark:bg-gray-900",
        },
    }

    fw_lower = framework.lower()
    comp_lower = component.lower()
    fw_docs = docs.get(fw_lower, {})
    if comp_lower and comp_lower in fw_docs:
        return f"=== {framework} — {component} ===\n{fw_docs[comp_lower]}"
    elif "" in fw_docs:
        return f"=== {framework} ===\n{fw_docs['']}"
    return f"[No docs for '{framework}'. Options: react, vue, tailwind]"


def _state_management_advisor(framework: str = "react") -> str:
    advice = {
        "react": (
            "Simple: useState, useReducer\n"
            "Shared (small): React Context + useReducer\n"
            "Complex: Zustand (lightweight) or Redux Toolkit\n"
            "Server state: TanStack Query or SWR\n"
            "Forms: React Hook Form"
        ),
        "vue": "Simple: ref/reactive\nShared: Pinia (official)\nServer: TanStack Query for Vue",
        "svelte": "Simple: let/$:\nShared: Svelte stores (writable/readable/derived)",
    }
    return advice.get(framework.lower(), f"[No advice for '{framework}']")


# ── Tool schemas ─────────────────────────────────────────────────────────────

_EXTRA_TOOLS = [
    {"type": "function", "function": {
        "name": "css_analyzer",
        "description": "Analyze CSS files for high specificity, !important, and unused properties.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Project root."}
        }, "required": []}
    }},
    {"type": "function", "function": {
        "name": "accessibility_checker",
        "description": "Audit HTML/JSX/TSX for WCAG 2.1 issues.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Project root."}
        }, "required": []}
    }},
    {"type": "function", "function": {
        "name": "component_library_lookup",
        "description": "Get UI component usage guidance for react/vue/tailwind.",
        "parameters": {"type": "object", "properties": {
            "framework": {"type": "string", "description": "react | vue | tailwind"},
            "component": {"type": "string", "description": "Component name (dialog, form, table)."}
        }, "required": ["framework"]}
    }},
    {"type": "function", "function": {
        "name": "state_management_advisor",
        "description": "Get state management recommendations for react/vue/svelte.",
        "parameters": {"type": "object", "properties": {
            "framework": {"type": "string", "description": "react | vue | svelte"}
        }, "required": []}
    }},
]

# ── Agent spec ───────────────────────────────────────────────────────────────

SPEC = {
    "name": "Frontend Agent",
    "icon": "palette",
    "color": "#f78c6c",
    "description": "UI, components, styling, state, routing",
    "agent_type": "frontend",

    "extra_tools": _EXTRA_TOOLS,
    "extra_dispatch": {
        "css_analyzer": _css_analyzer,
        "accessibility_checker": _accessibility_checker,
        "component_library_lookup": _component_library_lookup,
        "state_management_advisor": _state_management_advisor,
    },

    "system_prompt": """You are the Frontend Agent in a multi-agent development system.

YOUR ROLE: Implement all client-side code — components, pages, styling, state management, routing.

SPECIALIZED TOOLS:
- css_analyzer(path)                        — CSS specificity and unused vars
- accessibility_checker(path)               — WCAG 2.1 audit
- component_library_lookup(framework, comp) — UI library snippets
- state_management_advisor(framework)       — state patterns
- message_agent(target_id, message)         — coordinate with other agents or reply to user

WORKFLOW:
1. Read project context and analysis findings
2. Read existing files before editing
3. Implement with edit_file (surgical) or write_file (new files)
4. Use message_agent to notify peers about completed components or API contracts
5. Run build/lint if applicable

RULES:
- ALWAYS read a file before editing it
- Follow existing code style and framework conventions
- Coordinate with backend agents via message_agent when you need API contracts
- When done, output a summary of files changed and components created""",
}
