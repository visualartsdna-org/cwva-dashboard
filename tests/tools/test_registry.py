"""Tool registry + dispatcher: schema validation (deny-by-default), dispatch
outcomes, error mapping, audit emission, and MCP-shaped descriptors."""

from __future__ import annotations

import pytest

from cwva_dashboard.sandbox.fileops import FileOps
from cwva_dashboard.sandbox.paths import Sandbox
from cwva_dashboard.tools.base import ToolError, validate_args
from cwva_dashboard.tools.fileops_tools import build_default_registry

from conftest import TEST_DOMAIN


@pytest.fixture
def fileops(tmp_path):
    return FileOps(Sandbox.open(tmp_path / "stage", create=True))


@pytest.fixture
def registry():
    return build_default_registry(domain=TEST_DOMAIN)


# -- validate_args ----------------------------------------------------------

_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "flag": {"type": "boolean", "default": False},
        "n": {"type": "integer"},
    },
    "required": ["path"],
    "additionalProperties": False,
}


def test_validate_fills_defaults():
    out = validate_args(_SCHEMA, {"path": "a"})
    assert out == {"path": "a", "flag": False}


def test_validate_rejects_unknown_param():
    with pytest.raises(ToolError) as ei:
        validate_args(_SCHEMA, {"path": "a", "surprise": 1})
    assert ei.value.code == "unknown_param"


def test_validate_requires_required():
    with pytest.raises(ToolError) as ei:
        validate_args(_SCHEMA, {"flag": True})
    assert ei.value.code == "missing_param"


def test_validate_type_checks_and_excludes_bool_from_int():
    with pytest.raises(ToolError) as ei:
        validate_args(_SCHEMA, {"path": "a", "n": True})  # bool is not integer
    assert ei.value.code == "bad_type"


# -- enum / format (affordance-layer Dispatch enforcement) ------------------
#
# These are the guard the rendered <select> is NOT. Each "reject" case is a
# value a hand-written form would never emit but the Phase-5 agent (second
# driver on the same tools) can — so the assertions are the bypass being closed,
# not merely input hygiene.

_AFFORDANCE_SCHEMA = {
    "type": "object",
    "properties": {
        "units": {"type": "string", "enum": ["cm", "inch", "meter", "pixel"]},
        "when": {"type": "string", "format": "date"},
        "link": {"type": "string", "format": "uri"},
        "tags": {"type": "array", "items": {"type": "string", "enum": ["a", "b", "c"]}},
    },
    "additionalProperties": False,
}


def test_enum_accepts_a_member():
    out = validate_args(_AFFORDANCE_SCHEMA, {"units": "inch"})
    assert out == {"units": "inch"}


def test_enum_rejects_a_non_member():
    # the classic bypass: valid string, wrong value — passes type, fails enum
    with pytest.raises(ToolError) as ei:
        validate_args(_AFFORDANCE_SCHEMA, {"units": "metre"})
    assert ei.value.code == "not_in_enum"


def test_enum_is_case_sensitive():
    with pytest.raises(ToolError) as ei:
        validate_args(_AFFORDANCE_SCHEMA, {"units": "CM"})
    assert ei.value.code == "not_in_enum"


@pytest.mark.parametrize("good", ["2026-07-29", "2000-01-01", "2026-12-31"])
def test_format_date_accepts_canonical_iso(good):
    assert validate_args(_AFFORDANCE_SCHEMA, {"when": good}) == {"when": good}


@pytest.mark.parametrize(
    "bad",
    [
        "2026-13-01",  # month 13
        "2026-02-30",  # not a real day
        "20260729",    # basic form — date.fromisoformat accepts it; we must not
        "2026-7-29",   # unpadded
        "2026/07/29",  # wrong separator
        "July 29, 2026",
        "",
    ],
)
def test_format_date_rejects_noncanonical_or_impossible(bad):
    with pytest.raises(ToolError) as ei:
        validate_args(_AFFORDANCE_SCHEMA, {"when": bad})
    assert ei.value.code == "bad_format"


@pytest.mark.parametrize("good", ["http://x.org/a", "https://en.wikipedia.org/wiki/Art"])
def test_format_uri_accepts_absolute_http(good):
    assert validate_args(_AFFORDANCE_SCHEMA, {"link": good}) == {"link": good}


@pytest.mark.parametrize("bad", ["ftp://x.org/a", "/images/x.jpg", "not a url", "http://"])
def test_format_uri_rejects_non_http_or_relative(bad):
    with pytest.raises(ToolError) as ei:
        validate_args(_AFFORDANCE_SCHEMA, {"link": bad})
    assert ei.value.code == "bad_format"


def test_array_items_enum_is_enforced_per_element():
    # an array's closed set must not be a silent hole while the scalar's is shut
    assert validate_args(_AFFORDANCE_SCHEMA, {"tags": ["a", "c"]}) == {"tags": ["a", "c"]}
    with pytest.raises(ToolError) as ei:
        validate_args(_AFFORDANCE_SCHEMA, {"tags": ["a", "z"]})
    assert ei.value.code == "not_in_enum"


def test_unknown_format_name_is_refused_not_passed():
    # a schema-authoring slip must fail closed, never wave the value through
    schema = {"type": "object", "properties": {"x": {"type": "string", "format": "email"}}}
    with pytest.raises(ToolError) as ei:
        validate_args(schema, {"x": "anything"})
    assert ei.value.code == "bad_format"


def test_defaults_are_not_re_validated():
    # author-supplied defaults are trusted; enum/format apply to caller input only
    schema = {
        "type": "object",
        "properties": {"u": {"type": "string", "enum": ["cm"], "default": "trusted"}},
    }
    assert validate_args(schema, {}) == {"u": "trusted"}


def test_enum_and_format_reach_through_dispatch(registry, fileops):
    # end-to-end: a bad enum at the dispatcher is a structured error, not a raise
    from cwva_dashboard.tools.base import DispatchResult, Tool
    from cwva_dashboard.tools.registry import ToolRegistry

    reg = ToolRegistry()
    reg.register(
        Tool(
            name="x.echo",
            description="echo",
            input_schema={
                "type": "object",
                "properties": {"u": {"type": "string", "enum": ["cm", "inch"]}},
                "required": ["u"],
                "additionalProperties": False,
            },
            handler=lambda fileops, u: {"u": u},
        )
    )
    ok = reg.dispatch("x.echo", {"u": "cm"}, fileops)
    assert ok.ok and ok.result == {"u": "cm"}
    bad = reg.dispatch("x.echo", {"u": "metre"}, fileops)
    assert not bad.ok and bad.error["code"] == "not_in_enum"


# -- dispatch ---------------------------------------------------------------

def test_dispatch_write_then_read(registry, fileops):
    w = registry.dispatch("fs.write", {"path": "a.txt", "text": "hi"}, fileops)
    assert w.ok and w.result["created"] is True
    r = registry.dispatch("fs.read", {"path": "a.txt"}, fileops)
    assert r.ok and r.result["text"] == "hi"


def test_dispatch_unknown_tool(registry, fileops):
    dr = registry.dispatch("fs.nope", {}, fileops)
    assert not dr.ok and dr.error["code"] == "unknown_tool"


def test_dispatch_maps_path_rejection(registry, fileops):
    dr = registry.dispatch("fs.read", {"path": "../escape"}, fileops)
    assert not dr.ok
    assert dr.error["code"] == "path_rejected"
    assert dr.error["reason"] == "traversal"


def test_dispatch_maps_missing_file(registry, fileops):
    dr = registry.dispatch("fs.read", {"path": "ghost.txt"}, fileops)
    assert not dr.ok and dr.error["code"] == "FileNotFoundError"


def test_dispatch_emits_one_audit_event_with_redaction(registry, fileops):
    events = []
    registry.dispatch(
        "fs.write",
        {"path": "a.txt", "text": "supersecret payload"},
        fileops,
        audit=lambda op, args, outcome: events.append((op, args, outcome)),
    )
    assert len(events) == 1
    op, args, outcome = events[0]
    assert op == "fs.write" and outcome == "ok"
    assert args["text"] == "<19 chars>"  # payload redacted, not stored verbatim


def test_schemas_are_mcp_shaped(registry):
    schemas = registry.schemas()
    names = {s["name"] for s in schemas}
    assert {"fs.list", "fs.read", "fs.write", "fs.trash"} <= names
    for s in schemas:
        assert set(s) == {"name", "description", "inputSchema"}
        assert s["inputSchema"]["type"] == "object"
