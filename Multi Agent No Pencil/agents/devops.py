import os

# ── Tool implementations ──────────────────────────────────────────────────────

def _dockerfile_optimizer(base_image: str = "python:3.12-slim",
                           app_type: str = "python") -> str:
    """Return an optimized multi-stage Dockerfile template."""
    templates = {
        "python": f"""# ── Optimized multi-stage Python Dockerfile ──
# Builder stage
FROM {base_image} AS builder
WORKDIR /app

# Install dependencies in a layer that only rebuilds when deps change
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Runtime stage — minimal image
FROM {base_image}
WORKDIR /app

# Non-root user for security
RUN addgroup --system app && adduser --system --group app

# Copy dependencies from builder
COPY --from=builder /root/.local /home/app/.local
ENV PATH=/home/app/.local/bin:$PATH

# Copy application code last (changes most often → invalidates fewest cached layers)
COPY --chown=app:app . .

USER app
EXPOSE 8000

# Use exec form (not shell form) so signals propagate correctly
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
""",
        "node": """# ── Optimized multi-stage Node.js Dockerfile ──
# Builder stage
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci --only=production && npm cache clean --force

# Runtime stage
FROM node:20-alpine
WORKDIR /app
RUN addgroup -S app && adduser -S app -G app

COPY --from=builder --chown=app:app /app/node_modules ./node_modules
COPY --chown=app:app . .

USER app
EXPOSE 3000
CMD ["node", "src/index.js"]
""",
        "go": """# ── Optimized multi-stage Go Dockerfile ──
FROM golang:1.22-alpine AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-w -s" -o /app/server ./cmd/server

# Final stage — scratch or distroless for minimum size
FROM gcr.io/distroless/static-debian12
COPY --from=builder /app/server /server
EXPOSE 8080
CMD ["/server"]
""",
    }
    key = app_type.lower()
    tmpl = templates.get(key, templates["python"])
    return f"=== Optimized {app_type} Dockerfile ===\n\n{tmpl}\n\nChecklist:\n  - Specific version tags (not :latest)\n  - Multi-stage build to minimize final image\n  - Non-root user (security)\n  - Dependencies copied before app code (layer caching)\n  - CMD uses exec form (signal handling)"


def _ci_cd_builder(platform: str = "github_actions",
                   stack: str = "python") -> str:
    """Generate a CI/CD pipeline YAML for the given platform and stack."""
    if "github" in platform.lower():
        if "python" in stack.lower():
            return """# .github/workflows/ci.yml
name: CI/CD

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12"]

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
          cache: pip

      - name: Install dependencies
        run: pip install -r requirements.txt -r requirements-dev.txt

      - name: Lint (ruff)
        run: ruff check .

      - name: Type check (mypy)
        run: mypy .

      - name: Test (pytest + coverage)
        run: pytest --cov=. --cov-report=xml --cov-fail-under=80

      - name: Upload coverage
        uses: codecov/codecov-action@v4
        with:
          file: ./coverage.xml

  build-and-push:
    needs: test
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build and push Docker image
        uses: docker/build-push-action@v5
        with:
          push: true
          tags: ghcr.io/${{ github.repository }}:${{ github.sha }},ghcr.io/${{ github.repository }}:latest
          cache-from: type=gha
          cache-to: type=gha,mode=max
"""
        elif "node" in stack.lower():
            return """# .github/workflows/ci.yml
name: CI/CD

on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: npm

      - run: npm ci

      - name: Lint
        run: npm run lint

      - name: Type check
        run: npm run type-check

      - name: Test
        run: npm test -- --coverage

  deploy:
    needs: test
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: docker/build-push-action@v5
        with:
          push: true
          tags: ghcr.io/${{ github.repository }}:latest
"""
    return f"[No CI template for '{platform}/{stack}'. Available: github_actions/python, github_actions/node]"


def _kubernetes_handler(resource_type: str = "deployment",
                         app_name: str = "myapp",
                         port: int = 8000) -> str:
    """Generate a Kubernetes manifest template."""
    templates = {
        "deployment": f"""# k8s/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {app_name}
  labels:
    app: {app_name}
spec:
  replicas: 3
  selector:
    matchLabels:
      app: {app_name}
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  template:
    metadata:
      labels:
        app: {app_name}
    spec:
      containers:
        - name: {app_name}
          image: ghcr.io/org/{app_name}:latest
          ports:
            - containerPort: {port}
          env:
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: {app_name}-secrets
                  key: database-url
          resources:
            requests:
              memory: "128Mi"
              cpu: "100m"
            limits:
              memory: "512Mi"
              cpu: "500m"
          livenessProbe:
            httpGet:
              path: /health
              port: {port}
            initialDelaySeconds: 30
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /ready
              port: {port}
            initialDelaySeconds: 5
            periodSeconds: 5
          securityContext:
            runAsNonRoot: true
            readOnlyRootFilesystem: true
            allowPrivilegeEscalation: false
""",
        "service": f"""# k8s/service.yaml
apiVersion: v1
kind: Service
metadata:
  name: {app_name}
spec:
  selector:
    app: {app_name}
  ports:
    - port: 80
      targetPort: {port}
  type: ClusterIP
""",
        "ingress": f"""# k8s/ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {app_name}
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
    nginx.ingress.kubernetes.io/rate-limit: "100"
spec:
  tls:
    - hosts:
        - {app_name}.yourdomain.com
      secretName: {app_name}-tls
  rules:
    - host: {app_name}.yourdomain.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: {app_name}
                port:
                  number: 80
""",
        "hpa": f"""# k8s/hpa.yaml — Horizontal Pod Autoscaler
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: {app_name}
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: {app_name}
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
""",
    }
    tmpl = templates.get(resource_type.lower())
    if tmpl:
        return tmpl
    available = ", ".join(templates.keys())
    return f"[Unknown resource type '{resource_type}'. Available: {available}]"


def _environment_manager(action: str = "template", env_name: str = "production") -> str:
    """Help with environment config: .env templates, secrets management guidance."""
    if action.lower() == "template":
        return f"""# .env.{env_name} — Environment configuration template
# Copy this to .env and fill in real values
# NEVER commit .env to version control (add to .gitignore)

# Application
APP_ENV={env_name}
APP_DEBUG=false
APP_SECRET_KEY=CHANGE_ME_generate_with_secrets.token_hex_32

# Database
DATABASE_URL=postgresql://user:password@host:5432/dbname
DATABASE_POOL_SIZE=10
DATABASE_MAX_OVERFLOW=20

# Redis / Cache
REDIS_URL=redis://localhost:6379/0
CACHE_TTL=300

# Auth
JWT_SECRET=CHANGE_ME_generate_with_secrets.token_hex_32
JWT_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7

# External APIs (never hardcode values — use secrets manager in production)
STRIPE_SECRET_KEY=
SENDGRID_API_KEY=
SENTRY_DSN=

# .gitignore additions:
# .env
# .env.{env_name}
# *.env

# Production recommendation: use AWS Secrets Manager, Vault, or Doppler
# Never use .env files in production — inject via container environment
"""
    elif action.lower() == "secrets_guidance":
        return """=== Secrets Management Best Practices ===

DO:
  - Use environment variables injected at runtime
  - Use a secrets manager in production:
      AWS: AWS Secrets Manager or SSM Parameter Store
      GCP: Secret Manager
      HashiCorp Vault (self-hosted)
      Doppler (SaaS, easiest setup)
  - Rotate secrets regularly (set expiry)
  - Audit secret access logs

DON'T:
  - Commit .env files to version control
  - Hardcode secrets in source code
  - Log secrets or include them in error messages
  - Use the same secret across environments

Kubernetes secrets:
  kubectl create secret generic app-secrets \\
    --from-literal=db-password='...' \\
    --from-literal=api-key='...'
  # Reference in pod spec: secretKeyRef
"""
    return f"[Unknown action '{action}'. Options: template, secrets_guidance]"


def _nginx_configurator(app_type: str = "reverse_proxy", port: int = 8000,
                         domain: str = "yourdomain.com") -> str:
    """Generate an Nginx configuration template."""
    if "reverse_proxy" in app_type.lower():
        return f"""# /etc/nginx/sites-available/{domain}
server {{
    listen 80;
    server_name {domain} www.{domain};
    # Redirect HTTP → HTTPS
    return 301 https://$host$request_uri;
}}

server {{
    listen 443 ssl http2;
    server_name {domain} www.{domain};

    ssl_certificate     /etc/letsencrypt/live/{domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{domain}/privkey.pem;

    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options SAMEORIGIN always;
    add_header X-Content-Type-Options nosniff always;
    add_header Referrer-Policy strict-origin-when-cross-origin always;

    # Rate limiting
    limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;

    location / {{
        limit_req zone=api burst=20 nodelay;
        proxy_pass http://localhost:{port};
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket support
        proxy_http_version 1.1;
        proxy_set_header Upgrade    $http_upgrade;
        proxy_set_header Connection "upgrade";

        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout    60s;
        proxy_read_timeout    60s;
    }}

    # Static files (if any)
    location /static/ {{
        alias /var/www/{domain}/static/;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }}
}}
"""
    return f"[Unknown app_type '{app_type}'. Options: reverse_proxy, static, spa]"


def _terraform_handler(provider: str = "aws", resource_type: str = "ecs") -> str:
    """Generate Terraform IaC templates for common cloud resources."""
    templates = {
        ("aws", "ecs"): """# Terraform — AWS ECS Fargate Service
# Run: terraform init && terraform plan && terraform apply

terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
  backend "s3" {
    bucket = "your-tfstate-bucket"
    key    = "app/terraform.tfstate"
    region = "us-east-1"
  }
}

provider "aws" {
  region = var.aws_region
}

variable "app_name"   { default = "myapp" }
variable "aws_region" { default = "us-east-1" }
variable "image_uri"  { description = "ECR image URI" }

# ECS Cluster
resource "aws_ecs_cluster" "main" {
  name = var.app_name
  setting { name = "containerInsights" value = "enabled" }
}

# Task Definition
resource "aws_ecs_task_definition" "app" {
  family                   = var.app_name
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn

  container_definitions = jsonencode([{
    name      = var.app_name
    image     = var.image_uri
    portMappings = [{ containerPort = 8000, protocol = "tcp" }]
    environment  = [{ name = "APP_ENV", value = "production" }]
    secrets      = [{ name = "DATABASE_URL", valueFrom = aws_ssm_parameter.db_url.arn }]
    logConfiguration = {
      logDriver = "awslogs"
      options   = { "awslogs-group" = "/ecs/${var.app_name}", "awslogs-region" = var.aws_region, "awslogs-stream-prefix" = "ecs" }
    }
  }])
}

# ECS Service
resource "aws_ecs_service" "app" {
  name            = var.app_name
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.app.arn
  desired_count   = 2
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.ecs.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.app.arn
    container_name   = var.app_name
    container_port   = 8000
  }
}""",

        ("aws", "rds"): """# Terraform — AWS RDS PostgreSQL
resource "aws_db_subnet_group" "main" {
  name       = "${var.app_name}-db-subnet"
  subnet_ids = var.private_subnet_ids
}

resource "aws_db_instance" "postgres" {
  identifier              = "${var.app_name}-db"
  engine                  = "postgres"
  engine_version          = "16.1"
  instance_class          = "db.t3.micro"
  allocated_storage       = 20
  max_allocated_storage   = 100   # auto-scaling storage
  storage_encrypted       = true
  db_name                 = var.app_name
  username                = "dbadmin"
  password                = random_password.db.result
  db_subnet_group_name    = aws_db_subnet_group.main.name
  vpc_security_group_ids  = [aws_security_group.rds.id]
  multi_az                = true    # production HA
  backup_retention_period = 7
  deletion_protection     = true
  skip_final_snapshot     = false
  final_snapshot_identifier = "${var.app_name}-final-snapshot"

  tags = { Name = "${var.app_name}-postgres" }
}

resource "random_password" "db" {
  length  = 24
  special = false
}

resource "aws_ssm_parameter" "db_url" {
  name  = "/${var.app_name}/DATABASE_URL"
  type  = "SecureString"
  value = "postgresql://${aws_db_instance.postgres.username}:${random_password.db.result}@${aws_db_instance.postgres.endpoint}/${var.app_name}"
}""",

        ("gcp", "cloud_run"): """# Terraform — GCP Cloud Run
provider "google" {
  project = var.gcp_project
  region  = "us-central1"
}

variable "gcp_project" { description = "GCP Project ID" }
variable "image_uri"   { description = "Container image URI (e.g. gcr.io/project/app:latest)" }

resource "google_cloud_run_service" "app" {
  name     = "myapp"
  location = "us-central1"

  template {
    spec {
      containers {
        image = var.image_uri
        ports { container_port = 8080 }
        resources { limits = { cpu = "1000m", memory = "512Mi" } }
        env {
          name  = "DATABASE_URL"
          value_from {
            secret_key_ref { name = "database-url", key = "latest" }
          }
        }
      }
    }
    metadata {
      annotations = {
        "autoscaling.knative.dev/maxScale" = "10"
        "autoscaling.knative.dev/minScale" = "1"
      }
    }
  }

  traffic {
    percent         = 100
    latest_revision = true
  }
}

# Allow unauthenticated (public) access:
resource "google_cloud_run_service_iam_member" "public" {
  service  = google_cloud_run_service.app.name
  location = google_cloud_run_service.app.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}

output "url" {
  value = google_cloud_run_service.app.status[0].url
}""",
    }

    key = (provider.lower(), resource_type.lower())
    tmpl = templates.get(key)
    if tmpl:
        return f"=== Terraform: {provider.upper()} {resource_type.upper()} ===\n\n{tmpl}"

    available = [f"{p}/{r}" for p, r in templates.keys()]
    return (
        f"[No Terraform template for '{provider}/{resource_type}']. "
        f"Available: {', '.join(available)}\n\n"
        "General Terraform best practices:\n"
        "  - Store state in S3+DynamoDB (AWS) or GCS (GCP) — never local\n"
        "  - Use workspaces or separate state files per environment\n"
        "  - Pin provider versions with ~> to avoid breaking changes\n"
        "  - Use terraform plan -out=plan.tfplan before apply\n"
        "  - Tag all resources for cost allocation\n"
        "  - Use data sources to reference existing resources"
    )


def _database_ops_handler(operation: str = "backup", db_type: str = "postgresql") -> str:
    """Return database backup, migration, and restore scripts."""
    if "postgres" in db_type.lower() or "pg" in db_type.lower():
        ops = {
            "backup": """=== PostgreSQL Backup Scripts ===

# One-off backup (pg_dump):
pg_dump $DATABASE_URL -Fc -Z9 -f backup_$(date +%Y%m%d_%H%M%S).dump

# Restore from dump:
pg_restore -d $DATABASE_URL --clean --if-exists backup.dump

# backup.sh — automated daily backup to S3:
#!/bin/bash
set -e
DATE=$(date +%Y%m%d_%H%M%S)
FILENAME="backup_${DATE}.dump"

pg_dump $DATABASE_URL -Fc -Z9 -f /tmp/$FILENAME
aws s3 cp /tmp/$FILENAME s3://$BACKUP_BUCKET/postgres/$FILENAME
rm /tmp/$FILENAME

# Prune backups older than 30 days:
aws s3 ls s3://$BACKUP_BUCKET/postgres/ | \\
  awk '{print $4}' | \\
  while read key; do
    created=$(aws s3api head-object --bucket $BACKUP_BUCKET --key "postgres/$key" \\
              --query 'LastModified' --output text)
    if [[ $(date -d "$created" +%s) -lt $(date -d '30 days ago' +%s) ]]; then
      aws s3 rm "s3://$BACKUP_BUCKET/postgres/$key"
    fi
  done

# Cron (daily at 2am):
# 0 2 * * * /opt/scripts/backup.sh >> /var/log/db-backup.log 2>&1""",

            "migration": """=== PostgreSQL Migration Runner ===

# Alembic (Python):
alembic init alembic
alembic revision --autogenerate -m "add users table"
alembic upgrade head
alembic downgrade -1     # roll back one migration
alembic history          # show applied migrations

# alembic/env.py key config:
from myapp.models import Base  # your SQLAlchemy models
target_metadata = Base.metadata

# Flyway (Java/SQL):
# Place SQL files in db/migration/ with naming V1__create_users.sql, V2__add_email.sql
flyway -url=jdbc:postgresql://host/db -user=user -password=pass migrate
flyway info    # show migration status
flyway repair  # fix failed migrations

# Raw SQL migration script with transaction safety:
BEGIN;

ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(20);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_phone ON users(phone);

UPDATE schema_migrations SET version = '002' WHERE id = 1;

COMMIT;""",

            "restore": """=== PostgreSQL Point-in-Time Restore ===

# Restore from pg_dump:
pg_restore -d $DATABASE_URL --clean --if-exists backup.dump

# AWS RDS Point-in-Time Restore (console or CLI):
aws rds restore-db-instance-to-point-in-time \\
  --source-db-instance-identifier myapp-db \\
  --target-db-instance-identifier myapp-db-restored \\
  --restore-time 2024-01-15T14:00:00Z

# After restore — reconnect and validate:
psql $DATABASE_URL -c "SELECT COUNT(*) FROM users;"
psql $DATABASE_URL -c "SELECT MAX(created_at) FROM orders;" """,
        }
        key = operation.lower()
        if key in ops:
            return ops[key]
        return (
            f"=== PostgreSQL Operations — Available: {', '.join(ops.keys())} ===\n\n"
            + "\n\n---\n\n".join(f"[{k}]\n{v[:300]}..." for k, v in ops.items())
        )

    elif "mysql" in db_type.lower() or "mariadb" in db_type.lower():
        if operation.lower() == "backup":
            return """=== MySQL / MariaDB Backup ===

# mysqldump (logical backup):
mysqldump -h $DB_HOST -u $DB_USER -p$DB_PASS $DB_NAME \\
  --single-transaction --routines --triggers \\
  | gzip > backup_$(date +%Y%m%d).sql.gz

# Restore:
gunzip -c backup.sql.gz | mysql -h $DB_HOST -u $DB_USER -p$DB_PASS $DB_NAME

# Percona XtraBackup (hot physical backup for large DBs):
xtrabackup --backup --target-dir=/backup/xtrabackup
xtrabackup --prepare --target-dir=/backup/xtrabackup"""
        return f"[MySQL template for '{operation}' not available. Use 'backup' operation]"

    return f"[No database ops template for '{db_type}'. Options: postgresql, mysql]"


def _performance_monitor_setup(platform: str = "prometheus", stack: str = "python") -> str:
    """Return monitoring, metrics, and alerting setup templates."""
    if "prometheus" in platform.lower() or "grafana" in platform.lower():
        py_code = ""
        if "python" in stack.lower():
            py_code = """
# Python / FastAPI metrics (prometheus_fastapi_instrumentator):
# Install: pip install prometheus-fastapi-instrumentator
from prometheus_fastapi_instrumentator import Instrumentator

Instrumentator().instrument(app).expose(app, endpoint="/metrics")

# Custom metrics:
from prometheus_client import Counter, Histogram, Gauge

REQUEST_COUNT   = Counter('app_requests_total', 'Total requests', ['method', 'endpoint', 'status'])
REQUEST_LATENCY = Histogram('app_request_duration_seconds', 'Request latency')
ACTIVE_USERS    = Gauge('app_active_users', 'Currently active users')

@app.middleware("http")
async def metrics_middleware(request, call_next):
    start = time.time()
    response = await call_next(request)
    REQUEST_COUNT.labels(request.method, request.url.path, response.status_code).inc()
    REQUEST_LATENCY.observe(time.time() - start)
    return response"""
        elif "node" in stack.lower():
            py_code = """
// Node.js metrics (prom-client):
// Install: npm install prom-client
const client = require('prom-client')
client.collectDefaultMetrics()  // CPU, memory, event loop lag

const httpRequests = new client.Counter({
  name: 'http_requests_total',
  help: 'Total HTTP requests',
  labelNames: ['method', 'route', 'status_code']
})

app.get('/metrics', async (req, res) => {
  res.set('Content-Type', client.register.contentType)
  res.send(await client.register.metrics())
})"""

        return f"""=== Prometheus + Grafana Monitoring ==={py_code}

# docker-compose.monitoring.yml:
services:
  prometheus:
    image: prom/prometheus:latest
    ports: ["9090:9090"]
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
    command: --config.file=/etc/prometheus/prometheus.yml

  grafana:
    image: grafana/grafana:latest
    ports: ["3001:3000"]
    environment:
      GF_SECURITY_ADMIN_PASSWORD: admin
    volumes:
      - grafana_data:/var/lib/grafana

# prometheus.yml:
global:
  scrape_interval: 15s
scrape_configs:
  - job_name: 'myapp'
    static_configs:
      - targets: ['app:8000']   # or your app host:port
    metrics_path: /metrics

# Key Grafana dashboards to import:
#   1756  — Node.js metrics
#   10427 — FastAPI / Python metrics
#   7362  — PostgreSQL database metrics
#   3662  — Prometheus 2.0 overview"""

    elif "sentry" in platform.lower():
        if "python" in stack.lower():
            return """=== Sentry Error Monitoring — Python ===
# Install: pip install sentry-sdk[fastapi]

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

sentry_sdk.init(
    dsn=os.getenv("SENTRY_DSN"),
    environment=os.getenv("APP_ENV", "development"),
    traces_sample_rate=0.2,       # 20% of transactions for performance
    profiles_sample_rate=0.1,     # 10% profiling
    integrations=[
        FastApiIntegration(transaction_style="endpoint"),
        SqlalchemyIntegration(),
    ],
    before_send=lambda event, hint: None if os.getenv("APP_ENV") == "development" else event,
)

# Manual error capture:
try:
    risky_operation()
except Exception as e:
    sentry_sdk.capture_exception(e)

# Add user context:
with sentry_sdk.configure_scope() as scope:
    scope.set_user({"id": user.id, "email": user.email})"""
        elif "node" in stack.lower():
            return """=== Sentry Error Monitoring — Node.js ===
// Install: npm install @sentry/node @sentry/profiling-node

const Sentry = require('@sentry/node')

Sentry.init({
  dsn:                process.env.SENTRY_DSN,
  environment:        process.env.NODE_ENV,
  tracesSampleRate:   0.2,
  profilesSampleRate: 0.1,
})

// Express — add FIRST before routes:
app.use(Sentry.Handlers.requestHandler())
app.use(Sentry.Handlers.tracingHandler())

// Express — add LAST before error handler:
app.use(Sentry.Handlers.errorHandler())"""

    elif "datadog" in platform.lower():
        return """=== Datadog APM + Metrics ===
# Python: pip install ddtrace
# Instrument at startup (before imports):
# ddtrace-run python main.py

# Or manual init:
from ddtrace import patch_all, tracer
patch_all()  # auto-instrument FastAPI, SQLAlchemy, Redis, etc.

# Custom spans:
with tracer.trace("my_operation", service="myapp") as span:
    span.set_tag("user.id", user_id)
    result = do_work()

# datadog-agent docker-compose service:
  datadog:
    image: datadog/agent:latest
    environment:
      DD_API_KEY: ${DD_API_KEY}
      DD_SITE:    datadoghq.com
      DD_APM_ENABLED: "true"
      DD_LOGS_ENABLED: "true"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - /proc/:/host/proc/:ro
      - /sys/fs/cgroup/:/host/sys/fs/cgroup:ro"""

    elif "opentelemetry" in platform.lower() or "otel" in platform.lower():
        return """=== OpenTelemetry (Vendor-Neutral Observability) ===
# Python: pip install opentelemetry-distro opentelemetry-exporter-otlp
# Auto-instrument: opentelemetry-instrument python main.py

from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

provider = TracerProvider()
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(
    endpoint="http://otel-collector:4317"  # send to collector
)))
trace.set_tracer_provider(provider)

tracer = trace.get_tracer(__name__)

@app.get("/users")
async def list_users():
    with tracer.start_as_current_span("list-users") as span:
        span.set_attribute("db.query", "SELECT * FROM users")
        return await get_users()

# OpenTelemetry Collector → routes to Prometheus, Jaeger, Datadog, etc.
# docker-compose:
  otel-collector:
    image: otel/opentelemetry-collector-contrib:latest
    volumes:
      - ./otel-collector-config.yaml:/etc/otelcol/config.yaml"""

    return f"[No monitoring template for '{platform}'. Options: prometheus, sentry, datadog, opentelemetry]"


# ── Tool schemas ──────────────────────────────────────────────────────────────

_EXTRA_TOOLS = [
    {
        "type": "function", "function": {
            "name": "dockerfile_optimizer",
            "description": "Generate an optimized multi-stage Dockerfile with security best practices: non-root user, minimal image, proper layer ordering.",
            "parameters": {"type": "object", "properties": {
                "base_image": {"type": "string", "description": "Base Docker image (e.g. python:3.12-slim). Default: python:3.12-slim"},
                "app_type":   {"type": "string", "description": "python | node | go. Default: python"}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "ci_cd_builder",
            "description": "Generate a CI/CD pipeline YAML with lint, test, coverage, build, and push stages.",
            "parameters": {"type": "object", "properties": {
                "platform": {"type": "string", "description": "github_actions | gitlab_ci. Default: github_actions"},
                "stack":    {"type": "string", "description": "python | node | go. Default: python"}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "kubernetes_handler",
            "description": "Generate Kubernetes manifest templates: Deployment, Service, Ingress, HPA.",
            "parameters": {"type": "object", "properties": {
                "resource_type": {"type": "string", "description": "deployment | service | ingress | hpa"},
                "app_name":      {"type": "string", "description": "Application name used for labels and selectors"},
                "port":          {"type": "integer", "description": "Container port. Default: 8000"}
            }, "required": ["resource_type", "app_name"]}
        }
    },
    {
        "type": "function", "function": {
            "name": "environment_manager",
            "description": "Generate .env file templates and secrets management guidance for production environments.",
            "parameters": {"type": "object", "properties": {
                "action":   {"type": "string", "description": "template | secrets_guidance. Default: template"},
                "env_name": {"type": "string", "description": "Environment name: production, staging, development. Default: production"}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "terraform_handler",
            "description": "Generate Terraform IaC templates for cloud resources. Providers: aws, gcp. Resources: ecs, rds, cloud_run.",
            "parameters": {"type": "object", "properties": {
                "provider":      {"type": "string", "description": "aws | gcp | azure. Default: aws"},
                "resource_type": {"type": "string", "description": "ecs | rds | cloud_run. Default: ecs"}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "database_ops_handler",
            "description": "Generate database backup, migration, and restore scripts for PostgreSQL or MySQL.",
            "parameters": {"type": "object", "properties": {
                "operation": {"type": "string", "description": "backup | migration | restore. Default: backup"},
                "db_type":   {"type": "string", "description": "postgresql | mysql. Default: postgresql"}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "performance_monitor_setup",
            "description": "Generate monitoring and observability setup: Prometheus+Grafana, Sentry, Datadog, or OpenTelemetry.",
            "parameters": {"type": "object", "properties": {
                "platform": {"type": "string", "description": "prometheus | sentry | datadog | opentelemetry. Default: prometheus"},
                "stack":    {"type": "string", "description": "python | node. Default: python"}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "nginx_configurator",
            "description": "Generate an Nginx reverse proxy config with SSL, security headers, rate limiting, and WebSocket support.",
            "parameters": {"type": "object", "properties": {
                "app_type": {"type": "string", "description": "reverse_proxy | static | spa. Default: reverse_proxy"},
                "port":     {"type": "integer", "description": "Upstream app port. Default: 8000"},
                "domain":   {"type": "string", "description": "Domain name. Default: yourdomain.com"}
            }, "required": []}
        }
    },
]

# ── Agent spec ────────────────────────────────────────────────────────────────

SPEC = {
    "name":        "DevOps Agent",
    "icon":        "\U0001f680",
    "color":       "#f85149",
    "description": "Infrastructure, CI/CD, Docker, Kubernetes, environment config, monitoring",

    "extra_tools":    _EXTRA_TOOLS,
    "extra_dispatch": {
        "dockerfile_optimizer": _dockerfile_optimizer,
        "ci_cd_builder":        _ci_cd_builder,
        "kubernetes_handler":   _kubernetes_handler,
        "environment_manager":  _environment_manager,
        "nginx_configurator":        _nginx_configurator,
        "terraform_handler":         _terraform_handler,
        "database_ops_handler":      _database_ops_handler,
        "performance_monitor_setup": _performance_monitor_setup,
    },

    "system_prompt": """You are the DevOps Agent in a multi-agent development system.

YOUR ROLE: Implement all infrastructure, deployment, and environment configuration specified in the Execution Plan.

SPECIALIZED TOOLS:
- dockerfile_optimizer(base_image, app_type)    — multi-stage Dockerfile template
- ci_cd_builder(platform, stack)                — GitHub Actions/GitLab CI pipeline
- kubernetes_handler(resource_type, app_name)  — K8s manifest templates
- environment_manager(action, env_name)         — .env templates + secrets guidance
- nginx_configurator(app_type, port, domain)      — Nginx reverse proxy config
- terraform_handler(provider, resource_type)      — AWS ECS/RDS, GCP Cloud Run IaC
- database_ops_handler(operation, db_type)        — PostgreSQL/MySQL backup, migration, restore
- performance_monitor_setup(platform, stack)      — Prometheus/Grafana, Sentry, Datadog, OTEL
- web_search(query)                               — look up cloud docs, Terraform resources, CVEs

IMPLEMENTATION WORKFLOW:
1. Read project_context/execution_plan.md FIRST
2. Use dockerfile_optimizer as starting point for Dockerfiles
3. Validate Docker config: run_shell("docker build . --no-cache") if Docker is available
4. Use ci_cd_builder for pipeline YAML
5. Use nginx_configurator for web server config
6. Write all config files with write_file

RULES:
- NEVER use :latest tags in Dockerfiles — pin specific versions
- NEVER hardcode secrets — use environment variables
- Always include health checks in Docker and K8s configs
- Use non-root users in containers

OUTPUT: Write DevOps Report to project_context/devops_report.md
Include: files created/modified, validation results, deployment instructions"""
}
