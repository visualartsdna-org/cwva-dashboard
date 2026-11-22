"""doc.set_id: stamp a markdown document with the CURIE of its record.

Concept derivation and tagging find a document's entity by reading that line.
It has been a manual step — 5 of the 70 markdown files in the store carry it —
and the convention those five follow is exact: `[id=work:<guid>]`, alone on
line 2, directly under the `# Title`.
"""

from __future__ import annotations

import pytest

from cwva_dashboard.sandbox.fileops import FileOps
from cwva_dashboard.sandbox.paths import Sandbox
from cwva_dashboard.tools.fileops_tools import build_default_registry

from conftest import TEST_DOMAIN

# The real shape, from Claude-WatercolorArtCriticismOfSpiritedTree.md.
REAL = """# Watercolor art criticism of Spirited Tree
**Created:** 6/8/2026 10:17:45  
**Updated:** 6/8/2026 20:59:07  

Body of the criticism.
"""


@pytest.fixture
def env(tmp_path):
    sb = Sandbox.open(tmp_path / "stage", create=True)
    return build_default_registry(domain=TEST_DOMAIN), FileOps(sb), sb


def _set(reg, ops, path, curie="work:abc123"):
    dr = reg.dispatch("doc.set_id", {"path": path, "curie": curie}, ops)
    assert dr.ok, dr.error
    return dr.result


def test_registered(env):
    reg, _, _ = env
    assert "doc.set_id" in reg.names()


def test_the_id_lands_on_line_2_under_the_title(env):
    reg, ops, _ = env
    ops.write_text("d.md", REAL, make_parents=True)

    res = _set(reg, ops, "d.md")
    lines = ops.read_text("d.md").splitlines()

    assert res["line"] == 2 and res["changed"]
    assert lines[0].startswith("# Watercolor art criticism")
    assert lines[1] == "[id=work:abc123]"
    assert lines[2].startswith("**Created:**"), "the rest of the file is undisturbed"


def test_stamping_twice_changes_nothing(env):
    """Entry can be re-run. Without idempotence a second submission appends a
    second id line and the derivation step has two answers to choose from."""
    reg, ops, _ = env
    ops.write_text("d.md", REAL, make_parents=True)
    _set(reg, ops, "d.md")
    first = ops.read_text("d.md")

    again = _set(reg, ops, "d.md")

    assert again["changed"] is False
    assert ops.read_text("d.md") == first


def test_an_existing_id_is_REPLACED_where_it_sits(env):
    """Not moved. If a document keeps its id somewhere else that is the author's
    arrangement, and rewriting the file's shape is not this tool's business."""
    reg, ops, _ = env
    ops.write_text("d.md", "# Title\nintro\n[id=work:OLD]\nbody\n", make_parents=True)

    res = _set(reg, ops, "d.md", "work:NEW")
    lines = ops.read_text("d.md").splitlines()

    assert res["line"] == 3
    assert lines == ["# Title", "intro", "[id=work:NEW]", "body"]
    assert "work:OLD" not in ops.read_text("d.md")


def test_an_empty_document_gets_the_id_as_its_first_line(env):
    reg, ops, _ = env
    ops.write_text("d.md", "", make_parents=True)

    res = _set(reg, ops, "d.md")

    assert res["line"] == 1
    assert ops.read_text("d.md").strip() == "[id=work:abc123]"


def test_a_one_line_document_gets_the_id_beneath_it(env):
    reg, ops, _ = env
    ops.write_text("d.md", "# Only line", make_parents=True)

    _set(reg, ops, "d.md")

    assert ops.read_text("d.md").splitlines() == ["# Only line", "[id=work:abc123]"]


def test_the_trailing_newline_state_is_preserved(env):
    """Rewriting a file should not show up as a whitespace diff in the QA git."""
    reg, ops, _ = env
    ops.write_text("with.md", "# T\nbody\n", make_parents=True)
    ops.write_text("without.md", "# T\nbody", make_parents=True)

    _set(reg, ops, "with.md")
    _set(reg, ops, "without.md")

    assert ops.read_text("with.md").endswith("\n")
    assert not ops.read_text("without.md").endswith("\n")


def test_an_empty_curie_is_refused(env):
    reg, ops, _ = env
    ops.write_text("d.md", REAL, make_parents=True)

    dr = reg.dispatch("doc.set_id", {"path": "d.md", "curie": "  "}, ops)

    assert not dr.ok and dr.error["code"] == "bad_args"


def test_a_line_that_merely_CONTAINS_an_id_is_not_the_id_line(env):
    """The convention is the whole line and nothing else. Prose mentioning
    `[id=...]` must not be rewritten."""
    reg, ops, _ = env
    ops.write_text(
        "d.md", "# T\nSee the marker [id=work:X] used in these files.\nbody\n",
        make_parents=True,
    )

    res = _set(reg, ops, "d.md")
    lines = ops.read_text("d.md").splitlines()

    assert res["line"] == 2
    assert lines[1] == "[id=work:abc123]"
    assert "See the marker [id=work:X]" in lines[2], "the prose is untouched"
