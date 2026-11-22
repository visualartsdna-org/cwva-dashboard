"""Agent tool layer — the fixed, deny-by-default vocabulary (CE_DESIGN §2.1, §7).

Every dashboard capability the agent can invoke is a :class:`Tool` with a
name, a JSON-Schema input, and a handler. The registry validates arguments
before dispatch and refuses anything unknown. There is no exec/shell/eval tool,
by law; the vocabulary here is the whole of what the model can do.

Schemas are JSON Schema so the same registry can later be exposed as an MCP
server (CE_DESIGN §7) without reshaping the tools.
"""

from .base import DispatchResult, Tool, ToolError, validate_args
from .fileops_tools import build_default_registry
from .registry import ToolRegistry

__all__ = [
    "Tool",
    "ToolError",
    "DispatchResult",
    "validate_args",
    "ToolRegistry",
    "build_default_registry",
]
