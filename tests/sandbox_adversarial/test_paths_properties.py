"""Property-based confinement tests (CE_DESIGN §2.4).

The corpus (``test_paths_reject.py``) pins named escape classes; these
properties assert the *invariants* that must hold for every input, generated or
not. The load-bearing one is :func:`test_resolve_never_escapes`: for any string
whatsoever, ``resolve`` either refuses it or returns a path inside the sandbox —
there is no third outcome. The rest guard determinism and the reject-not-
sanitize contract.
"""

from __future__ import annotations

import os
import uuid

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from cwva_dashboard.sandbox.fileops import FileOps
from cwva_dashboard.sandbox.paths import PathRejected, Sandbox

# The sandbox is only read from in these properties (except the fileops
# round-trip, which writes unique names), so reusing one across examples is
# safe; silence Hypothesis's function-scoped-fixture health check.
_HC = [HealthCheck.function_scoped_fixture]

_RESERVED = (
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)

# Alphabet for provably-safe segments: no separators, dots, spaces, control,
# or Windows-invalid chars — so an accepted input maps 1:1 to its components.
_SAFE_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_+="


def _is_safe_segment(seg: str) -> bool:
    return bool(seg) and seg.upper() not in _RESERVED


_safe_segment = st.text(alphabet=_SAFE_ALPHABET, min_size=1, max_size=12).filter(
    _is_safe_segment
)
_safe_path = st.lists(_safe_segment, min_size=1, max_size=5).map("/".join)

# Hazardous tokens interleaved with safe ones to manufacture nasty paths.
_hazard_token = st.sampled_from(
    ["..", ".", "", "/", "\\", "\x00", "\x01", ":", "*", "?", '"', "|",
     "CON", "NUL", "COM1", "LPT9.txt", "foo.", "bar ", "~", "C:", "..\\",
     "//", "\\\\?\\", "a", "b"]
)
_weird_path = st.lists(
    st.one_of(_hazard_token, _safe_segment, st.text(max_size=6)), min_size=1, max_size=6
).map("/".join)

_any_path = st.one_of(st.text(), _safe_path, _weird_path)


@pytest.fixture
def sandbox(tmp_path):
    return Sandbox.open(tmp_path / "stage", create=True)


def _classify(sb: Sandbox, s: str):
    try:
        return ("ok", sb.resolve(s).as_posix())
    except PathRejected as exc:
        return ("reject", exc.reason)


@pytest.mark.adversarial
@settings(max_examples=400, deadline=None, suppress_health_check=_HC)
@given(s=_any_path)
def test_resolve_never_escapes(sandbox, s):
    """The one invariant: accept-inside-root or reject. Never a path outside."""
    try:
        resolved = sandbox.resolve(s)
    except PathRejected:
        return
    assert resolved == sandbox.root or resolved.is_relative_to(sandbox.root)


@pytest.mark.adversarial
@settings(max_examples=300, deadline=None, suppress_health_check=_HC)
@given(s=_any_path)
def test_resolve_is_deterministic(sandbox, s):
    assert _classify(sandbox, s) == _classify(sandbox, s)


@pytest.mark.adversarial
@settings(max_examples=300, deadline=None, suppress_health_check=_HC)
@given(s=_safe_path)
def test_accepted_paths_are_not_sanitized(sandbox, s):
    """A safe path is accepted and returned verbatim (relative to root) — the
    resolver confines, it never silently rewrites."""
    resolved = sandbox.resolve(s)
    assert resolved.relative_to(sandbox.root).as_posix() == s


@pytest.mark.adversarial
@settings(max_examples=300, deadline=None, suppress_health_check=_HC)
@given(
    prefix=st.lists(_safe_segment, max_size=3),
    suffix=st.lists(_safe_segment, max_size=3),
)
def test_dotdot_component_always_rejected(sandbox, prefix, suffix):
    """Any path with a bare '..' component is refused, wherever it sits."""
    parts = [*prefix, "..", *suffix]
    with pytest.raises(PathRejected):
        sandbox.resolve("/".join(parts))


@pytest.mark.adversarial
@settings(max_examples=150, deadline=None, suppress_health_check=_HC)
@given(s=_safe_path, data=st.binary(max_size=256))
def test_fileops_write_read_roundtrip_stays_contained(sandbox, s, data):
    # Isolate each example in a fresh sub-sandbox: examples share the fixture,
    # and one example's "a" file would otherwise collide with another's "a/b".
    sub = sandbox.root / f"ex{uuid.uuid4().hex}"
    sub.mkdir()
    ops = FileOps(Sandbox.open(sub))

    res = ops.write_bytes(s, data, make_parents=True)
    assert ops.read_bytes(s) == data
    # The written file is a real path under the sub-sandbox root.
    written = sub / res.path
    assert written.is_relative_to(sub)
    assert os.path.exists(written)
