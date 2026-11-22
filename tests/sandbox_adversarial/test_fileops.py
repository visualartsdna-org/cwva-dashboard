"""Fileops chokepoint tests: roundtrips, confinement pass-through, quotas,
soft delete."""

from __future__ import annotations

import pytest

from cwva_dashboard.sandbox.fileops import FileOps
from cwva_dashboard.sandbox.paths import PathRejected, Sandbox
from cwva_dashboard.sandbox.quotas import QuotaExceeded, Quotas


@pytest.fixture
def ops(tmp_path):
    sb = Sandbox.open(tmp_path / "stage", create=True)
    return FileOps(sb, Quotas(max_file_bytes=1024, max_file_count=10))


def test_write_read_roundtrip(ops):
    res = ops.write_text("dir/note.md", "hello", make_parents=True)
    assert res.created is True
    assert res.path == "dir/note.md"
    assert ops.read_text("dir/note.md") == "hello"


def test_overwrite_reports_not_created(ops):
    ops.write_text("a.txt", "one", make_parents=True)
    res = ops.write_text("a.txt", "two")
    assert res.created is False
    assert ops.read_text("a.txt") == "two"


def test_list_dir_sorted_and_relative(ops):
    ops.mkdir("d")
    ops.write_text("d/b.txt", "b")
    ops.write_text("d/a.txt", "a")
    names = [e.name for e in ops.list_dir("d")]
    assert names == ["a.txt", "b.txt"]
    assert all(e.path.startswith("d/") for e in ops.list_dir("d"))


def test_move_and_copy(ops):
    ops.write_text("src.txt", "x")
    ops.copy("src.txt", "copy.txt")
    assert ops.read_text("copy.txt") == "x"
    ops.move("src.txt", "moved.txt")
    assert ops.read_text("moved.txt") == "x"
    with pytest.raises(FileNotFoundError):
        ops.read_text("src.txt")


def test_move_no_clobber_without_overwrite(ops):
    ops.write_text("a.txt", "a")
    ops.write_text("b.txt", "b")
    with pytest.raises(FileExistsError):
        ops.move("a.txt", "b.txt")


def test_trash_soft_deletes(ops):
    ops.write_text("doomed.txt", "bye")
    trashed = ops.trash("doomed.txt")
    assert trashed.startswith(".qa/trash/")
    with pytest.raises(FileNotFoundError):
        ops.read_text("doomed.txt")
    # The bytes still exist under trash.
    assert ops.read_text(trashed) == "bye"


def test_confinement_passes_through(ops):
    with pytest.raises(PathRejected):
        ops.write_text("../escape.txt", "nope")
    with pytest.raises(PathRejected):
        ops.read_text("/etc/passwd")


def test_size_quota_enforced(ops):
    with pytest.raises(QuotaExceeded) as ei:
        ops.write_bytes("big.bin", b"x" * 2048)
    assert ei.value.limit == "max_file_bytes"


def test_count_quota_enforced(ops):
    for i in range(10):
        ops.write_text(f"f{i}.txt", "x")
    with pytest.raises(QuotaExceeded) as ei:
        ops.write_text("f10.txt", "x")
    assert ei.value.limit == "max_file_count"


def test_audit_hook_receives_calls(tmp_path):
    events = []
    sb = Sandbox.open(tmp_path / "stage", create=True)
    ops = FileOps(sb, audit=lambda op, args, outcome: events.append((op, outcome)))
    ops.write_text("a.txt", "x")
    ops.read_text("a.txt")
    assert ("write_bytes", "ok") in events
    assert ("read_bytes", "ok") in events
