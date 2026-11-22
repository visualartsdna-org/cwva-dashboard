"""Tool registry + dispatcher.

The dispatcher is the single point where a named tool call becomes an executed
operation. It validates arguments, runs the handler against a :class:`FileOps`,
maps sandbox exceptions to stable error codes, and emits exactly one audit
event per call. It never raises for an operational failure — the outcome is
always a :class:`DispatchResult` — so it is safe to drive from an untrusted
request loop.
"""

from __future__ import annotations

from typing import Any, Callable

from ..sandbox.paths import PathRejected
from ..sandbox.quotas import QuotaExceeded
from .base import DispatchResult, Tool, ToolError, validate_args

__all__ = ["ToolRegistry"]

# audit callback: (tool_name, audited_args, outcome)
AuditFn = Callable[[str, dict, str], None]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name!r}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def schemas(self) -> list[dict]:
        """MCP-style tool descriptors: name, description, inputSchema."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": t.input_schema,
            }
            for t in (self._tools[n] for n in self.names())
        ]

    def dispatch(
        self, name: str, args: dict, fileops: Any, *, audit: AuditFn | None = None
    ) -> DispatchResult:
        tool = self._tools.get(name)
        if tool is None:
            if audit:
                audit(name or "?", {}, "error:unknown_tool")
            return DispatchResult(
                False, None, {"code": "unknown_tool", "message": f"no such tool: {name!r}"}
            )

        try:
            norm = validate_args(tool.input_schema, args)
        except ToolError as exc:
            if audit:
                audit(name, _redact(args, tool.redact), f"error:{exc.code}")
            return DispatchResult(False, None, {"code": exc.code, "message": str(exc)})

        audited = _redact(norm, tool.redact)
        try:
            result = tool.handler(fileops, **norm)
        except ToolError as exc:
            # A handler's ToolError carries a STABLE CODE, exactly like one from
            # validate_args, and callers key off it. Without this branch it fell
            # through to the generic mapping below and came back as the useless
            # code "ToolError" — so a rule a handler enforces (a cross-field
            # requirement, say, which JSON Schema cannot state) was
            # indistinguishable from a crash.
            outcome = f"error:{exc.code}"
            dr = DispatchResult(False, None, {"code": exc.code, "message": str(exc)})
        except PathRejected as exc:
            outcome = f"error:path_rejected:{exc.reason.value}"
            dr = DispatchResult(
                False,
                None,
                {"code": "path_rejected", "reason": exc.reason.value, "message": str(exc)},
            )
        except QuotaExceeded as exc:
            outcome = f"error:quota:{exc.limit}"
            dr = DispatchResult(
                False, None, {"code": "quota_exceeded", "limit": exc.limit, "message": str(exc)}
            )
        except (
            FileNotFoundError,
            FileExistsError,
            NotADirectoryError,
            IsADirectoryError,
            PermissionError,
            UnicodeDecodeError,
            OSError,
        ) as exc:
            outcome = f"error:{type(exc).__name__}"
            dr = DispatchResult(
                False, None, {"code": type(exc).__name__, "message": str(exc)}
            )
        except Exception as exc:
            # Tool-execution boundary: a handler must never crash the worker
            # loop. Anything unmapped (bad SPARQL, corrupt image, parse error)
            # becomes a structured error keyed by exception type.
            outcome = f"error:{type(exc).__name__}"
            dr = DispatchResult(
                False, None, {"code": type(exc).__name__, "message": str(exc)}
            )
        else:
            outcome = "ok"
            dr = DispatchResult(True, result, None)

        if audit:
            audit(name, audited, outcome)
        return dr


def _redact(args: dict, redact: frozenset[str]) -> dict:
    """Replace redacted string params with a length summary so the audit log
    records that a write happened and how big it was, not the payload."""
    if not redact:
        return dict(args)
    out: dict[str, Any] = {}
    for k, v in args.items():
        if k in redact and isinstance(v, str):
            out[k] = f"<{len(v)} chars>"
        else:
            out[k] = v
    return out
