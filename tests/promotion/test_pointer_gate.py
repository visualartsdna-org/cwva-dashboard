"""The pointer gate: the sidecar/binary invariant is verified at the exit.

`binaries.content_manifest` translates a changed `<x>.ptr` into a push of `<x>`,
trusting fileops to have kept the pair in lockstep. Before this gate that trust
was assumed everywhere and checked nowhere. The gate recomputes sha256 for the
manifest's managed binaries only and **fails** on divergence — healing belongs
to reconcile() and rebuild_sidecars(), on the paths where each direction of
truth is the correct one.

Sidecars are also denied at Layer 1 now (see tests/sandbox_adversarial), so a
mismatch should be unreachable through the tool surface. The gate is kept as
defense against the next way a sidecar goes stale, and these tests therefore
construct divergence by real path, deliberately bypassing that denial.
"""

from __future__ import annotations

import json

import pytest

from cwva_dashboard.promotion.gates import pointer_gate
from cwva_dashboard.promotion.unit import ChangeManifest
from cwva_dashboard.sandbox.fileops import FileOps
from cwva_dashboard.sandbox.paths import Sandbox
from cwva_dashboard.sandbox.pointers import pointer_path_of


def _sandbox_with_image(tmp_path, data=b"REAL-IMAGE-BYTES"):
    ops = FileOps(Sandbox.open(tmp_path))
    ops.write_bytes("content/images/a.png", data, make_parents=True)
    return ops


def test_gate_passes_when_fileops_maintained_the_sidecar(tmp_path):
    _sandbox_with_image(tmp_path)
    result = pointer_gate(tmp_path, ChangeManifest(adds=["content/images/a.png"]))
    assert result.ok
    assert result.name == "pointer"
    assert "1 binary" in result.summary


def test_gate_fails_on_a_rewound_sidecar(tmp_path):
    """The forgery that hides a binary change from the manifest."""
    _sandbox_with_image(tmp_path)
    sidecar = pointer_path_of(tmp_path / "content/images/a.png")
    stale = json.loads(sidecar.read_text())
    stale["sha256"] = "0" * 64
    sidecar.write_text(json.dumps(stale))

    result = pointer_gate(tmp_path, ChangeManifest(modifies=["content/images/a.png"]))
    assert not result.ok
    assert "content/images/a.png" in result.messages[0]
    assert "sha256" in result.messages[0]


def test_gate_fails_when_content_changed_behind_the_sidecar(tmp_path):
    """The other direction: bytes replaced without the sidecar following."""
    _sandbox_with_image(tmp_path)
    (tmp_path / "content/images/a.png").write_bytes(b"SUBSTITUTED")

    result = pointer_gate(tmp_path, ChangeManifest(modifies=["content/images/a.png"]))
    assert not result.ok


def test_gate_fails_on_size_mismatch(tmp_path):
    _sandbox_with_image(tmp_path)
    sidecar = pointer_path_of(tmp_path / "content/images/a.png")
    d = json.loads(sidecar.read_text())
    d["size"] = d["size"] + 1
    sidecar.write_text(json.dumps(d))

    result = pointer_gate(tmp_path, ChangeManifest(adds=["content/images/a.png"]))
    assert not result.ok
    assert "size" in result.messages[0]


@pytest.mark.parametrize("missing", ["binary", "sidecar"])
def test_gate_fails_when_half_the_pair_is_absent(tmp_path, missing):
    _sandbox_with_image(tmp_path)
    binary = tmp_path / "content/images/a.png"
    (binary if missing == "binary" else pointer_path_of(binary)).unlink()

    result = pointer_gate(tmp_path, ChangeManifest(adds=["content/images/a.png"]))
    assert not result.ok


def test_gate_fails_on_an_unparseable_sidecar(tmp_path):
    _sandbox_with_image(tmp_path)
    pointer_path_of(tmp_path / "content/images/a.png").write_text("{not json")

    result = pointer_gate(tmp_path, ChangeManifest(adds=["content/images/a.png"]))
    assert not result.ok
    assert "sidecar" in result.messages[0]


def test_gate_ignores_deletes_and_non_binaries(tmp_path):
    """A deleted binary is meant to be gone, and RDF/markdown carry no sidecar."""
    ops = FileOps(Sandbox.open(tmp_path))
    ops.write_text("content/ttl/data/w1.ttl", "# ttl", make_parents=True)
    ops.write_text("content/documents/note.md", "note", make_parents=True)

    result = pointer_gate(
        tmp_path,
        ChangeManifest(
            adds=["content/ttl/data/w1.ttl", "content/documents/note.md"],
            deletes=["content/images/gone.png"],
        ),
    )
    assert result.ok


def test_gate_only_hashes_manifest_paths(tmp_path):
    """Scoped to the manifest: an inconsistency elsewhere in the tree is not
    this promotion's business (and the gate must not walk the whole tree)."""
    ops = _sandbox_with_image(tmp_path)
    ops.write_bytes("content/images/other.png", b"OTHER", make_parents=True)
    pointer_path_of(tmp_path / "content/images/other.png").write_text(
        json.dumps({"sha256": "f" * 64, "size": 5, "created": ""})
    )

    result = pointer_gate(tmp_path, ChangeManifest(adds=["content/images/a.png"]))
    assert result.ok
