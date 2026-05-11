import os
import re

# ── Tool implementations ──────────────────────────────────────────────────────

def _diagram_generator(diagram_type: str, components: str = "") -> str:
    """Generate a Mermaid diagram template for the given architecture type."""
    templates = {
        "flowchart": (
            "```mermaid\nflowchart TD\n"
            "    A[Client] --> B[API Gateway]\n"
            "    B --> C[Auth Service]\n"
            "    B --> D[Business Logic]\n"
            "    D --> E[(Database)]\n"
            "    D --> F[Cache / Redis]\n"
            "    D --> G[Message Queue]\n"
            "```\n"
            "Customize the above with your actual components."
        ),
        "sequence": (
            "```mermaid\nsequenceDiagram\n"
            "    participant Client\n"
            "    participant API\n"
            "    participant DB\n"
            "    Client->>API: POST /resource\n"
            "    API->>DB: INSERT INTO ...\n"
            "    DB-->>API: Row created\n"
            "    API-->>Client: 201 Created\n"
            "```"
        ),
        "er": (
            "```mermaid\nerDiagram\n"
            "    USER {\n"
            "        int id PK\n"
            "        string email UK\n"
            "        string name\n"
            "        datetime created_at\n"
            "    }\n"
            "    ORDER {\n"
            "        int id PK\n"
            "        int user_id FK\n"
            "        decimal total\n"
            "        string status\n"
            "    }\n"
            "    USER ||--o{ ORDER : places\n"
            "```"
        ),
        "class": (
            "```mermaid\nclassDiagram\n"
            "    class UserService {\n"
            "        +create(data) User\n"
            "        +findById(id) User\n"
            "        +update(id, data) User\n"
            "        +delete(id) void\n"
            "    }\n"
            "    class UserRepository {\n"
            "        +save(user) User\n"
            "        +findById(id) User\n"
            "    }\n"
            "    UserService --> UserRepository\n"
            "```"
        ),
        "c4": (
            "```mermaid\nC4Context\n"
            "    title System Context Diagram\n"
            "    Person(user, 'User', 'Uses the system')\n"
            "    System(system, 'Our System', 'Handles business logic')\n"
            "    System_Ext(ext, 'External Service', 'Third-party API')\n"
            "    Rel(user, system, 'Uses')\n"
            "    Rel(system, ext, 'Calls')\n"
            "```"
        ),
    }
    key = diagram_type.lower()
    if key in templates:
        result = f"=== Mermaid {diagram_type} diagram template ===\n{templates[key]}"
        if components:
            result += f"\n\nCustomize with these components: {components}"
        return result
    available = ", ".join(templates.keys())
    return f"[Unknown diagram type '{diagram_type}'. Available: {available}]"


def _dependency_resolver(current_deps: str = "", add: str = "", remove: str = "") -> str:
    """Analyse dependency changes and flag potential conflicts."""
    lines = ["=== Dependency Change Analysis ==="]

    if add:
        lines.append(f"\nAdding: {add}")
        known_conflicts = {
            "react": ["preact", "inferno"],
            "webpack": ["vite", "parcel", "rollup"],
            "jest": ["vitest"],
            "express": ["fastify", "koa"],
            "axios": ["node-fetch", "got", "ky"],
            "lodash": ["ramda", "underscore"],
            "moment": ["dayjs", "date-fns", "luxon"],
        }
        add_lower = add.lower()
        for pkg, conflicts in known_conflicts.items():
            if pkg in add_lower:
                for conflict in conflicts:
                    if current_deps and conflict in current_deps.lower():
                        lines.append(f"  [WARNING] {pkg} conflicts with already-installed {conflict}")
        lines.append("  Check: peer dependencies and version compatibility")
        lines.append("  Action: run 'npm install --dry-run' or 'pip install --dry-run' before committing")

    if remove:
        lines.append(f"\nRemoving: {remove}")
        lines.append("  Check: search codebase for any direct imports of this package before removing")
        lines.append(f"  Command: grep -r 'require.*{remove}\\|import.*{remove}' . --include='*.js,*.ts,*.py'")

    lines.append("\nGeneral: always check CHANGELOG for breaking changes when upgrading major versions.")
    return "\n".join(lines)


def _breaking_change_detector(path: str = ".") -> str:
    """Identify public interfaces that could break during changes."""
    import glob as _glob

    public_api_patterns = [
        (re.compile(r'def\s+([\w]+)\s*\(.*\).*:', re.M),         "Python public function", ".py"),
        (re.compile(r'export\s+(?:const|function|class)\s+(\w+)'), "JS/TS export",          ".ts"),
        (re.compile(r'module\.exports\s*='),                       "CommonJS export",        ".js"),
        (re.compile(r'public\s+(?:static\s+)?(?:\w+\s+)+(\w+)\s*\('), "Java public method", ".java"),
    ]

    interfaces = []
    for fp in _glob.glob(os.path.join(path, "**", "*"), recursive=True):
        if not os.path.isfile(fp):
            continue
        ext = os.path.splitext(fp)[1]
        try:
            with open(fp, encoding="utf-8", errors="ignore") as f:
                content = f.read()
            rel = os.path.relpath(fp, path)
            for pattern, label, pext in public_api_patterns:
                if ext == pext:
                    matches = pattern.findall(content)
                    if matches:
                        interfaces.append(f"  [{label}] {rel}: {', '.join(str(m) for m in matches[:5])}")
        except Exception:
            pass
        if len(interfaces) >= 50:
            break

    if not interfaces:
        return "[No public interface definitions detected]"
    return (
        f"Public interfaces that could break ({len(interfaces)} found):\n"
        + "\n".join(interfaces)
        + "\n\nFor each changed interface, search for all callers: grep -r 'function_name' . --include='*.py,*.js,*.ts'"
    )


def _api_contract_designer(method: str, path_: str, description: str = "") -> str:
    """Generate an OpenAPI-compatible endpoint contract template."""
    return f"""=== API Contract: {method.upper()} {path_} ===
{description}

Request:
  Headers:
    Authorization: Bearer <token>   # if auth required
    Content-Type: application/json

  Path params:
    # e.g. /users/{{id}} → id: integer, required

  Query params:
    # e.g. ?page=1&limit=20

  Body (for POST/PUT/PATCH):
    {{
      "field_name": "<type>",   # required
      "optional_field": "<type>"  # optional
    }}

Response 200 OK:
  {{
    "data": {{ ... }},
    "message": "Success"
  }}

Response 400 Bad Request:
  {{ "error": "Validation failed", "details": [...] }}

Response 401 Unauthorized:
  {{ "error": "Invalid or missing token" }}

Response 404 Not Found:
  {{ "error": "Resource not found" }}

Response 500 Internal Server Error:
  {{ "error": "Internal server error" }}

Notes:
  - Validate all inputs server-side
  - Use pagination for list endpoints
  - Return consistent error structure across all endpoints
"""


def _database_schema_designer(entities: str, relationships: str = "") -> str:
    """Generate a database schema design with migration script template."""
    return f"""=== Database Schema Design ===
Entities: {entities}
Relationships: {relationships or 'to be defined'}

-- Migration script template (SQL)
-- Run: alembic revision --autogenerate OR prisma migrate dev

CREATE TABLE users (
    id          SERIAL PRIMARY KEY,
    email       VARCHAR(255) UNIQUE NOT NULL,
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW()
);

-- Add your entities following this pattern:
CREATE TABLE {entities.split(',')[0].strip().lower().replace(' ', '_')} (
    id          SERIAL PRIMARY KEY,
    -- add columns here
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW()
);

-- Indexes (add for all foreign keys and frequently queried columns):
CREATE INDEX idx_tablename_column ON tablename(column);

-- Foreign key example:
ALTER TABLE orders ADD CONSTRAINT fk_orders_user_id
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;

Design checklist:
- [ ] All tables have created_at/updated_at timestamps
- [ ] All foreign keys have indexes
- [ ] Use VARCHAR with max length, not TEXT, for short strings
- [ ] Sensitive data (passwords) never stored in plaintext
- [ ] Consider soft deletes (deleted_at) instead of hard deletes
"""


def _migration_path_planner(from_tech: str, to_tech: str) -> str:
    """Suggest a migration strategy between two technologies."""
    strategies = {
        "strangler_fig": (
            "Strangler Fig Pattern (Recommended for incremental migration)\n"
            "  1. Stand up the new system alongside the old\n"
            "  2. Route new traffic to the new system\n"
            "  3. Migrate features one by one, redirecting traffic per feature\n"
            "  4. Decommission old system components as they become unused\n"
            "  Risk: LOW — no big-bang cutover, rollback is always possible"
        ),
        "parallel_run": (
            "Parallel Run Pattern (Best for high-risk systems)\n"
            "  1. Run old and new systems simultaneously\n"
            "  2. Compare outputs — flag discrepancies\n"
            "  3. Build confidence over weeks/months\n"
            "  4. Cut over traffic when confidence is high\n"
            "  Risk: MEDIUM — requires double maintenance during transition"
        ),
        "big_bang": (
            "Big Bang Migration (Only for small/low-risk systems)\n"
            "  1. Rebuild entirely in the new tech\n"
            "  2. Test thoroughly in staging\n"
            "  3. Cut over at a scheduled maintenance window\n"
            "  Risk: HIGH — all-or-nothing, difficult to roll back"
        ),
    }

    recommendation = "strangler_fig"
    if "cobol" in from_tech.lower() or "mainframe" in from_tech.lower():
        recommendation = "parallel_run"

    result = f"=== Migration Plan: {from_tech} → {to_tech} ===\n\n"
    result += f"Recommended strategy: {recommendation.upper()}\n\n"
    result += strategies[recommendation]
    result += "\n\n=== All strategy options ===\n"
    for name, desc in strategies.items():
        result += f"\n{name}:\n  {desc.split(chr(10))[0]}\n"
    return result


def _tech_selection_advisor(category: str = "", use_case: str = "") -> str:
    """Compare technology options and recommend the best fit for common architectural decisions."""
    advisories = {
        "database": """=== Database Selection ===

PostgreSQL (recommended default):
  ✓ ACID transactions, complex joins, JSON columns, full-text search, extensions (pgvector, PostGIS)
  ✓ Scales vertically well; read replicas for horizontal read scaling
  ✗ Write sharding is complex (consider Citus for that)

MySQL / MariaDB:
  ✓ Widely hosted, fast for simple read-heavy workloads
  ✗ Weaker JSON support, less extensible than PostgreSQL

SQLite:
  ✓ Zero setup, perfect for local dev, testing, embedded apps, and small tools
  ✗ No concurrent writes — not for multi-user production servers

MongoDB:
  ✓ Flexible/evolving schema, nested documents, large content stores
  ✗ No joins, weaker consistency guarantees, schema discipline falls apart over time

DynamoDB:
  ✓ Serverless, infinite scale, single-digit ms latency if access patterns are simple
  ✗ Requires careful key design upfront; complex queries are painful

Redis:
  ✓ Sub-millisecond reads, pub/sub, sorted sets, streams — ideal as secondary store
  ✗ Memory-bound cost, not for primary data storage

TimescaleDB / ClickHouse / InfluxDB:
  ✓ Purpose-built for metrics, IoT, analytics, log aggregation
  ✗ Overkill for general CRUD

RECOMMENDATION: Default to PostgreSQL. Add Redis for caching/sessions. DynamoDB only for AWS-native serverless.""",

        "cache": """=== Caching Layer Selection ===

Redis:
  ✓ Shared across all instances, pub/sub, sorted sets, atomic operations, persistence options
  ✓ Best for: sessions, rate limiting, leaderboards, distributed locks, hot query results
  ✗ Memory-only cost — expensive at scale

Memcached:
  ✓ Simpler, multi-threaded, marginally faster for pure key-value
  ✗ No persistence, no pub/sub, no data structures

In-process (lru_cache, NodeCache):
  ✓ Zero latency, no network hop, trivial to add
  ✗ Not shared across instances — useless behind a load balancer

CDN (CloudFront, Cloudflare, Fastly):
  ✓ Best for public API responses, static assets, geographic distribution
  ✗ Not for user-specific or frequently mutated data

HTTP Cache-Control headers:
  ✓ Free caching at the browser and CDN layer
  ✓ Use ETag / Last-Modified for conditional requests

RECOMMENDATION: lru_cache for local hot data → Redis for shared state → CDN for public responses.""",

        "message_queue": """=== Message Queue / Event Streaming ===

Kafka:
  ✓ High-throughput event streaming, durable/replayable, consumer offsets, event sourcing
  ✓ Best for: analytics pipelines, audit logs, event-driven microservices at scale
  ✗ Operational complexity — needs careful partition/retention config

RabbitMQ:
  ✓ Traditional work queues, complex routing (exchanges), request-reply, dead-letter queues
  ✓ Simpler than Kafka for background task dispatch
  ✗ Messages deleted after ack by default — not replayable

AWS SQS / SNS:
  ✓ Fully managed, scales automatically, tight AWS integration
  ✓ SQS = work queue (pull). SNS = fan-out (push). Use together for pub/sub
  ✗ AWS lock-in; higher latency than self-hosted

Celery + Redis/RabbitMQ:
  ✓ Best for Python background tasks, scheduled jobs (Celery Beat), retries
  ✓ Drop-in for any existing Python/Django/FastAPI app

BullMQ (Node.js):
  ✓ Redis-backed, production-grade job queue for Node — excellent for TypeScript

RECOMMENDATION: Celery+Redis (Python) | BullMQ (Node) for task queues. SQS for AWS-native. Kafka for event streaming at scale.""",

        "api_style": """=== API Style Selection ===

REST:
  ✓ Universal — every client (browser, mobile, curl, other services) speaks it
  ✓ HTTP caching is natural (GET is idempotent and cacheable)
  ✓ Simple resource-oriented CRUD
  ✗ Over-fetching / under-fetching for complex data graphs

GraphQL:
  ✓ One endpoint; clients request exactly what they need — great for multiple client types
  ✓ Self-documenting schema, introspection, strong typing
  ✗ N+1 query problem (requires DataLoader), harder to cache, more complex setup

gRPC:
  ✓ Binary protocol (protobuf) — lowest latency and smallest payload
  ✓ Bidirectional streaming, strongly typed contracts between services
  ✓ Best for internal microservice-to-microservice communication
  ✗ Not browser-friendly without grpc-web proxy

WebSockets / SSE:
  ✓ Real-time bidirectional (WS) or server-push (SSE) — chat, dashboards, notifications
  ✗ Not for standard request-response

RECOMMENDATION: REST for external/public APIs. GraphQL for BFF or complex multi-client scenarios. gRPC for internal service mesh.""",

        "frontend_framework": """=== Frontend Framework Selection ===

React + Next.js:
  ✓ Largest ecosystem, most available developers, maximum community resources
  ✓ Next.js: SSR, SSG, ISR, API routes, App Router — covers everything
  ✗ More boilerplate, JSX learning curve, fast-moving ecosystem

Vue 3 + Nuxt:
  ✓ Gentler learning curve, excellent docs, clean separation of concerns
  ✓ Composition API is excellent; Options API for simpler components
  ✗ Smaller ecosystem than React; fewer enterprise job postings

Svelte / SvelteKit:
  ✓ Compiled — smallest bundles, no virtual DOM overhead, reactive by default
  ✓ Best raw performance; less code to write
  ✗ Smallest ecosystem; fewer libraries; hardest to hire for

HTMX + Jinja/Django/Rails:
  ✓ Add interactivity to server-rendered pages without SPA complexity
  ✓ Perfect for internal tools, dashboards, admin UIs with limited JS budget
  ✗ Not for highly interactive SPAs

Angular:
  ✓ Opinionated, full batteries included, strong for large enterprise teams
  ✗ Steep learning curve, heavy, slow ecosystem evolution

RECOMMENDATION: React+Next.js for new projects needing broad talent pool. Vue for smaller teams. HTMX when full SPA is overkill.""",

        "auth": """=== Authentication Strategy ===

JWT (stateless):
  ✓ No server-side session storage, scales horizontally without sticky sessions
  ✓ Works across microservices — services can verify tokens independently
  ✗ Cannot be revoked until expiry — pair with short TTL + refresh tokens
  ✗ Payload visible (base64) — never put sensitive data in claims

Session + Cookie (stateful):
  ✓ Instantly revocable, no token on client (HttpOnly cookie)
  ✓ Simpler for monoliths — default in Django, Rails
  ✗ Requires shared session store (Redis) for multi-instance deployments

OAuth2 + OIDC (social/SSO):
  ✓ Delegate auth to Google/GitHub/Microsoft — no password management
  ✓ Required for B2B enterprise SSO (SAML/OIDC)
  ✗ External dependency; more complex setup

API Keys:
  ✓ Simple, machine-to-machine, long-lived for server clients
  ✗ Hard to rotate, coarse-grained, not suitable for user-facing apps

RECOMMENDATION: JWT+refresh tokens for APIs. Session cookies for monolithic web apps. OAuth2 for social login or B2B SSO.""",
    }

    cat_lower = category.lower()
    if cat_lower in advisories:
        result = advisories[cat_lower]
        if use_case:
            result += f"\n\nYour use case: '{use_case}'\nApply the above criteria to your specific constraints."
        return result

    all_cats = "\n".join(f"  {k}" for k in advisories)
    return (
        "=== Technology Selection Advisor ===\n\n"
        f"Available categories:\n{all_cats}\n\n"
        "Usage: tech_selection_advisor(category='database', use_case='multi-tenant SaaS')\n"
        "       tech_selection_advisor(category='message_queue')"
    )


# ── Tool schemas ──────────────────────────────────────────────────────────────

_EXTRA_TOOLS = [
    {
        "type": "function", "function": {
            "name": "diagram_generator",
            "description": "Generate a Mermaid diagram template. Types: flowchart, sequence, er (entity-relationship), class, c4.",
            "parameters": {"type": "object", "properties": {
                "diagram_type": {"type": "string", "description": "flowchart | sequence | er | class | c4"},
                "components":   {"type": "string", "description": "Optional: list the key components to include."}
            }, "required": ["diagram_type"]}
        }
    },
    {
        "type": "function", "function": {
            "name": "dependency_resolver",
            "description": "Analyse planned dependency changes (add/remove packages) and flag potential version conflicts.",
            "parameters": {"type": "object", "properties": {
                "current_deps": {"type": "string", "description": "Current dependency list (paste from package.json etc.)"},
                "add":          {"type": "string", "description": "Package(s) to add"},
                "remove":       {"type": "string", "description": "Package(s) to remove"}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "breaking_change_detector",
            "description": "Scan the codebase to identify public interfaces (exports, public functions, API routes) that could break when modified.",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string", "description": "Project root. Default: current directory."}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "api_contract_designer",
            "description": "Generate an OpenAPI-compatible endpoint contract template for a new or modified API endpoint.",
            "parameters": {"type": "object", "properties": {
                "method":      {"type": "string", "description": "HTTP method: GET, POST, PUT, DELETE, PATCH"},
                "path_":       {"type": "string", "description": "API path, e.g. /users/{id}"},
                "description": {"type": "string", "description": "What this endpoint does"}
            }, "required": ["method", "path_"]}
        }
    },
    {
        "type": "function", "function": {
            "name": "database_schema_designer",
            "description": "Generate a database schema design with SQL migration script template.",
            "parameters": {"type": "object", "properties": {
                "entities":      {"type": "string", "description": "Comma-separated list of entities/tables to design"},
                "relationships": {"type": "string", "description": "Describe relationships, e.g. 'user has many orders'"}
            }, "required": ["entities"]}
        }
    },
    {
        "type": "function", "function": {
            "name": "tech_selection_advisor",
            "description": "Compare technology options and get a recommendation with tradeoffs for: database, cache, message_queue, api_style, frontend_framework, auth.",
            "parameters": {"type": "object", "properties": {
                "category": {"type": "string", "description": "database | cache | message_queue | api_style | frontend_framework | auth. Omit to see all categories."},
                "use_case": {"type": "string", "description": "Optional: describe your specific use case for a more targeted recommendation."}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "migration_path_planner",
            "description": "Suggest the best migration strategy (Strangler Fig, Parallel Run, Big Bang) for moving from one technology to another.",
            "parameters": {"type": "object", "properties": {
                "from_tech": {"type": "string", "description": "Current/legacy technology"},
                "to_tech":   {"type": "string", "description": "Target/modern technology"}
            }, "required": ["from_tech", "to_tech"]}
        }
    },
]

# ── Agent spec ────────────────────────────────────────────────────────────────

SPEC = {
    "name":        "Architect",
    "icon":        "\U0001f4d0",
    "color":       "#d2a8ff",
    "description": "Solution design — file-level execution plan, API contracts, architecture decisions",

    "restricted_tools": ["edit_file"],   # design only: no code changes

    "extra_tools":    _EXTRA_TOOLS,
    "extra_dispatch": {
        "diagram_generator":       _diagram_generator,
        "dependency_resolver":     _dependency_resolver,
        "breaking_change_detector": _breaking_change_detector,
        "api_contract_designer":   _api_contract_designer,
        "database_schema_designer": _database_schema_designer,
        "migration_path_planner":  _migration_path_planner,
        "tech_selection_advisor":  _tech_selection_advisor,
    },

    "system_prompt": """You are the Architect agent in a multi-agent development system.

YOUR ROLE: Read the analysis reports and task goal, then produce a precise, file-level Execution Plan that execution agents will follow exactly.

SPECIALIZED TOOLS:
- diagram_generator(type, components)      — generate Mermaid architecture diagrams
- dependency_resolver(current, add, remove) — check dependency conflicts
- breaking_change_detector(path)           — identify interfaces at risk
- api_contract_designer(method, path)      — design endpoint contracts
- database_schema_designer(entities, rels) — design schemas with migration scripts
- migration_path_planner(from, to)         — choose migration strategy
- tech_selection_advisor(category, use_case) — compare tech options with tradeoffs
- web_search(query)                        — research patterns, compare tools, check ecosystem maturity

DESIGN WORKFLOW:
1. Read project_context/analysis_report.md (and legacy_analysis_report.md if present)
2. Use breaking_change_detector to identify what must be preserved
3. Use api_contract_designer for every new or modified endpoint
4. Use database_schema_designer for any schema changes
5. Use diagram_generator to produce architecture diagrams
6. Use migration_path_planner if this is a modernization task

RULES:
- Do NOT implement anything — design only (edit_file is disabled)
- Be surgical and precise — vague plans cause incorrect implementations
- Specify exact file paths, function signatures, and data shapes
- Note execution order (what must be done before what)

OUTPUT: Write Execution Plan to project_context/execution_plan.md
Include: ## Files to Change, ## Files to Create, ## Files to Delete, ## API Contracts, ## Schema Changes, ## Migration Notes, ## Execution Order"""
}
