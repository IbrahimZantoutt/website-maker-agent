import os
import re
import glob as _glob

_SKIP = {".git", "__pycache__", ".venv", "venv", "node_modules",
         ".pytest_cache", "dist", "build", "project_context"}


def _skip(path: str) -> bool:
    return bool(set(path.replace("\\", "/").split("/")) & _SKIP)


# ── Tool implementations ──────────────────────────────────────────────────────

def _css_analyzer(path: str = ".") -> str:
    """Analyse stylesheets for issues: high specificity, duplicate rules, unused variables."""
    results = []
    high_spec = re.compile(r'(#\w+\s+){2,}|(\.\w+\s+){4,}|!important')
    css_var   = re.compile(r'--[\w-]+\s*:')
    used_var  = re.compile(r'var\s*\(\s*--[\w-]+')

    all_vars:  set = set()
    used_vars: set = set()
    high_spec_findings = []

    for fp in _glob.glob(os.path.join(path, "**", "*.{css,scss,less}"), recursive=True):
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
        results.append("=== High specificity / !important usage (hard to override) ===\n"
                       + "\n".join(high_spec_findings[:20]))

    unused = all_vars - used_vars
    if unused:
        results.append("=== Potentially unused CSS custom properties ===\n"
                       + "\n".join(f"  {v}" for v in sorted(unused)[:20]))

    return "\n\n".join(results) if results else "[No CSS issues detected]"


def _accessibility_checker(path: str = ".") -> str:
    """Audit HTML/JSX/TSX for common WCAG 2.1 accessibility issues."""
    issues = []
    checks = [
        (re.compile(r'<img(?![^>]*\balt\s*=)', re.I),          "[A] img missing alt attribute"),
        (re.compile(r'<button(?![^>]*aria-)', re.I),            "[A] button missing aria label"),
        (re.compile(r'<input(?![^>]*\b(?:id|aria-label))', re.I), "[A] input missing id or aria-label"),
        (re.compile(r'onClick|onMouseDown', re.I),              "[A] click handler — ensure keyboard support too"),
        (re.compile(r'color:\s*#[0-9a-fA-F]{3,6}.*background|background.*color:\s*#', re.I),
                                                                "[AA] Check color contrast ratio"),
        (re.compile(r'tabIndex\s*=\s*["\']?-1', re.I),         "[A] tabIndex=-1 removes element from tab order"),
        (re.compile(r'<div\s+onClick|<span\s+onClick', re.I),  "[A] Non-interactive element with click — use button"),
        (re.compile(r'<html(?![^>]*lang\s*=)', re.I),           "[A] html element missing lang attribute"),
        (re.compile(r'<frame|<frameset', re.I),                 "[A] frames are inaccessible — use landmarks"),
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
                            issues.append(f"  {label}\n    {rel}:{lineno}: {line.strip()[:80]}")
                            break
        except Exception:
            pass
        if len(issues) >= 40:
            break

    return "\n".join(issues) if issues else "[No obvious accessibility issues detected]"


def _performance_auditor(path: str = ".") -> str:
    """Audit frontend for common performance issues."""
    issues = []
    perf_checks = [
        (re.compile(r'import\s+\w+\s+from\s+["\']lodash["\']'),       "Import entire lodash — use lodash/{fn} instead"),
        (re.compile(r'import\s+\*\s+from'),                            "Wildcard import may bloat bundle"),
        (re.compile(r'useEffect\s*\(\s*.*\[\s*\]\s*\)', re.S),        "useEffect with empty deps — check if needed"),
        (re.compile(r'useState.*\[\]|useState.*\{\}'),                 "State initialized as array/object — wrap in useMemo if expensive"),
        (re.compile(r'new\s+Image\s*\('),                              "Manual image preloading — consider lazy loading"),
        (re.compile(r'document\.querySelector|document\.getElementById'), "Direct DOM access in component — use refs"),
        (re.compile(r'setInterval|setTimeout.*\d{4,}'),               "Long timer — consider debounce or requestAnimationFrame"),
        (re.compile(r'<img(?![^>]*loading=["\']lazy["\'])', re.I),   "img without loading=lazy — consider lazy loading"),
        (re.compile(r'JSON\.parse\s*\(.*JSON\.stringify', re.S),       "JSON.parse(JSON.stringify()) — use structuredClone()"),
    ]

    src_exts = {".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte"}
    for fp in _glob.glob(os.path.join(path, "**", "*"), recursive=True):
        if not os.path.isfile(fp) or _skip(fp):
            continue
        if os.path.splitext(fp)[1].lower() not in src_exts:
            continue
        try:
            with open(fp, encoding="utf-8", errors="ignore") as f:
                content = f.read()
            rel = os.path.relpath(fp, path)
            for pattern, label in perf_checks:
                if pattern.search(content):
                    issues.append(f"  [{label}] — {rel}")
        except Exception:
            pass

    return "\n".join(issues) if issues else "[No obvious frontend performance issues detected]"


def _component_library_lookup(framework: str, component: str = "") -> str:
    """Return usage guidance for a component from a popular UI library."""
    docs = {
        "react": {
            "": "React UI libraries: shadcn/ui (Radix+Tailwind), MUI (Material), Ant Design, Chakra UI, Headless UI",
            "dialog": "shadcn/ui: <Dialog><DialogContent>...</DialogContent></Dialog>\nHeadless UI: <Dialog open={isOpen} onClose={setIsOpen}>",
            "form":   "React Hook Form: const { register, handleSubmit } = useForm()\nZod for validation: z.object({ email: z.string().email() })",
            "table":  "TanStack Table v8: useReactTable({ columns, data, getCoreRowModel })",
            "toast":  "shadcn/ui: useToast() hook → toast({ title: '...', description: '...' })",
        },
        "vue": {
            "": "Vue UI libraries: Vuetify, Element Plus, PrimeVue, Naive UI, shadcn-vue",
            "form":   "VeeValidate + Zod: const { handleSubmit } = useForm({ validationSchema })",
            "dialog": "Element Plus: <el-dialog v-model='dialogVisible'>",
        },
        "tailwind": {
            "": "Tailwind CSS utility reference:\n  Flex: flex items-center justify-between gap-4\n  Grid: grid grid-cols-3 gap-6\n  Responsive: sm:flex-col md:flex-row\n  Dark: dark:bg-gray-900 dark:text-white",
        },
    }

    fw_lower = framework.lower()
    comp_lower = component.lower()
    fw_docs = docs.get(fw_lower, {})

    if comp_lower and comp_lower in fw_docs:
        return f"=== {framework} — {component} ===\n{fw_docs[comp_lower]}"
    elif "" in fw_docs:
        result = f"=== {framework} libraries & docs ===\n{fw_docs['']}"
        if comp_lower:
            result += f"\n\n[No specific snippet for '{component}' — check the library docs above]"
        return result
    return f"[No documentation found for framework '{framework}'. Common options: react, vue, tailwind]"


def _state_management_advisor(framework: str = "react") -> str:
    """Recommend a state management approach for the given framework."""
    advice = {
        "react": (
            "=== React State Management Recommendations ===\n\n"
            "Simple local state: useState, useReducer\n"
            "Shared state (small app): React Context + useReducer\n"
            "Complex/large app: Zustand (lightweight) or Redux Toolkit (structured)\n"
            "Server state: TanStack Query (recommended) or SWR\n"
            "Form state: React Hook Form\n\n"
            "Example — Zustand store:\n"
            "  import { create } from 'zustand'\n"
            "  const useStore = create((set) => ({\n"
            "    count: 0,\n"
            "    increment: () => set((state) => ({ count: state.count + 1 }))\n"
            "  }))\n"
        ),
        "vue": (
            "=== Vue State Management Recommendations ===\n\n"
            "Simple: ref() and reactive() from Vue Composition API\n"
            "Shared state: Pinia (official, replaces Vuex)\n"
            "Server state: TanStack Query for Vue\n\n"
            "Example — Pinia store:\n"
            "  export const useCounterStore = defineStore('counter', () => {\n"
            "    const count = ref(0)\n"
            "    function increment() { count.value++ }\n"
            "    return { count, increment }\n"
            "  })\n"
        ),
        "svelte": (
            "=== Svelte State Management Recommendations ===\n\n"
            "Simple: let / reactive declarations ($:)\n"
            "Shared: Svelte stores (writable, readable, derived)\n"
            "Complex: nanostores or XState\n\n"
            "Example — Svelte writable store:\n"
            "  import { writable } from 'svelte/store'\n"
            "  export const count = writable(0)\n"
        ),
    }
    return advice.get(framework.lower(),
                      f"[No advice for '{framework}'. Options: react, vue, svelte]")


def _browser_compatibility_checker(feature: str = "") -> str:
    """Return browser compatibility information for CSS/JS features."""
    # Curated compatibility reference (MDN data as of 2024)
    compat = {
        "container_queries": {
            "support": "Chrome 105+, Firefox 110+, Safari 16+, Edge 105+",
            "status":  "Widely supported (2022+)",
            "usage":   "@container (min-width: 400px) { .card { font-size: 1.2rem; } }",
            "polyfill": "No reliable polyfill — use media queries as fallback for older browsers",
        },
        "css_grid": {
            "support":  "Chrome 57+, Firefox 52+, Safari 10.1+, Edge 16+ — all modern browsers",
            "status":   "Fully supported",
            "usage":    "display: grid; grid-template-columns: repeat(3, 1fr);",
            "polyfill": "None needed for modern targets",
        },
        "css_variables": {
            "support":  "Chrome 49+, Firefox 31+, Safari 9.1+, Edge 15+",
            "status":   "Fully supported",
            "usage":    "--primary: #3b82f6; color: var(--primary);",
            "polyfill": "postcss-custom-properties for IE11 if needed",
        },
        "subgrid": {
            "support":  "Chrome 117+, Firefox 71+, Safari 16+, Edge 117+",
            "status":   "Good support in 2024, some older Chrome versions missing",
            "usage":    "grid-template-columns: subgrid;",
            "polyfill": "No polyfill — use nested grid as fallback",
        },
        "view_transitions": {
            "support":  "Chrome 111+, Edge 111+ — Firefox/Safari in progress",
            "status":   "Progressive enhancement only",
            "usage":    "document.startViewTransition(() => updateDOM())",
            "polyfill": "No polyfill — gracefully degrade without it",
        },
        "web_components": {
            "support":  "Chrome 67+, Firefox 63+, Safari 10.1+, Edge 79+",
            "status":   "Widely supported",
            "usage":    "customElements.define('my-el', class extends HTMLElement {...})",
            "polyfill": "@webcomponents/polyfills for older Safari",
        },
        "fetch": {
            "support":  "All modern browsers — IE not supported natively",
            "status":   "Fully supported",
            "usage":    "const data = await fetch('/api').then(r => r.json())",
            "polyfill": "whatwg-fetch for IE11",
        },
        "intersection_observer": {
            "support":  "Chrome 51+, Firefox 55+, Safari 12.1+, Edge 15+",
            "status":   "Widely supported",
            "usage":    "new IntersectionObserver(cb, { threshold: 0.1 })",
            "polyfill": "intersection-observer npm polyfill for older Safari",
        },
        "css_nesting": {
            "support":  "Chrome 120+, Firefox 117+, Safari 17.2+, Edge 120+",
            "status":   "New — check target audience browser versions",
            "usage":    ".parent { color: red; & .child { color: blue; } }",
            "polyfill": "postcss-nesting plugin for build step",
        },
        "web_workers": {
            "support":  "All modern browsers",
            "status":   "Fully supported",
            "usage":    "const worker = new Worker('worker.js')",
            "polyfill": "None needed",
        },
        "wasm": {
            "support":  "Chrome 57+, Firefox 52+, Safari 11+, Edge 16+",
            "status":   "Widely supported",
            "usage":    "WebAssembly.instantiateStreaming(fetch('module.wasm'), imports)",
            "polyfill": "None available — requires native support",
        },
        "dialog": {
            "support":  "Chrome 37+, Firefox 98+, Safari 15.4+, Edge 79+",
            "status":   "Good modern support — avoid for older Safari < 15.4",
            "usage":    "<dialog> element with showModal() / close()",
            "polyfill": "dialog-polyfill for older browsers",
        },
    }

    if feature:
        key = feature.lower().replace(" ", "_").replace("-", "_")
        # Try partial match
        match = next((v for k, v in compat.items() if key in k or k in key), None)
        if match:
            matched_key = next(k for k in compat if key in k or k in key)
            return (
                f"=== Browser Compatibility: {matched_key.replace('_', ' ').title()} ===\n\n"
                f"Browser Support: {match['support']}\n"
                f"Status:         {match['status']}\n"
                f"Usage:          {match['usage']}\n"
                f"Polyfill:       {match['polyfill']}"
            )
        return (
            f"[No data for '{feature}']. Available features:\n" +
            "\n".join(f"  {k.replace('_', ' ')}" for k in compat) +
            "\n\nFor authoritative data: web_search('MDN browser compat " + feature + "')"
        )

    # Return summary table
    lines = ["=== Browser Compatibility Quick Reference ===\n"]
    for feat, data in compat.items():
        lines.append(f"{feat.replace('_', ' ').ljust(25)} | {data['status']}")
    lines.append("\n\nFor detailed info: browser_compatibility_checker(feature='css_grid')")
    lines.append("Source: MDN Web Docs — always verify at https://caniuse.com for target browsers")
    return "\n".join(lines)


def _i18n_handler(framework: str = "react", action: str = "setup") -> str:
    """Return internationalization setup and usage templates."""
    if "react" in framework.lower():
        if action.lower() in ("setup", "install"):
            return """=== i18n Setup — React (react-i18next) ===
# Install: npm install i18next react-i18next

# src/i18n.ts
import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import LanguageDetector from 'i18next-browser-languagedetector'

i18n
  .use(LanguageDetector)   // detects browser language
  .use(initReactI18next)
  .init({
    fallbackLng: 'en',
    debug: process.env.NODE_ENV === 'development',
    interpolation: { escapeValue: false },  // React escapes by default
    resources: {
      en: { translation: require('./locales/en.json') },
      es: { translation: require('./locales/es.json') },
      fr: { translation: require('./locales/fr.json') },
    },
  })

export default i18n

# src/main.tsx — import before App:
import './i18n'

# src/locales/en.json:
{
  "common": {
    "save":   "Save",
    "cancel": "Cancel",
    "delete": "Delete"
  },
  "auth": {
    "login":     "Login",
    "logout":    "Logout",
    "welcome":   "Welcome, {{name}}!"
  },
  "errors": {
    "required":  "This field is required",
    "not_found": "Resource not found"
  }
}"""

        elif action.lower() == "usage":
            return """=== i18n Usage — React ===

// In components:
import { useTranslation } from 'react-i18next'

function MyComponent() {
  const { t, i18n } = useTranslation()

  return (
    <>
      <h1>{t('auth.welcome', { name: 'Alice' })}</h1>
      <button>{t('common.save')}</button>

      {/* Pluralization */}
      <p>{t('items', { count: 5 })}</p>

      {/* Language switcher */}
      <select value={i18n.language} onChange={e => i18n.changeLanguage(e.target.value)}>
        <option value="en">English</option>
        <option value="es">Español</option>
        <option value="fr">Français</option>
      </select>
    </>
  )
}

// en.json — pluralization:
{
  "items_one":   "{{count}} item",
  "items_other": "{{count}} items"
}

// Lazy loading namespaces (for large apps):
import { useTranslation } from 'react-i18next'
const { t } = useTranslation('checkout')  // loads checkout.json separately"""

    elif "vue" in framework.lower():
        return """=== i18n Setup — Vue 3 (vue-i18n) ===
# Install: npm install vue-i18n@9

# src/i18n.ts
import { createI18n } from 'vue-i18n'

export const i18n = createI18n({
  legacy:        false,       // use Composition API
  locale:        'en',
  fallbackLocale: 'en',
  messages: {
    en: { hello: 'Hello {name}!', save: 'Save' },
    es: { hello: '¡Hola {name}!', save: 'Guardar' },
  }
})

# main.ts:
import { i18n } from './i18n'
app.use(i18n)

# In components:
<script setup>
import { useI18n } from 'vue-i18n'
const { t, locale } = useI18n()
</script>

<template>
  <p>{{ t('hello', { name: 'Alice' }) }}</p>
  <select v-model="locale">
    <option value="en">English</option>
    <option value="es">Español</option>
  </select>
</template>"""

    elif "next" in framework.lower() or "next.js" in framework.lower():
        return """=== i18n Setup — Next.js (next-intl) ===
# Install: npm install next-intl

# next.config.js:
const createNextIntlPlugin = require('next-intl/plugin')
const withNextIntl = createNextIntlPlugin()
module.exports = withNextIntl({})

# messages/en.json:
{
  "HomePage": {
    "title": "Hello world!",
    "about": "Go to the about page"
  }
}

# src/i18n.ts:
import { getRequestConfig } from 'next-intl/server'
export default getRequestConfig(async ({ locale }) => ({
  messages: (await import(`../messages/${locale}.json`)).default
}))

# In Server Components:
import { getTranslations } from 'next-intl/server'
export default async function HomePage() {
  const t = await getTranslations('HomePage')
  return <h1>{t('title')}</h1>
}

# In Client Components:
import { useTranslations } from 'next-intl'
export default function Nav() {
  const t = useTranslations('HomePage')
  return <nav>{t('about')}</nav>
}"""

    return f"[No i18n template for '{framework}'. Options: react, vue, next.js]"


def _responsive_tester(path: str = ".") -> str:
    """Scan frontend files for responsive design patterns and issues."""
    results = []

    # Look for viewport meta tag
    viewport_found = False
    for fp in _glob.glob(os.path.join(path, "**", "*.html"), recursive=True):
        if _skip(fp) or not os.path.isfile(fp):
            continue
        try:
            with open(fp, encoding="utf-8", errors="ignore") as f:
                content = f.read()
            if 'name="viewport"' in content:
                viewport_found = True
                break
        except Exception:
            pass

    results.append("=== Responsive Design Analysis ===\n")
    results.append(f"Viewport meta tag: {'✓ Found' if viewport_found else '✗ MISSING — add <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"> to <head>'}")

    # Scan CSS for responsive patterns
    media_queries     = []
    fixed_widths      = []
    missing_responsive = []
    good_patterns     = []

    mq_re     = re.compile(r'@media\s*\(([^)]+)\)', re.IGNORECASE)
    fixed_re  = re.compile(r'width\s*:\s*(\d+)px(?!\s*\))', re.IGNORECASE)
    flex_re   = re.compile(r'display\s*:\s*flex', re.IGNORECASE)
    grid_re   = re.compile(r'display\s*:\s*grid', re.IGNORECASE)
    vw_re     = re.compile(r'width\s*:\s*\d+vw|max-width\s*:\s*100%', re.IGNORECASE)

    css_exts = {".css", ".scss", ".less", ".sass"}
    for fp in _glob.glob(os.path.join(path, "**", "*"), recursive=True):
        if not os.path.isfile(fp) or _skip(fp):
            continue
        if os.path.splitext(fp)[1].lower() not in css_exts:
            continue
        try:
            with open(fp, encoding="utf-8", errors="ignore") as f:
                content = f.read()
            rel = os.path.relpath(fp, path)

            queries = mq_re.findall(content)
            for q in queries[:5]:
                media_queries.append(f"  @media({q}) — {rel}")

            fixed = fixed_re.findall(content)
            for w in fixed:
                if int(w) > 400:  # flag only wide fixed widths
                    fixed_widths.append(f"  width: {w}px (fixed) — {rel}")

            if flex_re.search(content):
                good_patterns.append(f"  ✓ flex layout — {rel}")
            if grid_re.search(content):
                good_patterns.append(f"  ✓ grid layout — {rel}")
            if vw_re.search(content):
                good_patterns.append(f"  ✓ fluid width (vw / 100%) — {rel}")
        except Exception:
            pass

    if media_queries:
        results.append(f"\n[Media Queries Found — {len(media_queries)}]")
        results.extend(media_queries[:10])
    else:
        results.append("\n[✗ NO media queries found — layout may not adapt to screen sizes]")

    if good_patterns:
        results.append("\n[Good Responsive Patterns]")
        results.extend(good_patterns[:10])

    if fixed_widths:
        results.append(f"\n[Fixed-Width Warnings — {len(fixed_widths)}]")
        results.extend(fixed_widths[:10])
        results.append("  Consider: max-width instead of width, or use % / vw units")

    results.append("\n[RECOMMENDATIONS]")
    results.append("  1. Use CSS Grid or Flexbox for layout (avoid float-based layouts)")
    results.append("  2. Define breakpoints: sm:640px md:768px lg:1024px xl:1280px")
    results.append("  3. Use max-width: 100% on images to prevent overflow")
    results.append("  4. Test with Chrome DevTools device emulation (F12 → device toolbar)")
    results.append("  5. Use clamp() for fluid typography: font-size: clamp(1rem, 2.5vw, 2rem)")
    results.append("  6. Tailwind CSS breakpoints: sm: md: lg: xl: 2xl: prefixes")

    return "\n".join(results)


# ── Tool schemas ──────────────────────────────────────────────────────────────

_EXTRA_TOOLS = [
    {
        "type": "function", "function": {
            "name": "css_analyzer",
            "description": "Analyze CSS/SCSS/Less files for high specificity, !important usage, and unused CSS custom properties.",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string", "description": "Project root. Default: current directory."}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "accessibility_checker",
            "description": "Audit HTML/JSX/TSX/Vue/Svelte files for WCAG 2.1 violations: missing alt attributes, missing aria labels, non-interactive elements with click handlers, missing lang attribute.",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string", "description": "Project root. Default: current directory."}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "performance_auditor",
            "description": "Audit frontend source for performance anti-patterns: full lodash imports, wildcard imports, direct DOM access, images without lazy loading, large setTimeout values.",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string", "description": "Project root. Default: current directory."}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "component_library_lookup",
            "description": "Get usage guidance and code snippets for a UI component from a popular library (React/shadcn, Vue/Element Plus, Tailwind).",
            "parameters": {"type": "object", "properties": {
                "framework": {"type": "string", "description": "react | vue | tailwind | svelte"},
                "component": {"type": "string", "description": "Component name (e.g. dialog, form, table, toast). Optional — omit for library overview."}
            }, "required": ["framework"]}
        }
    },
    {
        "type": "function", "function": {
            "name": "browser_compatibility_checker",
            "description": "Check browser support for a CSS or JS feature. Returns support table, status, usage example, and polyfill info. Features: css_grid, container_queries, subgrid, view_transitions, web_components, fetch, intersection_observer, css_nesting, wasm, dialog.",
            "parameters": {"type": "object", "properties": {
                "feature": {"type": "string", "description": "Feature name (e.g. css_grid, container_queries, web_components). Omit for a full reference table."}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "i18n_handler",
            "description": "Get internationalization (i18n) setup and usage templates for React (react-i18next), Vue (vue-i18n), or Next.js (next-intl).",
            "parameters": {"type": "object", "properties": {
                "framework": {"type": "string", "description": "react | vue | next.js. Default: react"},
                "action":    {"type": "string", "description": "setup | usage. Default: setup"}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "responsive_tester",
            "description": "Scan CSS/SCSS files and HTML for responsive design patterns: media queries, fixed widths, flex/grid usage, viewport meta tag presence, and improvement recommendations.",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string", "description": "Project root. Default: current directory."}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "state_management_advisor",
            "description": "Get state management recommendations and code examples for React (Zustand/Redux), Vue (Pinia), or Svelte (stores).",
            "parameters": {"type": "object", "properties": {
                "framework": {"type": "string", "description": "react | vue | svelte. Default: react"}
            }, "required": []}
        }
    },
]

# ── Agent spec ────────────────────────────────────────────────────────────────

SPEC = {
    "name":        "Frontend Agent",
    "icon":        "\U0001f3a8",
    "color":       "#f78c6c",
    "description": "UI, UX, and client-side code — components, styling, state, routing",

    # Full tool access — frontend agent both reads AND writes files
    "extra_tools":    _EXTRA_TOOLS,
    "extra_dispatch": {
        "css_analyzer":             _css_analyzer,
        "accessibility_checker":    _accessibility_checker,
        "performance_auditor":      _performance_auditor,
        "component_library_lookup": _component_library_lookup,
        "state_management_advisor":    _state_management_advisor,
        "browser_compatibility_checker": _browser_compatibility_checker,
        "i18n_handler":                _i18n_handler,
        "responsive_tester":           _responsive_tester,
    },

    "system_prompt": """You are the Frontend Agent in a multi-agent development system.

YOUR ROLE: Implement all client-side code changes specified in the Execution Plan.

SPECIALIZED TOOLS:
- css_analyzer(path)                        — find CSS specificity and unused variables
- accessibility_checker(path)               — WCAG 2.1 audit
- performance_auditor(path)                 — bundle and render performance issues
- component_library_lookup(framework, comp) — UI library code snippets
- state_management_advisor(framework)          — state management patterns
- browser_compatibility_checker(feature)       — MDN compat data for CSS/JS features
- i18n_handler(framework, action)              — react-i18next / vue-i18n / next-intl setup
- responsive_tester(path)                      — scan for responsive issues and media queries
- web_search(query)                            — look up component docs, CSS solutions, framework issues

IMPLEMENTATION WORKFLOW:
1. Read project_context/execution_plan.md FIRST
2. Use css_analyzer and accessibility_checker to understand current state
3. Read existing source files before editing them
4. Implement changes with edit_file (surgical) or write_file (new files)
5. Use component_library_lookup for unfamiliar component patterns
6. Run the build: run_shell("npm run build") or equivalent
7. Fix any build errors before declaring done

RULES:
- ALWAYS read a file before editing it
- Follow the existing code style and framework conventions exactly
- Never describe a change without applying it

OUTPUT: Write Frontend Report to project_context/frontend_report.md
Include: files changed, build status, accessibility fixes, any deviations from plan"""
}
