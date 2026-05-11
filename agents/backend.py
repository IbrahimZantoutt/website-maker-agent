"""
Backend Agent — APIs, server logic, databases, auth, business logic.
"""
import os
import re


# ── Tool implementations ─────────────────────────────────────────────────────


def _auth_pattern_implementer(pattern: str, language: str = "python") -> str:
    patterns = {
        ("jwt", "python"): """=== JWT Auth — Python/FastAPI ===
from jose import JWTError, jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(token: str) -> dict:
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

# FastAPI dependency:
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")
async def get_current_user(token: str = Depends(oauth2_scheme)):
    return verify_token(token)""",

        ("jwt", "javascript"): """=== JWT Auth — Node.js/Express ===
const jwt = require('jsonwebtoken')
const bcrypt = require('bcryptjs')
const SECRET = process.env.JWT_SECRET

const generateToken = (payload) => jwt.sign(payload, SECRET, { expiresIn: '30m' })
const verifyToken = (token) => jwt.verify(token, SECRET)

// Middleware:
const authenticate = (req, res, next) => {
    const auth = req.headers.authorization
    if (!auth?.startsWith('Bearer ')) return res.status(401).json({ error: 'Missing token' })
    try { req.user = verifyToken(auth.slice(7)); next() }
    catch { res.status(401).json({ error: 'Invalid token' }) }
}""",
    }

    key = (pattern.lower(), language.lower())
    if key in patterns:
        return patterns[key]
    return f"[No template for ({pattern}, {language}). Available: (jwt, python), (jwt, javascript)]"


def _database_query_builder(orm: str, operation: str = "crud") -> str:
    templates = {
        ("sqlalchemy", "crud"): """=== SQLAlchemy 2.x CRUD ===
from sqlalchemy import select, insert, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

# Create
async def create_item(session: AsyncSession, data: dict):
    stmt = insert(Item).values(**data).returning(Item)
    result = await session.execute(stmt)
    await session.commit()
    return result.scalar_one()

# Read
async def get_item(session: AsyncSession, item_id: int):
    stmt = select(Item).where(Item.id == item_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()

# Update
async def update_item(session: AsyncSession, item_id: int, data: dict):
    stmt = update(Item).where(Item.id == item_id).values(**data).returning(Item)
    result = await session.execute(stmt)
    await session.commit()
    return result.scalar_one()

# Delete
async def delete_item(session: AsyncSession, item_id: int):
    stmt = delete(Item).where(Item.id == item_id)
    await session.execute(stmt)
    await session.commit()""",

        ("prisma", "crud"): """=== Prisma CRUD ===
// Create
const item = await prisma.item.create({ data: { name, description } })

// Read
const item = await prisma.item.findUnique({ where: { id } })
const items = await prisma.item.findMany({ where: { active: true }, orderBy: { createdAt: 'desc' } })

// Update
const updated = await prisma.item.update({ where: { id }, data: { name: newName } })

// Delete
await prisma.item.delete({ where: { id } })

// Relations
const userWithPosts = await prisma.user.findUnique({
    where: { id },
    include: { posts: true }
})""",
    }

    key = (orm.lower(), operation.lower())
    if key in templates:
        return templates[key]
    return f"[No template for ({orm}, {operation}). Available: (sqlalchemy, crud), (prisma, crud)]"


def _api_framework_lookup(framework: str, topic: str = "routing") -> str:
    docs = {
        ("fastapi", "routing"): """=== FastAPI Routing ===
from fastapi import FastAPI, APIRouter, Depends, HTTPException

router = APIRouter(prefix="/api/v1", tags=["items"])

@router.get("/items")
async def list_items(skip: int = 0, limit: int = 100):
    return await get_items(skip=skip, limit=limit)

@router.get("/items/{item_id}")
async def get_item(item_id: int):
    item = await find_item(item_id)
    if not item: raise HTTPException(status_code=404, detail="Not found")
    return item

@router.post("/items", status_code=201)
async def create_item(data: ItemCreate):
    return await insert_item(data)

# Register in main:
app.include_router(router)""",

        ("express", "routing"): """=== Express Routing ===
const express = require('express')
const router = express.Router()

router.get('/items', async (req, res) => {
    const items = await Item.find()
    res.json(items)
})

router.get('/items/:id', async (req, res) => {
    const item = await Item.findById(req.params.id)
    if (!item) return res.status(404).json({ error: 'Not found' })
    res.json(item)
})

router.post('/items', async (req, res) => {
    const item = await Item.create(req.body)
    res.status(201).json(item)
})

module.exports = router""",

        ("fastapi", "middleware"): """=== FastAPI Middleware ===
from fastapi import Request
from starlette.middleware.cors import CORSMiddleware
import time

# CORS
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Custom timing middleware
@app.middleware("http")
async def add_timing(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    response.headers["X-Process-Time"] = str(time.time() - start)
    return response""",
    }

    key = (framework.lower(), topic.lower())
    if key in docs:
        return docs[key]
    available = [f"({f}, {t})" for f, t in docs]
    return f"[No docs for ({framework}, {topic}). Available: {', '.join(available)}]"


def _error_handler_builder(framework: str = "fastapi") -> str:
    handlers = {
        "fastapi": """=== FastAPI Error Handling ===
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={
        "error": exc.detail,
        "status": exc.status_code
    })

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={
        "error": "Internal server error",
        "status": 500
    })""",

        "express": """=== Express Error Handling ===
// Error handler middleware (must be last)
app.use((err, req, res, next) => {
    console.error(err.stack)
    const status = err.status || 500
    res.status(status).json({
        error: err.message || 'Internal server error',
        status
    })
})""",
    }
    return handlers.get(framework.lower(), f"[No template for '{framework}'. Options: fastapi, express]")


# ── Tool schemas ─────────────────────────────────────────────────────────────

_EXTRA_TOOLS = [
    {"type": "function", "function": {
        "name": "auth_pattern_implementer",
        "description": "Get auth implementation templates (JWT, OAuth2) for Python or JavaScript.",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string", "description": "jwt | oauth2 | rbac"},
            "language": {"type": "string", "description": "python | javascript"}
        }, "required": ["pattern"]}
    }},
    {"type": "function", "function": {
        "name": "database_query_builder",
        "description": "Get CRUD templates for SQLAlchemy or Prisma.",
        "parameters": {"type": "object", "properties": {
            "orm": {"type": "string", "description": "sqlalchemy | prisma"},
            "operation": {"type": "string", "description": "crud (default)"}
        }, "required": ["orm"]}
    }},
    {"type": "function", "function": {
        "name": "api_framework_lookup",
        "description": "Get routing, middleware, and other patterns for FastAPI or Express.",
        "parameters": {"type": "object", "properties": {
            "framework": {"type": "string", "description": "fastapi | express | django"},
            "topic": {"type": "string", "description": "routing | middleware | background_tasks"}
        }, "required": ["framework"]}
    }},
    {"type": "function", "function": {
        "name": "error_handler_builder",
        "description": "Get structured error handling templates for FastAPI or Express.",
        "parameters": {"type": "object", "properties": {
            "framework": {"type": "string", "description": "fastapi | express"}
        }, "required": []}
    }},
]

# ── Agent spec ───────────────────────────────────────────────────────────────

SPEC = {
    "name": "Backend Agent",
    "icon": "gear",
    "color": "#3fb950",
    "description": "APIs, server logic, databases, auth, business logic",
    "agent_type": "backend",

    "extra_tools": _EXTRA_TOOLS,
    "extra_dispatch": {
        "auth_pattern_implementer": _auth_pattern_implementer,
        "database_query_builder": _database_query_builder,
        "api_framework_lookup": _api_framework_lookup,
        "error_handler_builder": _error_handler_builder,
    },

    "system_prompt": """You are the Backend Agent in a multi-agent development system.

YOUR ROLE: Implement server-side code — APIs, database models, auth, business logic, middleware.

SPECIALIZED TOOLS:
- auth_pattern_implementer(pattern, language) — JWT/OAuth2 templates
- database_query_builder(orm, operation)      — SQLAlchemy/Prisma CRUD
- api_framework_lookup(framework, topic)      — FastAPI/Express patterns
- error_handler_builder(framework)            — error handling templates
- message_agent(target_id, message)           — coordinate with peers or reply to user

WORKFLOW:
1. Read project context and analysis findings
2. Read existing files before editing
3. Implement with edit_file (surgical) or write_file (new files)
4. Use message_agent to share API contracts and schemas with frontend agents
5. Run tests/build if applicable

RULES:
- ALWAYS read a file before editing it
- Follow existing code style and framework conventions
- Share API contracts via message_agent so frontend agents can build against them
- When done, output a summary of endpoints created, migrations run, and files changed""",
}
