"""
Configuration — models, limits, path exclusions.
"""
import os

# ── LLM Configuration ────────────────────────────────────────────────────────

MODELS = [
    "minimax-m2.5:cloud",
    "qwen2.5-coder:7b",
]
MODEL = MODELS[0]
MAX_STEPS = 200

# ── Path Exclusions ──────────────────────────────────────────────────────────

# Directory of the agent system itself — excluded from agent file access
AGENT_DIR = os.path.dirname(os.path.abspath(__file__))

# Directories excluded from file tree, search, and analysis
TREE_SKIP = {
    ".git", "__pycache__", ".venv", "venv", ".env",
    "node_modules", ".pytest_cache", ".mypy_cache",
    "dist", "build", "project_context",
}
