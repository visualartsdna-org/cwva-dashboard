"""Tool spec, argument validation, and dispatch result types.

A :class:`Tool` pairs a JSON-Schema input with a handler ``(fileops, **args)``.
Validation is deliberately small and **deny-by-default**: unknown keys are
refused (``additionalProperties: false``), required keys enforced, declared
types checked, and declared **closed sets (`enum`) and `format`s enforced**. A
full JSON-Schema engine is deferred — the security posture wants refusal of
anything unrecognized, which a minimal validator delivers without a new
dependency.

`enum`/`format` matter beyond shape: this is the single place a schema
constraint binds **both** drivers (the human via the rendered affordance and the
Phase-5 agent on the same tools). A closed set that lived only in a rendered
`<select>` would bind the human alone and let the agent send `units:"metre"`
straight through — the affordance-layer hole this enforcement closes
(the affordance design, Dispatch locus). Store-relative validity (dynamic
vocabulary, asset existence) is deliberately NOT here — that is a promotion-gate
concern, because the confined worker must not enumerate the store to validate an
argument. The `x-*` affordance annotations are ignored here by design.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Callable
from urllib.parse import urlsplit

from dataclasses import dataclass, field

__all__ = ["Tool", "ToolError", "DispatchResult", "validate_args"]


class ToolError(Exception):
    """Argument validation or dispatch precondition failure. ``code`` is a
    stable machine-readable tag for the audit log and API."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict  # JSON Schema (object) — MCP `inputSchema` shape
    handler: Callable[..., dict]
    # Param names whose values are summarized (not stored verbatim) in the
    # audit log — e.g. large text payloads.
    redact: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class DispatchResult:
    ok: bool
    result: dict | None = None
    error: dict | None = None


# JSON Schema type name -> Python predicate. bool is excluded from integer/
# number because ``isinstance(True, int)`` is True in Python.
def _is_integer(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


_TYPE_CHECKS: dict[str, Callable[[Any], bool]] = {
    "string": lambda v: isinstance(v, str),
    "integer": _is_integer,
    "number": _is_number,
    "boolean": lambda v: isinstance(v, bool),
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "null": lambda v: v is None,
}


# format name -> predicate on a string value. Enforced (deny-by-default), not
# advisory as `format` is in vanilla JSON Schema — a bad value here is a
# rejected tool call, not a warning. `date` is the canonical YYYY-MM-DD and a
# real calendar date; `uri` is a well-formed absolute http(s) URL (well-
# formedness only — reachability/existence is never a dispatch concern).
def _is_iso_date(v: str) -> bool:
    # date.fromisoformat also accepts the 3.11 basic form "20260729"; require the
    # canonical hyphenated form explicitly so the closed shape is exact.
    if len(v) != 10 or v[4] != "-" or v[7] != "-":
        return False
    try:
        date.fromisoformat(v)
    except ValueError:
        return False
    return True


def _is_http_uri(v: str) -> bool:
    try:
        parts = urlsplit(v)
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.netloc)


# ISO-8601 durations, the lexical space of xs:duration. Enforced here rather
# than left to the parse gate because rdflib will serialize an ill-formed
# xs:duration literal without complaint — the resulting file parses, so the gate
# passes, and the bad lexical form only surfaces in whatever consumes it later.
# Dispatch is the boundary that can still say no.
_DURATION_RE = re.compile(
    r"^-?P(?!$)(\d+Y)?(\d+M)?(\d+D)?"
    r"(T(?!$)(\d+H)?(\d+M)?(\d+(\.\d+)?S)?)?$"
)


def _is_duration(v: str) -> bool:
    return bool(_DURATION_RE.match(v))


_FORMAT_CHECKS: dict[str, Callable[[str], bool]] = {
    "date": _is_iso_date,
    "duration": _is_duration,
    "uri": _is_http_uri,
}


def _check_scalar(key: str, value: Any, spec: dict) -> None:
    """Type, enum, and format for one (already-known) value. Raises ToolError."""
    declared = spec.get("type")
    if declared is not None:
        check = _TYPE_CHECKS.get(declared)
        if check is not None and not check(value):
            raise ToolError(
                "bad_type",
                f"parameter {key!r} must be {declared}, got {type(value).__name__}",
            )

    enum = spec.get("enum")
    if enum is not None and value not in enum:
        raise ToolError(
            "not_in_enum",
            f"parameter {key!r} must be one of {list(enum)}, got {value!r}",
        )

    fmt = spec.get("format")
    if fmt is not None and isinstance(value, str):
        checker = _FORMAT_CHECKS.get(fmt)
        # An unknown format name is a schema-authoring error, not a caller error:
        # do not silently pass the value (that would reopen the hole). Refuse.
        if checker is None:
            raise ToolError("bad_format", f"parameter {key!r} declares unknown format {fmt!r}")
        if not checker(value):
            raise ToolError("bad_format", f"parameter {key!r} is not a valid {fmt}: {value!r}")


def _check_object(key: str, value: Any, spec: dict) -> None:
    """One object element against `properties`/`required`/`additionalProperties`.

    Deliberately the same rules as the top level, one level down: unknown keys
    refused, required keys present, each declared property scalar-checked. Not
    recursive beyond this — nothing in the vocabulary nests deeper, and a
    validator that quietly handles a shape no tool uses is untested code.
    """
    if not isinstance(value, dict):
        raise ToolError("bad_type", f"parameter {key!r} must be object, got {type(value).__name__}")

    props: dict = spec.get("properties", {})
    if spec.get("additionalProperties", False) is False:
        unknown = set(value) - set(props)
        if unknown:
            raise ToolError("unknown_param", f"{key}: unknown key(s): {sorted(unknown)}")
    for req in spec.get("required", []):
        if req not in value:
            raise ToolError("missing_param", f"{key}: missing required key: {req!r}")
    for k, sub in props.items():
        if k in value:
            _check_scalar(f"{key}.{k}", value[k], sub)


def validate_args(schema: dict, args: dict) -> dict:
    """Validate ``args`` against an object ``schema`` and return a normalized
    copy with defaults applied. Raises :class:`ToolError` on any violation.

    Enforces (deny-by-default): unknown-key refusal, required keys, `type`,
    `enum` (scalar, array `items`, and object-item `properties`), and `format`
    (`date`, `duration`, `uri`). Author-
    supplied `default`s are trusted and not re-validated. `x-*` annotation keys
    (affordance hints resolved trusted-side) are ignored."""
    if not isinstance(args, dict):
        raise ToolError("bad_args", "arguments must be an object")

    props: dict = schema.get("properties", {})
    required: list = schema.get("required", [])
    additional = schema.get("additionalProperties", False)

    if additional is False:
        unknown = set(args) - set(props)
        if unknown:
            raise ToolError("unknown_param", f"unknown parameter(s): {sorted(unknown)}")

    for key in required:
        if key not in args:
            raise ToolError("missing_param", f"missing required parameter: {key!r}")

    normalized: dict[str, Any] = {}
    for key, spec in props.items():
        if key in args:
            value = args[key]
            _check_scalar(key, value, spec)
            # A closed set on an array field lives on `items`; enforce each
            # element, or the array's enum would be a silent hole while the
            # scalar's is enforced — the same render-≠-enforce gap.
            if spec.get("type") == "array" and isinstance(value, list):
                items = spec.get("items")
                if isinstance(items, dict) and ("enum" in items or "format" in items or "type" in items):
                    for i, elem in enumerate(value):
                        _check_scalar(f"{key}[{i}]", elem, items)
                # An array of OBJECTS: enforce each element's declared
                # properties too. Without this, a closed set on a nested field
                # is offered by the form and enforced by nothing — the entity
                # form's note types are exactly that shape, and `skos:<type>`
                # would mint whatever string arrived. The limitation used to be
                # written into the schema description as a known hole; a hole
                # you have documented is still a hole.
                if isinstance(items, dict) and items.get("properties"):
                    for i, elem in enumerate(value):
                        _check_object(f"{key}[{i}]", elem, items)
            normalized[key] = value
        elif "default" in spec:
            normalized[key] = spec["default"]

    return normalized
