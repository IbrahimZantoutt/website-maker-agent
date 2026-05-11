import os
import re
import glob as _glob
import subprocess
import json as _json

_SKIP = {".git", "__pycache__", ".venv", "venv", "node_modules",
         ".pytest_cache", ".mypy_cache", "dist", "build", "project_context"}


def _skip(path: str) -> bool:
    return bool(set(path.replace("\\", "/").split("/")) & _SKIP)


# ── Tool implementations ──────────────────────────────────────────────────────

def _unit_test_generator(framework: str, module_name: str = "module",
                          functions: str = "") -> str:
    """Generate unit test scaffolding for the given framework and module."""
    func_list = [f.strip() for f in functions.split(",") if f.strip()] or ["example_fn"]

    if "pytest" in framework.lower() or "python" in framework.lower():
        cases = []
        for fn in func_list:
            cases.append(f"""
def test_{fn}_happy_path():
    \"\"\"Valid input returns expected output.\"\"\"
    result = {fn}(valid_input)
    assert result == expected_output


def test_{fn}_edge_case():
    \"\"\"Edge case (zero, empty, boundary) is handled.\"\"\"
    result = {fn}(edge_input)
    assert result is not None


def test_{fn}_raises_on_invalid():
    \"\"\"Invalid input raises expected error.\"\"\"
    with pytest.raises((ValueError, TypeError)):
        {fn}(None)""")

        param_fn = func_list[0]
        return f"""=== pytest Unit Tests: {module_name} ===

import pytest
from {module_name} import {', '.join(func_list)}


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_data():
    \"\"\"Reusable realistic test fixture.\"\"\"
    return {{
        # TODO: fill with realistic values
    }}


# ── Test cases ────────────────────────────────────────────────────────────────
{''.join(cases)}

# ── Parametrized tests ────────────────────────────────────────────────────────

@pytest.mark.parametrize("input_val,expected", [
    (1,    True),
    (0,    False),
    (-1,   False),
    (None, False),
])
def test_{param_fn}_parametrized(input_val, expected):
    assert bool({param_fn}(input_val)) == expected
"""

    elif "jest" in framework.lower() or "vitest" in framework.lower():
        import_line = (
            "import { describe, it, expect, beforeEach } from 'vitest'"
            if "vitest" in framework.lower()
            else "// Jest globals are available automatically"
        )
        cases = []
        for fn in func_list:
            cases.append(f"""
  describe('{fn}', () => {{
    it('returns expected result for valid input', () => {{
      expect({fn}(validInput)).toBe(expectedOutput)
    }})

    it('handles edge case gracefully', () => {{
      expect({fn}(edgeInput)).not.toBeNull()
    }})

    it('throws on null input', () => {{
      expect(() => {fn}(null)).toThrow()
    }})
  }})""")

        return f"""=== {framework} Unit Tests: {module_name} ===

{import_line}
import {{ {', '.join(func_list)} }} from './{module_name}'

describe('{module_name}', () => {{
  let validInput, edgeInput, expectedOutput

  beforeEach(() => {{
    validInput     = /* TODO */
    edgeInput      = /* TODO */
    expectedOutput = /* TODO */
  }})
{''.join(cases)}
}})
"""

    elif "rspec" in framework.lower() or "ruby" in framework.lower():
        cases = "\n".join([f"""
  describe '#{fn}' do
    it 'returns expected result' do
      expect(subject.{fn}(valid_input)).to eq(expected_output)
    end

    it 'raises ArgumentError on nil' do
      expect {{ subject.{fn}(nil) }}.to raise_error(ArgumentError)
    end
  end""" for fn in func_list])
        return f"""=== RSpec Unit Tests: {module_name} ===

require 'spec_helper'
require '{module_name}'

RSpec.describe {module_name.split('_')[-1].capitalize()} do
  subject {{ described_class.new }}
  let(:valid_input)     {{ nil }}  # TODO: fill in
  let(:expected_output) {{ nil }}  # TODO: fill in
{cases}
end
"""

    elif "junit" in framework.lower() or "java" in framework.lower():
        cls = ''.join(w.capitalize() for w in module_name.split('_'))
        cases = "\n".join([f"""
    @Test
    @DisplayName("{fn} — happy path")
    void test{fn[0].upper() + fn[1:]}HappyPath() {{
        var result = sut.{fn}(/* valid input */);
        assertEquals(/* expected */, result);
    }}

    @Test
    @DisplayName("{fn} — throws on null")
    void test{fn[0].upper() + fn[1:]}ThrowsOnNull() {{
        assertThrows(IllegalArgumentException.class, () -> sut.{fn}(null));
    }}""" for fn in func_list])
        return f"""=== JUnit 5 Unit Tests: {module_name} ===

import org.junit.jupiter.api.*;
import static org.junit.jupiter.api.Assertions.*;

@DisplayName("{module_name} Tests")
class {cls}Test {{

    private {cls} sut;

    @BeforeEach
    void setUp() {{
        sut = new {cls}();
    }}
{cases}
}}
"""

    return f"[No template for '{framework}'. Options: pytest, jest, vitest, rspec, junit]"


def _integration_test_builder(framework: str = "pytest", endpoint: str = "/api/resource",
                               method: str = "GET", description: str = "") -> str:
    """Generate integration tests for API endpoints."""
    method = method.upper()

    if "pytest" in framework.lower() or "python" in framework.lower():
        send = ""
        if method in ("POST", "PUT", "PATCH"):
            send = f"\n    payload = {{  # TODO: fill with valid body\n    }}\n    response = await client.{method.lower()}(ENDPOINT, json=payload)"
        else:
            send = f"\n    response = await client.{method.lower()}(ENDPOINT)"

        return f"""=== pytest Integration Tests: {method} {endpoint} ===
# {description}

import pytest
from httpx import AsyncClient
from main import app  # adjust to your app entry point

BASE_URL = "http://testserver"
ENDPOINT = "{endpoint}"


@pytest.fixture(scope="module")
async def client():
    async with AsyncClient(app=app, base_url=BASE_URL) as ac:
        yield ac


@pytest.mark.asyncio
async def test_{method.lower()}_success(client):{send}
    assert response.status_code in (200, 201)
    assert response.json() is not None  # TODO: assert specific fields


@pytest.mark.asyncio
async def test_{method.lower()}_unauthorized(client):
    \"\"\"Missing auth token returns 401.\"\"\"
    response = await client.{method.lower()}(ENDPOINT)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_{method.lower()}_not_found(client):
    \"\"\"Non-existent resource returns 404.\"\"\"
    response = await client.{method.lower()}(ENDPOINT + "/nonexistent-99999")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_{method.lower()}_validation_error(client):
    \"\"\"Malformed body returns 422.\"\"\"
    response = await client.{method.lower()}(ENDPOINT, json={{"invalid": True}})
    assert response.status_code in (400, 422)
"""

    elif "jest" in framework.lower() or "supertest" in framework.lower():
        send = ""
        if method in ("POST", "PUT", "PATCH"):
            send = "\n      .send({ /* TODO: valid body */ })"
        return f"""=== Supertest Integration Tests: {method} {endpoint} ===
// {description}

const request = require('supertest')
const app     = require('../../src/app')  // adjust import

const ENDPOINT = '{endpoint}'

describe('{method} {endpoint}', () => {{
  it('returns 2xx for valid request', async () => {{
    const res = await request(app)
      .{method.lower()}(ENDPOINT){send}
      .set('Authorization', `Bearer ${{process.env.TEST_TOKEN}}`)
    expect(res.status).toBeGreaterThanOrEqual(200)
    expect(res.status).toBeLessThan(300)
  }})

  it('returns 401 when unauthenticated', async () => {{
    const res = await request(app).{method.lower()}(ENDPOINT)
    expect(res.status).toBe(401)
  }})

  it('returns 404 for missing resource', async () => {{
    const res = await request(app)
      .{method.lower()}(ENDPOINT + '/nonexistent-99999')
      .set('Authorization', `Bearer ${{process.env.TEST_TOKEN}}`)
    expect(res.status).toBe(404)
  }})
}})
"""

    return f"[No template for '{framework}'. Options: pytest, jest/supertest]"


def _e2e_test_builder(framework: str = "playwright", flow_name: str = "user_flow",
                       steps: str = "") -> str:
    """Generate end-to-end test templates."""
    step_list = [s.strip() for s in steps.split(",") if s.strip()] if steps else [
        "navigate to the page", "fill in the form", "submit the form", "verify success state"
    ]

    if "playwright" in framework.lower():
        step_comments = "\n    ".join(f"// Step {i+1}: {s}" for i, s in enumerate(step_list))
        return f"""=== Playwright E2E: {flow_name} ===

import {{ test, expect }} from '@playwright/test'

test.describe('{flow_name}', () => {{
  test.beforeEach(async ({{ page }}) => {{
    await page.goto(process.env.BASE_URL || 'http://localhost:3000')
    // await page.evaluate(() => localStorage.setItem('token', process.env.TEST_TOKEN))
  }})

  test('completes {flow_name} successfully', async ({{ page }}) => {{
    {step_comments}

    // Playwright actions (fill in per step above):
    // await page.goto('/path')
    // await page.getByRole('button', {{ name: 'Submit' }}).click()
    // await page.getByLabel('Email').fill('test@example.com')
    // await page.waitForURL('**/success')
    // await expect(page.getByText('Success')).toBeVisible()

    await expect(page).toHaveTitle(/expected/i)
  }})

  test('shows error on invalid input', async ({{ page }}) => {{
    // TODO: trigger error state
    await expect(page.getByRole('alert')).toBeVisible()
  }})

  test('is accessible', async ({{ page }}) => {{
    const violations = await page.evaluate(() =>
      // Use axe-core: npm install axe-playwright
      // return new AxeBuilder({{ page }}).analyze()
      []
    )
    expect(violations).toHaveLength(0)
  }})
}})

// playwright.config.ts:
// export default defineConfig({{
//   testDir: './e2e',
//   use: {{ baseURL: 'http://localhost:3000', screenshot: 'only-on-failure' }},
//   projects: [
//     {{ name: 'chromium', use: {{ ...devices['Desktop Chrome'] }} }},
//     {{ name: 'firefox',  use: {{ ...devices['Desktop Firefox'] }} }},
//   ],
// }})
"""

    elif "cypress" in framework.lower():
        step_comments = "\n    ".join(f"// {s}" for s in step_list)
        return f"""=== Cypress E2E: {flow_name} ===

describe('{flow_name}', () => {{
  beforeEach(() => {{
    cy.visit('/')
    // cy.login()  // custom command for auth
  }})

  it('completes {flow_name} successfully', () => {{
    {step_comments}

    // Cypress commands:
    // cy.get('[data-cy=submit]').click()
    // cy.get('input[name=email]').type('test@example.com')
    // cy.url().should('include', '/success')
    // cy.contains('Success').should('be.visible')
  }})

  it('handles validation errors', () => {{
    cy.get('form').submit()
    cy.get('[data-cy=error-message]').should('be.visible')
  }})
}})

// cypress.config.ts:
// export default defineConfig({{
//   e2e: {{ baseUrl: 'http://localhost:3000', specPattern: 'cypress/e2e/**/*.cy.ts' }}
// }})
"""

    return f"[No template for '{framework}'. Options: playwright, cypress]"


def _regression_detector(path: str = ".") -> str:
    """Scan for patterns that are common sources of test regressions."""
    fragile_patterns = [
        (re.compile(r'time\.sleep|asyncio\.sleep'),                   "Hard-coded sleep (timing-sensitive)"),
        (re.compile(r'datetime\.now\(\)|Date\.now\(\)'),             "Un-mocked datetime (time-sensitive)"),
        (re.compile(r'\brandom\.\b|Math\.random\(\)'),               "Un-seeded randomness (non-deterministic)"),
        (re.compile(r'os\.environ\[|process\.env\.'),                "Direct env access (should be injected)"),
        (re.compile(r'global\s+\w+'),                                "Global mutable state (test pollution risk)"),
        (re.compile(r'monkeypatch(?!.*\bfixture\b)'),                "Monkeypatch without cleanup"),
        (re.compile(r'\.only\(|fdescribe\(|fit\('),                  "Focused test (.only) — blocks other tests"),
        (re.compile(r'xtest\(|xit\(|@pytest\.mark\.skip'),           "Skipped test — hidden regression"),
        (re.compile(r'TODO.*test|test.*TODO', re.I),                 "Incomplete test"),
        (re.compile(r'assert\s+True$|assertEqual\(True'),            "Trivially passing assertion"),
    ]

    test_files = set()
    for fp in _glob.glob(os.path.join(path, "**", "*"), recursive=True):
        if os.path.isfile(fp) and not _skip(fp):
            base = os.path.basename(fp)
            if "test" in base or "spec" in base:
                test_files.add(fp)

    findings = []
    for fp in _glob.glob(os.path.join(path, "**", "*"), recursive=True):
        if not os.path.isfile(fp) or _skip(fp):
            continue
        ext = os.path.splitext(fp)[1].lower()
        if ext not in {".py", ".js", ".ts", ".rb", ".go", ".java"}:
            continue
        try:
            with open(fp, encoding="utf-8", errors="ignore") as f:
                for lineno, line in enumerate(f, 1):
                    for pattern, label in fragile_patterns:
                        if pattern.search(line):
                            rel = os.path.relpath(fp, path)
                            findings.append(f"  [{label}]\n    {rel}:{lineno}: {line.strip()[:80]}")
                            break
        except Exception:
            pass
        if len(findings) >= 60:
            break

    lines = ["=== Regression Risk Analysis ===\n"]
    lines.append(f"Test files found: {len(test_files)}")
    if findings:
        lines.append(f"\n[FRAGILE PATTERNS — {len(findings)} found]")
        lines.extend(findings[:40])
    else:
        lines.append("\n[No obvious fragile patterns detected]")

    lines.append("\n[RECOMMENDATIONS]")
    lines.append("  1. Mock time, random, env vars — never depend on real values in tests")
    lines.append("  2. Avoid global state — use fixtures with proper teardown")
    lines.append("  3. Remove .only() tests — they silently hide regressions in other tests")
    lines.append("  4. Remove skip markers — fix or delete the test, never skip forever")
    lines.append("  5. Run full test suite on every PR — CI must be green before merge")
    return "\n".join(lines)


def _coverage_analyzer(path: str = ".", language: str = "auto") -> str:
    """Run test coverage tools and return the report."""
    results = []

    has_py = any(
        fp for fp in _glob.glob(os.path.join(path, "**", "*.py"), recursive=True)
        if not _skip(fp)
    )
    has_js = os.path.exists(os.path.join(path, "package.json"))

    if language.lower() in ("auto", "python") and has_py:
        try:
            r = subprocess.run(
                "pytest --cov=. --cov-report=term-missing -q 2>&1",
                shell=True, capture_output=True, text=True, timeout=120, cwd=path
            )
            output = (r.stdout + r.stderr).strip()
            results.append(f"=== pytest Coverage ===\n{output[:4000]}")
        except subprocess.TimeoutExpired:
            results.append("=== pytest Coverage ===\n[Timed out — run manually: pytest --cov=. --cov-report=term-missing]")
        except Exception as e:
            results.append(f"=== pytest Coverage ===\n[Error: {e}]\nInstall: pip install pytest pytest-cov")

    if language.lower() in ("auto", "javascript", "js", "typescript", "ts") and has_js:
        try:
            with open(os.path.join(path, "package.json")) as f:
                pkg = _json.load(f)
            test_script = pkg.get("scripts", {}).get("test", "")
            if "vitest" in test_script:
                cmd = "npx vitest run --coverage 2>&1"
            else:
                cmd = "npm test -- --coverage --watchAll=false 2>&1"
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                               timeout=120, cwd=path)
            output = (r.stdout + r.stderr).strip()
            results.append(f"=== JS/TS Coverage ===\n{output[:4000]}")
        except Exception as e:
            results.append(f"=== JS/TS Coverage ===\n[Error: {e}]")

    if not results:
        return """[No coverage run succeeded. Setup guide:]
  Python:  pip install pytest pytest-cov → pytest --cov=. --cov-report=term-missing
  JS/TS:   npm test -- --coverage (Jest) | npx vitest run --coverage (Vitest)
  Go:      go test ./... -coverprofile=cov.out && go tool cover -func=cov.out
  Ruby:    add gem 'simplecov' → bundle exec rspec
  Java:    mvn test (JaCoCo plugin in pom.xml)"""
    return "\n\n".join(results)


def _mutation_tester(path: str = ".", language: str = "auto") -> str:
    """Run mutation testing to validate test quality, or provide setup instructions."""
    results = []

    has_py = any(
        fp for fp in _glob.glob(os.path.join(path, "**", "*.py"), recursive=True)
        if not _skip(fp)
    )
    has_js = os.path.exists(os.path.join(path, "package.json"))

    if language.lower() in ("auto", "python") and has_py:
        try:
            r = subprocess.run(
                "mutmut run --paths-to-mutate . 2>&1",
                shell=True, capture_output=True, text=True, timeout=300, cwd=path
            )
            out = (r.stdout + r.stderr).strip()
            if out and "command not found" not in out.lower() and "not recognized" not in out.lower():
                results.append(f"=== mutmut (Python) ===\n{out[:3000]}")
                r2 = subprocess.run("mutmut results 2>&1", shell=True,
                                    capture_output=True, text=True, timeout=30, cwd=path)
                results.append(f"Results:\n{(r2.stdout + r2.stderr).strip()[:2000]}")
            else:
                results.append(
                    "=== mutmut (Python Mutation Testing) ===\n"
                    "[Not installed. Setup:]\n"
                    "  pip install mutmut\n"
                    "  mutmut run\n"
                    "  mutmut results\n"
                    "  mutmut show <id>   ← see exactly what survived\n\n"
                    "Surviving mutant = your tests didn't catch that code change.\n"
                    "Target: mutation score > 70%"
                )
        except subprocess.TimeoutExpired:
            results.append("=== mutmut ===\n[Still running — mutation testing is slow for large codebases. Check progress: mutmut results]")
        except Exception as e:
            results.append(f"=== mutmut ===\n[Error: {e}. Install: pip install mutmut]")

    if language.lower() in ("auto", "javascript", "typescript") and has_js:
        results.append(
            "=== Stryker (JS/TS Mutation Testing) ===\n"
            "Setup:\n"
            "  npm install --save-dev @stryker-mutator/core @stryker-mutator/jest-runner\n"
            "  npx stryker init\n\n"
            "Run:\n"
            "  npx stryker run\n\n"
            "stryker.config.json:\n"
            "{\n"
            '  "testRunner": "jest",\n'
            '  "mutate": ["src/**/*.ts", "!src/**/*.test.ts"],\n'
            '  "reporters": ["html", "clear-text", "progress"],\n'
            '  "thresholds": { "high": 80, "low": 60, "break": 50 }\n'
            "}"
        )

    if not results:
        return (
            "=== Mutation Testing — Quick Reference ===\n"
            "Python:  pip install mutmut && mutmut run && mutmut results\n"
            "JS/TS:   npx stryker init && npx stryker run\n"
            "Go:      go install github.com/zimmski/go-mutesting/...@latest && go-mutesting ./...\n"
            "Ruby:    gem install mutant && bundle exec mutant -- ClassName\n\n"
            "Concept: each 'mutant' is a small code change. If tests pass anyway → gap in coverage."
        )
    return "\n\n".join(results)


def _performance_tester(tool: str = "k6", target_url: str = "http://localhost:8000",
                         rps: int = 100) -> str:
    """Generate a load test script template for the given tool."""
    if "k6" in tool.lower():
        return f"""=== k6 Load Test — {target_url} ===
// Install: https://k6.io/docs/get-started/installation/
// Run:     k6 run load_test.js
// With env: k6 run --env BASE_URL={target_url} load_test.js

import http   from 'k6/http'
import {{ sleep, check }} from 'k6'
import {{ Rate }} from 'k6/metrics'

const errorRate = new Rate('errors')

export const options = {{
  stages: [
    {{ duration: '30s', target: {max(1, rps // 4)} }},   // ramp up
    {{ duration: '1m',  target: {rps} }},               // hold
    {{ duration: '30s', target: 0 }},                   // ramp down
  ],
  thresholds: {{
    http_req_duration: ['p(95)<500'],   // 95% requests under 500 ms
    http_req_failed:   ['rate<0.01'],   // < 1% error rate
    errors:            ['rate<0.05'],
  }},
}}

const BASE_URL = __ENV.BASE_URL || '{target_url}'

export default function () {{
  const res = http.get(`${{BASE_URL}}/api/endpoint`)

  const ok = check(res, {{
    'status is 200':      (r) => r.status === 200,
    'response under 1s':  (r) => r.timings.duration < 1000,
    'body not empty':     (r) => r.body.length > 0,
  }})
  errorRate.add(!ok)

  // POST example:
  // const payload = JSON.stringify({{ key: 'value' }})
  // const params  = {{ headers: {{ 'Content-Type': 'application/json' }} }}
  // http.post(`${{BASE_URL}}/api/resource`, payload, params)

  sleep(1)
}}
"""

    elif "locust" in tool.lower():
        return f"""=== Locust Load Test — {target_url} ===
# Install: pip install locust
# Run UI:  locust -f locustfile.py --host={target_url}
# Run CLI: locust -f locustfile.py --host={target_url} --users={rps * 5} --spawn-rate={rps} --headless -t 2m

from locust import HttpUser, task, between
import random


class APIUser(HttpUser):
    wait_time = between(0.5, 2)
    host      = "{target_url}"

    def on_start(self):
        \"\"\"Run once per user on start — use for login.\"\"\"
        # resp = self.client.post("/auth/token", json={{"username":"u","password":"p"}})
        # self.token = resp.json().get("access_token", "")
        # self.client.headers["Authorization"] = f"Bearer {{self.token}}"

    @task(3)
    def get_list(self):
        self.client.get("/api/resources")

    @task(1)
    def get_single(self):
        self.client.get(f"/api/resources/{{random.randint(1, 100)}}")

    @task(1)
    def create(self):
        self.client.post("/api/resources", json={{
            "name": f"test-{{random.randint(1000, 9999)}}",
        }})
"""

    elif "artillery" in tool.lower():
        return f"""=== Artillery Load Test — {target_url} ===
# Install: npm install -g artillery
# Run:     artillery run load_test.yml
# Report:  artillery run --output report.json load_test.yml && artillery report report.json

config:
  target: "{target_url}"
  phases:
    - duration: 30
      arrivalRate: {max(1, rps // 4)}
      name: "Ramp up"
    - duration: 60
      arrivalRate: {rps}
      name: "Sustained load"
  defaults:
    headers:
      Authorization: "Bearer {{{{$processEnvironment.TEST_TOKEN}}}}"
      Content-Type:  "application/json"

scenarios:
  - name: "Read + Write flow"
    flow:
      - get:
          url: "/api/resources"
          expect:
            - statusCode: 200
      - post:
          url: "/api/resources"
          json:
            name: "test-resource"
          expect:
            - statusCode: 201
"""

    return f"[No template for '{tool}'. Options: k6, locust, artillery]"


def _test_data_generator(entity_name: str, fields: str = "", count: int = 5) -> str:
    """Generate realistic test fixtures and mock data."""
    count     = max(1, min(int(count), 50))
    field_list = [f.strip() for f in fields.split(",") if f.strip()] if fields else [
        "id", "name", "email", "created_at"
    ]

    def _val(field: str, idx: int):
        f = field.lower()
        if f in ("id", "pk") or f.endswith("_id"):          return idx + 1
        if "email" in f:                                     return f'"user{idx+1}@example.com"'
        if "username" in f or "user_name" in f:             return f'"user_{idx+1}"'
        if "first_name" in f:
            names = ["Alice", "Bob", "Charlie", "Diana", "Eve"]
            return f'"{names[idx % len(names)]}"'
        if "last_name" in f or "surname" in f:
            names = ["Smith", "Jones", "Brown", "Taylor", "Wilson"]
            return f'"{names[idx % len(names)]}"'
        if "name" in f:
            return f'"Test {entity_name.capitalize()} {idx+1}"'
        if "phone" in f:                                     return f'"555-{100 + idx:04d}"'
        if "url" in f or "website" in f:                    return f'"https://example.com/{idx+1}"'
        if "price" in f or "amount" in f or "cost" in f:   return round(9.99 + idx * 10, 2)
        if "count" in f or "quantity" in f or "stock" in f: return (idx + 1) * 5
        if "age" in f:                                       return 20 + (idx % 40)
        if f.startswith("is_") or "active" in f or "enabled" in f:
            return "true" if idx % 2 == 0 else "false"
        if "date" in f or f.endswith("_at") or "time" in f:
            return f'"2024-01-{(idx % 28) + 1:02d}T12:00:00Z"'
        if "status" in f:
            return f'"{["active","pending","inactive"][idx % 3]}"'
        if "description" in f or "bio" in f or "notes" in f:
            return f'"Sample {entity_name} {idx+1} description"'
        return f'"value_{idx+1}"'

    # JSON fixtures
    json_rows = ["  {" + ", ".join(f'"{fld}": {_val(fld, i)}' for fld in field_list) + "}"
                 for i in range(count)]

    # Python dicts
    py_rows = ["    {" + ", ".join(f'"{fld}": {_val(fld, i)}' for fld in field_list) + "},"
               for i in range(count)]

    # SQL INSERTs
    cols    = ", ".join(field_list)
    sql_rows = ["  (" + ", ".join(str(_val(fld, i)) for fld in field_list) + "),"
                for i in range(count)]

    first_py = "{" + ", ".join(f'"{fld}": {_val(fld, 0)}' for fld in field_list) + "}"
    ename = entity_name.lower()

    return f"""=== Test Data: {entity_name} ({count} records) ===

--- JSON (API mocking / fixtures files) ---
[
{chr(10).join(json_rows)}
]

--- Python dicts (pytest fixtures) ---
{ename.upper()}_FIXTURES = [
{chr(10).join(py_rows)}
]

--- SQL (database seeding) ---
INSERT INTO {ename}s ({cols}) VALUES
{chr(10).join(sql_rows).rstrip(',')};

--- pytest factory fixture ---
import pytest

@pytest.fixture
def {ename}_factory(db_session):
    def _make(**overrides):
        defaults = {first_py}
        defaults.update(overrides)
        obj = {entity_name.capitalize()}(**defaults)
        db_session.add(obj)
        db_session.commit()
        return obj
    return _make
"""


# ── Tool schemas ──────────────────────────────────────────────────────────────

_EXTRA_TOOLS = [
    {
        "type": "function", "function": {
            "name": "unit_test_generator",
            "description": "Generate a complete unit test file for a module. Supports pytest, jest, vitest, rspec, junit. Includes fixtures, parametrized tests, and edge cases.",
            "parameters": {"type": "object", "properties": {
                "framework":   {"type": "string", "description": "pytest | jest | vitest | rspec | junit"},
                "module_name": {"type": "string", "description": "Module/class/file name to test. Default: module"},
                "functions":   {"type": "string", "description": "Comma-separated function/method names to generate tests for."}
            }, "required": ["framework"]}
        }
    },
    {
        "type": "function", "function": {
            "name": "integration_test_builder",
            "description": "Generate integration tests for an API endpoint. Covers happy path, unauthorized, 404, and validation error cases.",
            "parameters": {"type": "object", "properties": {
                "framework":   {"type": "string", "description": "pytest | jest/supertest. Default: pytest"},
                "endpoint":    {"type": "string", "description": "API path, e.g. /api/users. Default: /api/resource"},
                "method":      {"type": "string", "description": "HTTP method: GET, POST, PUT, DELETE, PATCH. Default: GET"},
                "description": {"type": "string", "description": "What this endpoint does (for comments)."}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "e2e_test_builder",
            "description": "Generate an end-to-end test template using Playwright or Cypress for a specific user flow.",
            "parameters": {"type": "object", "properties": {
                "framework":  {"type": "string", "description": "playwright | cypress. Default: playwright"},
                "flow_name":  {"type": "string", "description": "Name of the user flow (e.g. user_registration). Default: user_flow"},
                "steps":      {"type": "string", "description": "Comma-separated description of the flow steps."}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "regression_detector",
            "description": "Scan the codebase for fragile test patterns that commonly cause regressions: hard-coded sleeps, un-mocked datetime, global state, skipped tests, focused (.only) tests.",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string", "description": "Project root. Default: current directory."}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "coverage_analyzer",
            "description": "Run test coverage tools (pytest-cov for Python, jest/vitest --coverage for JS/TS) and return the coverage report with uncovered lines.",
            "parameters": {"type": "object", "properties": {
                "path":     {"type": "string", "description": "Project root. Default: current directory."},
                "language": {"type": "string", "description": "auto | python | javascript | typescript. Default: auto"}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "mutation_tester",
            "description": "Run mutation testing (mutmut for Python, Stryker for JS/TS) to validate that tests actually catch code changes. A surviving mutant = a gap in test coverage.",
            "parameters": {"type": "object", "properties": {
                "path":     {"type": "string", "description": "Project root. Default: current directory."},
                "language": {"type": "string", "description": "auto | python | javascript | typescript. Default: auto"}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "performance_tester",
            "description": "Generate a load test script for k6, Locust, or Artillery. Includes ramp-up stages, thresholds, and multiple request patterns.",
            "parameters": {"type": "object", "properties": {
                "tool":       {"type": "string", "description": "k6 | locust | artillery. Default: k6"},
                "target_url": {"type": "string", "description": "Base URL of the service to test. Default: http://localhost:8000"},
                "rps":        {"type": "integer", "description": "Target requests per second at peak. Default: 100"}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "test_data_generator",
            "description": "Generate realistic test fixtures for an entity in JSON, Python dicts, SQL INSERT, and pytest factory fixture formats.",
            "parameters": {"type": "object", "properties": {
                "entity_name": {"type": "string", "description": "Entity/model name (e.g. User, Order, Product)"},
                "fields":      {"type": "string", "description": "Comma-separated field names. Values are auto-inferred from names."},
                "count":       {"type": "integer", "description": "Number of records to generate (1-50). Default: 5"}
            }, "required": ["entity_name"]}
        }
    },
]

# ── Agent spec ────────────────────────────────────────────────────────────────

SPEC = {
    "name":        "QA & Testing Agent",
    "icon":        "\U0001f9ea",
    "color":       "#56d364",
    "description": "Test generation, execution, coverage analysis, mutation testing, load testing",

    "extra_tools":    _EXTRA_TOOLS,
    "extra_dispatch": {
        "unit_test_generator":    _unit_test_generator,
        "integration_test_builder": _integration_test_builder,
        "e2e_test_builder":       _e2e_test_builder,
        "regression_detector":    _regression_detector,
        "coverage_analyzer":      _coverage_analyzer,
        "mutation_tester":        _mutation_tester,
        "performance_tester":     _performance_tester,
        "test_data_generator":    _test_data_generator,
    },

    "system_prompt": """You are the QA & Testing Agent in a multi-agent development system.

YOUR ROLE: Write tests for all new and modified code, execute the test suite, validate quality, and catch regressions. You are the quality gate — nothing ships without your sign-off.

SPECIALIZED TOOLS:
- unit_test_generator(framework, module_name, functions) — generate complete unit test files
- integration_test_builder(framework, endpoint, method)  — API integration test templates
- e2e_test_builder(framework, flow_name, steps)          — Playwright/Cypress E2E templates
- regression_detector(path)                              — find fragile test patterns
- coverage_analyzer(path, language)                      — run and report coverage
- mutation_tester(path, language)                        — validate test quality with mutmut/Stryker
- performance_tester(tool, target_url, rps)              — k6/Locust/Artillery load tests
- test_data_generator(entity_name, fields, count)        — realistic fixtures in multiple formats
- web_search(query)                                      — look up testing patterns, framework docs

TESTING WORKFLOW:
1. Read project_context/execution_plan.md — understand what was changed
2. Read agent reports (backend_report.md, frontend_report.md, etc.)
3. regression_detector(.) — find existing fragile patterns first
4. Read each modified source file before writing its tests
5. unit_test_generator → write unit tests for every new function/class
6. integration_test_builder → test every new/modified API endpoint
7. e2e_test_builder → test critical user flows end-to-end
8. coverage_analyzer → run coverage; flag any critical path below 80%
9. mutation_tester → run mutation testing on core business logic
10. Write your Test Report

RULES:
- ALWAYS read the source file before writing tests for it
- Test behavior, not implementation — tests should survive refactoring
- Every test must have a clear name that describes what it tests
- Include: happy path, error cases, boundary conditions, auth checks
- NEVER mark a test as passing without actually running it (use run_shell)
- If coverage < 80% on new code — this is a FAIL

OUTPUT:
Write Test Report to project_context/test_report.md using write_file.
FIRST LINE must be: status: PASSED or status: FAILED
Include: tests written, tests run, pass/fail counts, coverage %, specific failure details."""
}
