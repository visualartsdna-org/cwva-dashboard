"""The panel's content graph is cached — and must invalidate.

Why this exists: answering standing queries re-reads every record, so a poll
cost one fileops call per record. At 328 records that is 329 ops per poll,
which at the hub's polling interval exceeds the entire per-minute quota on an
*idle* dashboard — it surfaced as `quota_exceeded` on an unrelated Create
record, which merely happened to be operation 601.

The risk a cache introduces is staleness, so the invalidation is what these
tests are mostly about.
"""

from __future__ import annotations

import time

import pytest

from rdflib import Literal, URIRef

from cwva_dashboard.sandbox.fileops import FileOps
from cwva_dashboard.sandbox.paths import Sandbox
from cwva_dashboard.tools import workflow_tools

TTL = '@prefix ex: <http://example.org/> .\nex:{n} ex:p "{v}" .\n'


@pytest.fixture
def ops(tmp_path):
    workflow_tools._FILE_CACHE.clear()
    (tmp_path / "data").mkdir()
    return FileOps(Sandbox.open(tmp_path))


def _counting(ops):
    calls = {"n": 0}
    orig = ops._begin

    def counted(op, args):
        calls["n"] += 1
        return orig(op, args)

    ops._begin = counted
    return calls


def _value(graph, n) -> str | None:
    """The object of ex:<n> ex:p — asserted as a triple, never as serialized
    text (the project's own rule, and rdflib picks its own prefixes anyway)."""
    o = graph.value(URIRef(f"http://example.org/{n}"), URIRef("http://example.org/p"))
    return str(o) if isinstance(o, Literal) else None


def _write(ops, name, n, v):
    ops.write_text(f"data/{name}", TTL.format(n=n, v=v))


def _settle():
    """Wait past the racy-clean window.

    A file whose mtime is not strictly older than its cache entry is re-read
    rather than trusted, because filesystem timestamp granularity means a write
    can land in the same tick as the cache and leave the key unchanged. Tests
    that measure the CHEAP path must therefore let their fixture writes settle —
    in practice a poll happens seconds to minutes after a record is written, not
    microseconds.
    """
    time.sleep(workflow_tools._RACY_WINDOW_NS / 1e9 * 1.5)


def test_an_unchanged_directory_costs_one_op(ops):
    for i in range(5):
        _write(ops, f"w{i}.ttl", i, "a")
    _settle()
    calls = _counting(ops)

    workflow_tools._content_graph(ops, "data")
    cold = calls["n"]
    calls["n"] = 0
    workflow_tools._content_graph(ops, "data")

    assert cold == 6, "one list + one read per record"
    assert calls["n"] == 1, "a warm poll is a single list_dir"


def test_a_new_record_invalidates(ops):
    _write(ops, "w1.ttl", 1, "a")
    first = workflow_tools._content_graph(ops, "data")
    assert len(first) == 1

    _write(ops, "w2.ttl", 2, "a")

    assert len(workflow_tools._content_graph(ops, "data")) == 2


def test_a_deleted_record_invalidates(ops):
    _write(ops, "w1.ttl", 1, "a")
    _write(ops, "w2.ttl", 2, "a")
    assert len(workflow_tools._content_graph(ops, "data")) == 2

    ops.trash("data/w2.ttl")

    assert len(workflow_tools._content_graph(ops, "data")) == 1


def test_a_SAME_LENGTH_edit_invalidates(ops):
    """The reason the key carries mtime and not just size. A flag flipping
    false->true is the same number of bytes, and a size-only key would serve a
    stale panel forever."""
    _write(ops, "w1.ttl", 1, "a")
    before = workflow_tools._content_graph(ops, "data")
    assert _value(before, 1) == "a"

    _write(ops, "w1.ttl", 1, "b")  # identical length, different content

    assert _value(workflow_tools._content_graph(ops, "data"), 1) == "b"


def test_directories_are_cached_independently(ops):
    (ops._sb.root / "other").mkdir()
    _write(ops, "w1.ttl", 1, "a")
    ops.write_text("other/z.ttl", TTL.format(n=9, v="z"))

    assert len(workflow_tools._content_graph(ops, "data")) == 1
    assert len(workflow_tools._content_graph(ops, "other")) == 1


def test_a_missing_directory_is_empty_not_an_error(ops):
    assert len(workflow_tools._content_graph(ops, "nope")) == 0


def test_a_poll_after_one_edit_costs_TWO_ops_not_a_full_rescan(ops):
    """The property that keeps a burst of entries under the quota: cost is
    proportional to what changed, not to how much exists. A whole-tree rescan
    per change would still trip the limit after two entries in a minute."""
    for i in range(20):
        _write(ops, f"w{i}.ttl", i, "a")
    _settle()
    workflow_tools._content_graph(ops, "data")  # warm

    _write(ops, "w7.ttl", 7, "b")  # one record changes
    calls = _counting(ops)
    g = workflow_tools._content_graph(ops, "data")

    assert calls["n"] == 2, "one list_dir + one re-read of the changed record"
    assert len(g) == 20, "the whole set is still returned"
    assert _value(g, 7) == "b", "the changed record is fresh"
    assert _value(g, 6) == "a", "unchanged records come from cache intact"


def test_a_write_in_the_SAME_TICK_is_not_trusted(ops):
    """The cache-coherency race, and why the window exists.

    Filesystem timestamps are not infinitely fine-grained. A same-length write
    landing in the same tick as the cache entry leaves (size, mtime_ns)
    identical, so a naive key would serve stale content indefinitely. Git calls
    such an entry "racily clean" and re-reads it; so does this. Caught by an
    intermittently failing test, which is the only way this shows up.
    """
    _write(ops, "w1.ttl", 1, "a")
    workflow_tools._content_graph(ops, "data")  # cached immediately, still racy
    _write(ops, "w1.ttl", 1, "b")  # same length, very likely the same tick

    assert _value(workflow_tools._content_graph(ops, "data"), 1) == "b"
