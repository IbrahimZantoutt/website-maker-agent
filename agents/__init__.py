"""
Agent registry — 3 agent types: Code Analyst, Frontend, Backend.
"""
from .code_analyst import SPEC as _code_analyst_spec
from .frontend import SPEC as _frontend_spec
from .backend import SPEC as _backend_spec

AGENT_REGISTRY: dict = {
    "code_analyst": _code_analyst_spec,
    "frontend": _frontend_spec,
    "backend": _backend_spec,
}
