import os
import re

# ── Tool implementations ──────────────────────────────────────────────────────

def _auth_pattern_implementer(pattern: str, language: str = "python") -> str:
    """Return implementation template for a specified authentication pattern."""
    patterns = {
        ("jwt", "python"): """=== JWT Authentication — Python/FastAPI ===

# Install: pip install python-jose[cryptography] passlib[bcrypt]

from jose import JWTError, jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta

SECRET_KEY = os.getenv("SECRET_KEY")  # never hardcode!
ALGORITHM  = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

# FastAPI dependency:
from fastapi import Depends, HTTPException, Security
from fastapi.security import OAuth2PasswordBearer

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

async def get_current_user(token: str = Depends(oauth2_scheme)):
    return verify_token(token)
""",
        ("jwt", "javascript"): """=== JWT Authentication — Node.js/Express ===

// Install: npm install jsonwebtoken bcryptjs
const jwt    = require('jsonwebtoken')
const bcrypt = require('bcryptjs')

const SECRET = process.env.JWT_SECRET  // never hardcode!

const generateToken = (payload) =>
    jwt.sign(payload, SECRET, { expiresIn: '30m' })

const verifyToken = (token) => {
    try { return jwt.verify(token, SECRET) }
    catch { throw new Error('Invalid token') }
}

// Middleware:
const authenticate = (req, res, next) => {
    const auth = req.headers.authorization
    if (!auth?.startsWith('Bearer '))
        return res.status(401).json({ error: 'Missing token' })
    try {
        req.user = verifyToken(auth.slice(7))
        next()
    } catch {
        res.status(401).json({ error: 'Invalid token' })
    }
}
""",
        ("oauth2", "python"): """=== OAuth2 with external provider — Python ===

# Install: pip install authlib httpx

from authlib.integrations.starlette_client import OAuth

oauth = OAuth()
oauth.register(
    name='google',
    client_id=os.getenv('GOOGLE_CLIENT_ID'),
    client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

@app.get('/auth/google')
async def google_login(request: Request):
    redirect_uri = request.url_for('google_callback')
    return await oauth.google.authorize_redirect(request, redirect_uri)

@app.get('/auth/google/callback')
async def google_callback(request: Request):
    token = await oauth.google.authorize_access_token(request)
    user_info = token.get('userinfo')
    # Create or find user, generate your own JWT
""",
        ("rbac", "python"): """=== Role-Based Access Control — Python/FastAPI ===

from enum import Enum
from functools import wraps

class Role(str, Enum):
    ADMIN = "admin"
    USER  = "user"
    GUEST = "guest"

ROLE_PERMISSIONS = {
    Role.ADMIN: {"read", "write", "delete", "admin"},
    Role.USER:  {"read", "write"},
    Role.GUEST: {"read"},
}

def require_permission(permission: str):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, current_user=Depends(get_current_user), **kwargs):
            user_role = Role(current_user.get("role", "guest"))
            if permission not in ROLE_PERMISSIONS.get(user_role, set()):
                raise HTTPException(status_code=403, detail="Insufficient permissions")
            return await func(*args, current_user=current_user, **kwargs)
        return wrapper
    return decorator

# Usage:
@app.delete("/users/{id}")
@require_permission("delete")
async def delete_user(id: int, current_user=Depends(get_current_user)):
    ...
""",
    }

    key = (pattern.lower(), language.lower())
    if key in patterns:
        return patterns[key]

    # Fallback: return closest match
    available = [f"{p}/{l}" for p, l in patterns.keys()]
    return f"[No template for '{pattern}/{language}'. Available: {', '.join(available)}]"


def _caching_advisor(strategy: str = "general") -> str:
    """Return caching strategy implementation guidance."""
    strategies = {
        "redis": """=== Redis Caching — Python ===

# Install: pip install redis

import redis
import json

r = redis.Redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379'))

def cache_get(key: str):
    val = r.get(key)
    return json.loads(val) if val else None

def cache_set(key: str, value, ttl_seconds: int = 300):
    r.setex(key, ttl_seconds, json.dumps(value, default=str))

def cache_delete(key: str):
    r.delete(key)

# Decorator:
def cached(ttl=300, key_fn=None):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            cache_key = key_fn(*args, **kwargs) if key_fn else f"{func.__name__}:{args}:{kwargs}"
            cached_val = cache_get(cache_key)
            if cached_val is not None:
                return cached_val
            result = await func(*args, **kwargs)
            cache_set(cache_key, result, ttl)
            return result
        return wrapper
    return decorator
""",
        "in_memory": """=== In-Memory Caching — Python (functools.lru_cache) ===

from functools import lru_cache, wraps
import time

# Simple LRU cache (process-local, lost on restart)
@lru_cache(maxsize=256)
def get_expensive_data(key: str):
    return fetch_from_db(key)

# TTL-aware cache (basic pattern)
_cache = {}

def ttl_cache(ttl: int = 60):
    def decorator(func):
        @wraps(func)
        def wrapper(*args):
            key = (func.__name__, args)
            if key in _cache:
                val, exp = _cache[key]
                if time.time() < exp:
                    return val
            result = func(*args)
            _cache[key] = (result, time.time() + ttl)
            return result
        return wrapper
    return decorator
""",
        "general": """=== Caching Strategy Guide ===

Choose based on use case:

1. In-process memory (functools.lru_cache)
   Best for: repeated pure function calls, computed values
   TTL: process lifetime
   Scope: single server instance

2. Redis / Memcached
   Best for: session data, shared across instances, user-specific caches
   TTL: configurable (seconds to hours)
   Scope: multi-server / distributed

3. CDN (CloudFront, Cloudflare)
   Best for: static assets, public API responses
   TTL: hours to days
   Scope: global edge

4. HTTP caching (Cache-Control, ETag)
   Best for: API responses consumed by browsers
   Headers: Cache-Control: max-age=300, public
   Scope: client-side / CDN

Cache invalidation strategy:
  - Time-based (TTL): simplest, acceptable staleness
  - Event-based: invalidate on write (delete key after mutation)
  - Versioned keys: never invalidate, use new key per version
""",
    }
    return strategies.get(strategy.lower(),
                          strategies["general"] + f"\n\n[No specific template for '{strategy}']")


def _rate_limiter_builder(framework: str = "fastapi", per: str = "minute", limit: int = 60) -> str:
    """Return rate limiting implementation for the given framework."""
    if "fastapi" in framework.lower() or "python" in framework.lower():
        return f"""=== Rate Limiting — FastAPI ({limit} req/{per}) ===

# Install: pip install slowapi

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import Request

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.get("/api/endpoint")
@limiter.limit("{limit}/{per}")
async def endpoint(request: Request):
    return {{"data": "..."}}

# Per-user rate limit:
def get_user_id(request: Request):
    # extract user ID from JWT token
    return request.headers.get("X-User-ID", get_remote_address(request))

user_limiter = Limiter(key_func=get_user_id)

@app.post("/api/sensitive")
@user_limiter.limit("10/minute")
async def sensitive_endpoint(request: Request):
    ...
"""
    elif "express" in framework.lower() or "node" in framework.lower():
        return f"""=== Rate Limiting — Express ({limit} req/{per}) ===

// Install: npm install express-rate-limit

const rateLimit = require('express-rate-limit')

const limiter = rateLimit({{
  windowMs: {'60 * 1000' if per == 'minute' else '60 * 60 * 1000'},
  max: {limit},
  message: {{ error: 'Too many requests, please try again later.' }},
  standardHeaders: true,   // Return rate limit info in headers
  legacyHeaders: false,
}})

app.use('/api/', limiter)

// Stricter limit for auth endpoints:
const authLimiter = rateLimit({{ windowMs: 15 * 60 * 1000, max: 10 }})
app.use('/auth/', authLimiter)
"""
    return f"[No rate limit template for '{framework}'. Options: fastapi, express]"


def _error_handler_builder(framework: str = "fastapi") -> str:
    """Return structured error handling implementation."""
    if "fastapi" in framework.lower():
        return """=== Structured Error Handling — FastAPI ===

from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
import logging
import traceback

logger = logging.getLogger(__name__)

class AppError(Exception):
    def __init__(self, message: str, status_code: int = 400, details: dict = None):
        self.message = message
        self.status_code = status_code
        self.details = details or {}

@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    logger.warning(f"AppError: {exc.message} | Path: {request.url}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.message, "details": exc.details}
    )

@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail}
    )

@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error: {exc}\\n{traceback.format_exc()}")
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error"}  # never expose details
    )
"""
    return f"[No error handler template for '{framework}'. Options: fastapi, express]"


def _database_query_builder(orm: str, operation: str = "crud") -> str:
    """Return ORM query patterns for common operations."""
    templates = {
        ("sqlalchemy", "crud"): """=== SQLAlchemy 2.x CRUD Patterns ===

from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

# Create
async def create_user(db: AsyncSession, email: str, name: str):
    user = User(email=email, name=name)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user

# Read (single)
async def get_user(db: AsyncSession, user_id: int):
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()

# Read (list with pagination)
async def list_users(db: AsyncSession, skip: int = 0, limit: int = 20):
    result = await db.execute(select(User).offset(skip).limit(limit))
    return result.scalars().all()

# Update
async def update_user(db: AsyncSession, user_id: int, data: dict):
    await db.execute(update(User).where(User.id == user_id).values(**data))
    await db.commit()

# Delete
async def delete_user(db: AsyncSession, user_id: int):
    await db.execute(delete(User).where(User.id == user_id))
    await db.commit()
""",
        ("prisma", "crud"): """=== Prisma CRUD Patterns (TypeScript) ===

import { PrismaClient } from '@prisma/client'
const prisma = new PrismaClient()

// Create
const user = await prisma.user.create({
    data: { email, name }
})

// Read
const user = await prisma.user.findUnique({ where: { id } })
const users = await prisma.user.findMany({
    skip: page * pageSize, take: pageSize,
    orderBy: { createdAt: 'desc' }
})

// Update
const updated = await prisma.user.update({
    where: { id },
    data: { name: 'New Name' }
})

// Delete (soft delete pattern):
const deleted = await prisma.user.update({
    where: { id },
    data: { deletedAt: new Date() }
})

// Transactions:
const result = await prisma.$transaction([
    prisma.order.create({ data: orderData }),
    prisma.inventory.update({ where: { id: itemId }, data: { stock: { decrement: 1 } } })
])
""",
    }
    key = (orm.lower(), operation.lower())
    if key in templates:
        return templates[key]
    available = [f"{o}/{op}" for o, op in templates.keys()]
    return f"[No template for '{orm}/{operation}'. Available: {', '.join(available)}]"


def _api_framework_lookup(framework: str, topic: str = "") -> str:
    """Return code snippets and patterns for common API framework operations."""
    docs = {
        "fastapi": {
            "": "FastAPI docs: https://fastapi.tiangolo.com | Key features: async, auto OpenAPI, Pydantic validation",
            "routing": """# FastAPI routing patterns
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

router = APIRouter(prefix="/users", tags=["users"])

class UserCreate(BaseModel):
    email: str
    name:  str

class UserResponse(BaseModel):
    id:    int
    email: str
    name:  str

    class Config:
        from_attributes = True  # Pydantic v2: model_config = ConfigDict(from_attributes=True)

@router.get("/",          response_model=list[UserResponse])
@router.get("/{user_id}", response_model=UserResponse)
@router.post("/",         response_model=UserResponse, status_code=status.HTTP_201_CREATED)
@router.put("/{user_id}", response_model=UserResponse)
@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)""",
            "middleware": """# FastAPI middleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

app.add_middleware(CORSMiddleware,
    allow_origins=["https://yourdomain.com"],
    allow_methods=["*"], allow_headers=["*"], allow_credentials=True)
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Custom middleware:
from starlette.middleware.base import BaseHTTPMiddleware
class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request.state.request_id = str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response""",
            "background_tasks": """# FastAPI background tasks
from fastapi import BackgroundTasks

def send_email(email: str, message: str):
    # runs after response is sent
    pass

@app.post("/send")
async def send(background_tasks: BackgroundTasks, email: str):
    background_tasks.add_task(send_email, email, "Welcome!")
    return {"status": "queued"}""",
        },
        "express": {
            "": "Express docs: https://expressjs.com | Key features: minimal, middleware-based, flexible",
            "routing": """// Express routing patterns
const router = require('express').Router()
const { body, param, validationResult } = require('express-validator')

// Middleware: check validation results
const validate = (req, res, next) => {
  const errors = validationResult(req)
  if (!errors.isEmpty()) return res.status(422).json({ errors: errors.array() })
  next()
}

router.get('/',        asyncHandler(listUsers))
router.get('/:id',    [param('id').isInt()], validate, asyncHandler(getUser))
router.post('/',      [body('email').isEmail()], validate, asyncHandler(createUser))
router.put('/:id',    asyncHandler(updateUser))
router.delete('/:id', asyncHandler(deleteUser))

// asyncHandler wrapper to avoid try/catch boilerplate:
const asyncHandler = fn => (req, res, next) => Promise.resolve(fn(req, res, next)).catch(next)""",
            "middleware": """// Express middleware
const express    = require('express')
const helmet     = require('helmet')
const morgan     = require('morgan')
const cors       = require('cors')
const compression = require('compression')

app.use(helmet())               // security headers
app.use(cors({ origin: process.env.ALLOWED_ORIGIN }))
app.use(morgan('combined'))     // request logging
app.use(compression())          // gzip
app.use(express.json({ limit: '1mb' }))

// Global error handler (must be last):
app.use((err, req, res, next) => {
  console.error(err.stack)
  res.status(err.status || 500).json({ error: err.message || 'Internal server error' })
})""",
        },
        "django": {
            "": "Django REST Framework docs: https://www.django-rest-framework.org",
            "viewset": """# Django REST Framework ViewSet
from rest_framework import viewsets, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response

class UserViewSet(viewsets.ModelViewSet):
    queryset           = User.objects.all().order_by('-created_at')
    serializer_class   = UserSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends    = [filters.SearchFilter, filters.OrderingFilter]
    search_fields      = ['email', 'name']
    ordering_fields    = ['created_at', 'name']

    @action(detail=True, methods=['post'], url_path='activate')
    def activate(self, request, pk=None):
        user = self.get_object()
        user.is_active = True
        user.save()
        return Response({'status': 'activated'})

# urls.py:
from rest_framework.routers import DefaultRouter
router = DefaultRouter()
router.register(r'users', UserViewSet)
urlpatterns = router.urls""",
        },
        "rails": {
            "": "Ruby on Rails API docs: https://api.rubyonrails.org",
            "controller": """# Rails API Controller
class Api::V1::UsersController < ApplicationController
  before_action :authenticate_user!
  before_action :set_user, only: [:show, :update, :destroy]

  def index
    @users = User.all.page(params[:page]).per(20)
    render json: @users, status: :ok
  end

  def show
    render json: @user
  end

  def create
    @user = User.new(user_params)
    if @user.save
      render json: @user, status: :created
    else
      render json: { errors: @user.errors }, status: :unprocessable_entity
    end
  end

  private

  def set_user
    @user = User.find(params[:id])
  rescue ActiveRecord::RecordNotFound
    render json: { error: 'Not found' }, status: :not_found
  end

  def user_params
    params.require(:user).permit(:email, :name)
  end
end""",
        },
    }

    fw = framework.lower()
    fw_docs = docs.get(fw, {})
    if not fw_docs:
        available = ", ".join(docs.keys())
        return f"[No docs for '{framework}'. Available: {available}]"

    topic_lower = topic.lower()
    if topic_lower and topic_lower in fw_docs:
        return f"=== {framework} — {topic} ===\n{fw_docs[topic_lower]}"
    elif "" in fw_docs:
        result = f"=== {framework} Overview ===\n{fw_docs['']}"
        if topic_lower:
            result += f"\n\n[No snippet for '{topic}' — available topics: {', '.join(k for k in fw_docs if k)}]"
        else:
            result += f"\n\nAvailable topics: {', '.join(k for k in fw_docs if k)}"
        return result
    return f"[No entry for '{framework}/{topic}']"


def _queue_handler(broker: str = "celery", operation: str = "task",
                    language: str = "python") -> str:
    """Return background job / message queue implementation templates."""
    if "celery" in broker.lower():
        if operation.lower() in ("task", "basic"):
            return """=== Celery Task Queue — Python ===
# Install: pip install celery redis
# Start worker: celery -A myapp.celery worker --loglevel=info
# Start beat:   celery -A myapp.celery beat --loglevel=info

# celery_app.py
from celery import Celery
import os

celery_app = Celery(
    "myapp",
    broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    backend=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_expires=3600,
    task_acks_late=True,          # re-queue on worker crash
    worker_prefetch_multiplier=1, # fair distribution
)

# tasks.py
from celery_app import celery_app

@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def send_email(self, recipient: str, subject: str, body: str):
    try:
        # email sending logic
        pass
    except Exception as exc:
        raise self.retry(exc=exc)  # auto-exponential backoff

@celery_app.task
def generate_report(report_id: int):
    # long-running background task
    pass

# Dispatch tasks:
send_email.delay("user@example.com", "Subject", "Body")
send_email.apply_async(args=["user@example.com", "Subject", "Body"],
                        countdown=60,      # delay 60 seconds
                        expires=3600)      # discard if not run in 1h

# Scheduled task (celery beat):
celery_app.conf.beat_schedule = {
    "daily-report": {
        "task": "tasks.generate_report",
        "schedule": crontab(hour=0, minute=0),  # midnight
        "args": (1,),
    },
}"""

        elif operation.lower() == "chain":
            return """=== Celery Workflow Patterns ===
from celery import chain, group, chord

# Chain: A → B → C (sequential)
result = chain(
    fetch_data.s(user_id),
    process_data.s(),
    save_result.s(),
)()

# Group: run tasks in parallel, collect results
result = group(
    process_chunk.s(chunk) for chunk in chunks
)()

# Chord: parallel + callback when all done
result = chord(
    group(process_chunk.s(chunk) for chunk in chunks),
    aggregate_results.s()  # runs after all chunks finish
)()"""

    elif "bull" in broker.lower() or "bullmq" in broker.lower():
        return """=== BullMQ — Node.js Job Queue ===
// Install: npm install bullmq ioredis

import { Queue, Worker, QueueEvents } from 'bullmq'
import IORedis from 'ioredis'

const connection = new IORedis(process.env.REDIS_URL || 'redis://localhost:6379')

// Define queue
const emailQueue = new Queue('email', { connection })

// Add jobs
await emailQueue.add('send-welcome', {
  recipient: 'user@example.com',
  subject:   'Welcome!',
}, {
  attempts:  3,
  backoff:   { type: 'exponential', delay: 1000 },
  delay:     5000,   // delay 5 seconds
  removeOnComplete: 100,  // keep last 100 completed
  removeOnFail:     50,
})

// Process jobs
const worker = new Worker('email', async (job) => {
  const { recipient, subject } = job.data
  await sendEmail(recipient, subject)
  return { sent: true }
}, { connection, concurrency: 5 })

worker.on('completed', (job, result) => console.log(`Job ${job.id} done`, result))
worker.on('failed',    (job, err)    => console.error(`Job ${job.id} failed`, err))

// Scheduled (repeatable) jobs:
await emailQueue.add('daily-digest', {}, {
  repeat: { cron: '0 9 * * *' }  // 9am daily
})"""

    elif "sqs" in broker.lower() or "aws" in broker.lower():
        return """=== AWS SQS Task Queue — Python ===
# Install: pip install boto3

import boto3
import json
import os

sqs = boto3.client('sqs', region_name=os.getenv('AWS_REGION', 'us-east-1'))
QUEUE_URL = os.getenv('SQS_QUEUE_URL')

def enqueue(message: dict, delay_seconds: int = 0) -> str:
    resp = sqs.send_message(
        QueueUrl=QUEUE_URL,
        MessageBody=json.dumps(message),
        DelaySeconds=delay_seconds,
    )
    return resp['MessageId']

def process_messages(handler, max_messages: int = 10):
    while True:
        resp = sqs.receive_message(
            QueueUrl=QUEUE_URL,
            MaxNumberOfMessages=max_messages,
            WaitTimeSeconds=20,    # long polling — reduces empty responses
            VisibilityTimeout=300, # 5 min to process before re-queuing
        )
        for msg in resp.get('Messages', []):
            body = json.loads(msg['Body'])
            try:
                handler(body)
                sqs.delete_message(QueueUrl=QUEUE_URL,
                                   ReceiptHandle=msg['ReceiptHandle'])
            except Exception as e:
                print(f"Error processing {msg['MessageId']}: {e}")
                # Message becomes visible again after VisibilityTimeout

# Usage:
enqueue({"type": "send_email", "to": "user@example.com"})
process_messages(lambda msg: handle(msg))"""

    return f"[No template for broker '{broker}'. Options: celery, bullmq, sqs]"


def _api_versioning_handler(strategy: str = "url_prefix") -> str:
    """Return API versioning strategy implementation."""
    strategies = {
        "url_prefix": """=== URL Prefix Versioning — /api/v1/... ===
# Most common, most explicit, easiest to reason about

# FastAPI:
from fastapi import FastAPI, APIRouter

v1_router = APIRouter(prefix="/api/v1")
v2_router = APIRouter(prefix="/api/v2")

@v1_router.get("/users")
async def list_users_v1(): ...

@v2_router.get("/users")
async def list_users_v2(): ...  # can add new fields, change response shape

app = FastAPI()
app.include_router(v1_router)
app.include_router(v2_router)

# Express:
const v1 = require('./routes/v1')
const v2 = require('./routes/v2')
app.use('/api/v1', v1)
app.use('/api/v2', v2)

# RULES for breaking vs non-breaking changes:
# ✓ Non-breaking (no new version needed): add optional fields, add new endpoints
# ✗ Breaking (new version required): remove fields, rename fields, change field types""",

        "header": """=== Header Versioning — Accept: application/vnd.api+json;version=2 ===
# Cleaner URLs, but harder to test and cache

# FastAPI:
from fastapi import Header, HTTPException

@app.get("/api/users")
async def list_users(accept_version: str = Header(default="1")):
    if accept_version == "2":
        return v2_response()
    return v1_response()

# Express:
app.get('/api/users', (req, res) => {
  const version = req.headers['api-version'] || '1'
  if (version === '2') return res.json(v2Response())
  return res.json(v1Response())
})""",

        "sunset": """=== API Deprecation & Sunset Strategy ===

1. Announce deprecation in docs and via Sunset header:
   Sunset: Sat, 01 Jan 2026 00:00:00 GMT
   Deprecation: true
   Link: <https://docs.example.com/migration>; rel="deprecation"

2. FastAPI deprecation marker:
   @app.get("/api/v1/users", deprecated=True,
            description="Deprecated — migrate to /api/v2/users by 2026-01-01")

3. Log usage of deprecated endpoints to track remaining consumers:
   @app.middleware("http")
   async def log_deprecated(request, call_next):
       if "/api/v1/" in str(request.url):
           logger.warning(f"Deprecated v1 call: {request.url} from {request.client.host}")
       return await call_next(request)

4. Migration timeline:
   Month 1: Release v2 alongside v1 (parallel)
   Month 2: Add Deprecation headers to v1
   Month 3: Email all API key holders with migration guide
   Month 6: Sunset v1 (return 410 Gone)""",
    }

    key = strategy.lower().replace("-", "_").replace(" ", "_")
    if key in strategies:
        return strategies[key]
    all_keys = ", ".join(strategies.keys())
    return (
        f"=== API Versioning Strategies ===\n\n"
        f"Available: {all_keys}\n\n"
        + "\n\n".join(f"--- {k} ---\n{v[:200]}..." for k, v in strategies.items())
    )


# ── Tool schemas ──────────────────────────────────────────────────────────────

_EXTRA_TOOLS = [
    {
        "type": "function", "function": {
            "name": "auth_pattern_implementer",
            "description": "Get a ready-to-use authentication implementation template. Patterns: jwt, oauth2, rbac. Languages: python, javascript.",
            "parameters": {"type": "object", "properties": {
                "pattern":  {"type": "string", "description": "jwt | oauth2 | rbac"},
                "language": {"type": "string", "description": "python | javascript. Default: python"}
            }, "required": ["pattern"]}
        }
    },
    {
        "type": "function", "function": {
            "name": "caching_advisor",
            "description": "Get caching strategy guidance and code template. Strategies: redis, in_memory, general.",
            "parameters": {"type": "object", "properties": {
                "strategy": {"type": "string", "description": "redis | in_memory | general. Default: general"}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "rate_limiter_builder",
            "description": "Get a rate limiting implementation template for FastAPI or Express.",
            "parameters": {"type": "object", "properties": {
                "framework": {"type": "string", "description": "fastapi | express. Default: fastapi"},
                "per":       {"type": "string", "description": "minute | hour | day. Default: minute"},
                "limit":     {"type": "integer", "description": "Max requests per window. Default: 60"}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "error_handler_builder",
            "description": "Get a structured error handling setup for FastAPI or Express with proper logging.",
            "parameters": {"type": "object", "properties": {
                "framework": {"type": "string", "description": "fastapi | express. Default: fastapi"}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "api_framework_lookup",
            "description": "Get code snippets and patterns for a specific API framework. Frameworks: fastapi, express, django, rails. Topics vary by framework (routing, middleware, viewset, etc.).",
            "parameters": {"type": "object", "properties": {
                "framework": {"type": "string", "description": "fastapi | express | django | rails"},
                "topic":     {"type": "string", "description": "Specific topic (routing, middleware, background_tasks, viewset, controller). Omit for overview."}
            }, "required": ["framework"]}
        }
    },
    {
        "type": "function", "function": {
            "name": "queue_handler",
            "description": "Get background job / message queue implementation templates. Brokers: celery (Python), bullmq (Node.js), sqs (AWS).",
            "parameters": {"type": "object", "properties": {
                "broker":    {"type": "string", "description": "celery | bullmq | sqs. Default: celery"},
                "operation": {"type": "string", "description": "task | chain | schedule. Default: task"},
                "language":  {"type": "string", "description": "python | javascript. Default: python"}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "api_versioning_handler",
            "description": "Get API versioning strategy implementation: URL prefix (/api/v1/), header versioning, or sunset/deprecation strategy.",
            "parameters": {"type": "object", "properties": {
                "strategy": {"type": "string", "description": "url_prefix | header | sunset. Default: url_prefix"}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "database_query_builder",
            "description": "Get ORM query patterns for common CRUD operations. ORMs: sqlalchemy, prisma.",
            "parameters": {"type": "object", "properties": {
                "orm":       {"type": "string", "description": "sqlalchemy | prisma"},
                "operation": {"type": "string", "description": "crud | migrations | transactions. Default: crud"}
            }, "required": ["orm"]}
        }
    },
]

# ── Agent spec ────────────────────────────────────────────────────────────────

SPEC = {
    "name":        "Backend Agent",
    "icon":        "\u2699\ufe0f",
    "color":       "#3fb950",
    "description": "Server logic, APIs, databases, auth, and business logic",

    "extra_tools":    _EXTRA_TOOLS,
    "extra_dispatch": {
        "auth_pattern_implementer": _auth_pattern_implementer,
        "caching_advisor":          _caching_advisor,
        "rate_limiter_builder":     _rate_limiter_builder,
        "error_handler_builder":    _error_handler_builder,
        "database_query_builder":   _database_query_builder,
        "api_framework_lookup":     _api_framework_lookup,
        "queue_handler":            _queue_handler,
        "api_versioning_handler":   _api_versioning_handler,
    },

    "system_prompt": """You are the Backend Agent in a multi-agent development system.

YOUR ROLE: Implement all server-side code changes specified in the Execution Plan.

SPECIALIZED TOOLS:
- auth_pattern_implementer(pattern, language) — JWT/OAuth2/RBAC templates
- caching_advisor(strategy)                   — Redis/in-memory caching templates
- rate_limiter_builder(framework, per, limit) — rate limiting setup
- error_handler_builder(framework)            — structured error handling
- database_query_builder(orm, operation)      — SQLAlchemy/Prisma query patterns
- api_framework_lookup(framework, topic)      — FastAPI/Express/Django/Rails code snippets
- queue_handler(broker, operation)            — Celery/BullMQ/SQS background job templates
- api_versioning_handler(strategy)            — URL prefix / header / sunset strategies
- web_search(query)                           — look up framework docs, error solutions, packages

IMPLEMENTATION WORKFLOW:
1. Read project_context/execution_plan.md FIRST
2. Read existing source files before editing them
3. Use tool templates as starting points — adapt to match existing code style
4. Implement changes with edit_file (surgical) or write_file (new files)
5. Run tests: run_shell("pytest" or "npm test") and fix failures

RULES:
- ALWAYS read a file before editing it
- ALWAYS add error handling to new endpoints — never leave bare code
- ALWAYS validate user input — never trust request data
- Follow the existing code style and framework conventions exactly

OUTPUT: Write Backend Report to project_context/backend_report.md
Include: endpoints added/modified, migrations run, test results, any deviations from plan"""
}
