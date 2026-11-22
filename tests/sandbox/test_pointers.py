"""Binary-asset pointers through the fileops chokepoint: sidecar consistency on
write/move/copy/trash, attic on replacement, and reconcile (rollback support)."""

from __future__ import annotations

import hashlib

from cwva_dashboard.sandbox.fileops import FileOps
from cwva_dashboard.sandbox.paths import Sandbox
from cwva_dashboard.sandbox.pointers import Pointer, PointerManager, pointer_path_of


def _sb_ops(tmp_path):
    sb = Sandbox.open(tmp_path / "stage", create=True)
    return sb, FileOps(sb)


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def test_write_managed_binary_creates_synced_sidecar(tmp_path):
    sb, ops = _sb_ops(tmp_path)
    ops.write_bytes("img/a.png", b"IMGV1", make_parents=True)

    assert (sb.root / "img" / "a.png").read_bytes() == b"IMGV1"
    ptr = pointer_path_of(sb.root / "img" / "a.png")
    assert ptr.exists()
    p = Pointer.from_json(ptr.read_text())
    assert p.sha256 == _sha(b"IMGV1")
    assert p.size == 5


def test_non_managed_file_gets_no_sidecar(tmp_path):
    sb, ops = _sb_ops(tmp_path)
    ops.write_text("notes.md", "hi")
    assert not pointer_path_of(sb.root / "notes.md").exists()


def test_overwrite_attics_superseded_content_and_updates_pointer(tmp_path):
    sb, ops = _sb_ops(tmp_path)
    ops.write_bytes("a.png", b"V1")
    ops.write_bytes("a.png", b"V2-longer")

    # superseded content preserved in the content-addressed attic
    attic_blob = sb.root / ".qa" / "attic" / _sha(b"V1")
    assert attic_blob.read_bytes() == b"V1"
    # pointer now reflects the new content
    p = Pointer.from_json(pointer_path_of(sb.root / "a.png").read_text())
    assert p.sha256 == _sha(b"V2-longer")


def test_move_managed_binary_moves_sidecar(tmp_path):
    sb, ops = _sb_ops(tmp_path)
    ops.write_bytes("a.png", b"V1")
    ops.move("a.png", "b.png")
    assert not (sb.root / "a.png").exists()
    assert not pointer_path_of(sb.root / "a.png").exists()
    assert (sb.root / "b.png").read_bytes() == b"V1"
    assert pointer_path_of(sb.root / "b.png").exists()


def test_copy_managed_binary_writes_new_sidecar(tmp_path):
    sb, ops = _sb_ops(tmp_path)
    ops.write_bytes("a.png", b"V1")
    ops.copy("a.png", "c.png")
    assert pointer_path_of(sb.root / "c.png").exists()
    assert pointer_path_of(sb.root / "a.png").exists()  # original intact


def test_trash_managed_binary_takes_sidecar_along(tmp_path):
    sb, ops = _sb_ops(tmp_path)
    ops.write_bytes("a.png", b"V1")
    ops.trash("a.png")
    assert not (sb.root / "a.png").exists()
    assert not pointer_path_of(sb.root / "a.png").exists()
    trash = sb.root / ".qa" / "trash"
    names = [f.name for f in trash.iterdir()]
    assert any(n.endswith(".png") and not n.endswith(".ptr") for n in names)
    assert any(n.endswith(".png.ptr") for n in names)


def test_reconcile_rematerializes_binary_from_attic(tmp_path):
    sb, ops = _sb_ops(tmp_path)
    ops.write_bytes("a.png", b"V1")
    ops.write_bytes("a.png", b"V2")  # V1 -> attic
    # Simulate a git tree restore: sidecar rolled back to V1, binary still V2.
    pointer_path_of(sb.root / "a.png").write_text(
        Pointer(sha256=_sha(b"V1"), size=2, created="").to_json()
    )

    mgr = PointerManager(sb.root)
    res = mgr.reconcile(sb.root)
    assert (sb.root / "a.png").read_bytes() == b"V1"
    assert "a.png" in res["restored"]


def test_reconcile_removes_binary_whose_pointer_is_gone(tmp_path):
    sb, ops = _sb_ops(tmp_path)
    ops.write_bytes("x.png", b"data")
    pointer_path_of(sb.root / "x.png").unlink()  # pointer removed by restore

    res = PointerManager(sb.root).reconcile(sb.root)
    assert not (sb.root / "x.png").exists()
    assert "x.png" in res["removed"]
