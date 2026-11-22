"""Change preview: file-level manifest + isomorphic RDF graph diff. The diff is
graph-based, so blank-node relabeling and triple reordering are NOT changes;
only real triple add/remove is."""

from __future__ import annotations

import shutil

import pytest

from cwva_dashboard.promotion.preview import build_preview
from cwva_dashboard.promotion.qa_git import QAGit

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

WORKS_BASE = """
@prefix ex: <http://example.org/> .
ex:w1 a ex:Work ; ex:title "Sunrise" .
"""


def _qa(tmp_path):
    root = tmp_path / "qa"
    root.mkdir()
    return QAGit.init(root)


def test_preview_add_modify_and_types(tmp_path):
    qa = _qa(tmp_path)
    (qa.root / "works.ttl").write_text(WORKS_BASE)
    base = qa.commit("seed works")

    # modify w1's title, add w2 (Work), and a new file with a Criticism.
    (qa.root / "works.ttl").write_text(
        """
@prefix ex: <http://example.org/> .
ex:w1 a ex:Work ; ex:title "Dawn" .
ex:w2 a ex:Work ; ex:title "Dusk" .
"""
    )
    (qa.root / "crit.ttl").write_text(
        """
@prefix ex: <http://example.org/> .
ex:c1 a ex:Criticism ; ex:about ex:w1 .
"""
    )

    manifest = qa.manifest_since(base)
    p = build_preview(qa, manifest, base)

    assert manifest.adds == ["crit.ttl"]
    assert manifest.modifies == ["works.ttl"]
    # w2 and c1 are new subjects; w1 is modified (title changed), none removed.
    assert p.subjects_added == ["http://example.org/c1", "http://example.org/w2"]
    assert p.subjects_modified == ["http://example.org/w1"]
    assert p.subjects_removed == []
    assert p.added_by_type == {"Work": 1, "Criticism": 1}
    # +: w2 type+title (2), c1 type+about (2), w1 new title (1) = 5; -: old title 1
    assert p.triples_added == 5
    assert p.triples_removed == 1
    assert "adds 1 Criticism, 1 Work" in p.summary()


def test_preview_deletion_reports_removed_subjects(tmp_path):
    qa = _qa(tmp_path)
    (qa.root / "works.ttl").write_text(WORKS_BASE)
    base = qa.commit("seed")
    (qa.root / "works.ttl").unlink()

    manifest = qa.manifest_since(base)
    p = build_preview(qa, manifest, base)
    assert manifest.deletes == ["works.ttl"]
    assert p.subjects_removed == ["http://example.org/w1"]
    assert p.removed_by_type == {"Work": 1}
    assert p.triples_added == 0 and p.triples_removed == 2


def test_preview_bnode_relabel_is_not_a_change(tmp_path):
    qa = _qa(tmp_path)
    (qa.root / "g.ttl").write_text(
        """
@prefix ex: <http://example.org/> .
ex:w1 ex:dimensions [ ex:h 10 ; ex:w 20 ] .
"""
    )
    base = qa.commit("seed bnode")
    # Same graph, different blank-node id and reordered — isomorphic.
    (qa.root / "g.ttl").write_text(
        """
@prefix ex: <http://example.org/> .
ex:w1 ex:dimensions [ ex:w 20 ; ex:h 10 ] .
"""
    )
    manifest = qa.manifest_since(base)
    # The file changed textually...
    assert manifest.modifies == ["g.ttl"]
    p = build_preview(qa, manifest, base)
    # ...but the graph did not.
    assert p.triples_added == 0
    assert p.triples_removed == 0
    assert p.subjects_modified == []


def test_preview_reorder_and_whitespace_is_not_a_change(tmp_path):
    qa = _qa(tmp_path)
    (qa.root / "g.ttl").write_text(
        "@prefix ex: <http://example.org/> .\nex:a ex:p 1 .\nex:b ex:p 2 .\n"
    )
    base = qa.commit("seed")
    (qa.root / "g.ttl").write_text(
        "@prefix ex: <http://example.org/> .\n\nex:b ex:p 2 .\nex:a ex:p 1 .\n"
    )
    p = build_preview(qa, qa.manifest_since(base), base)
    assert p.triples_added == 0 and p.triples_removed == 0


def test_preview_nonrdf_files_reported_without_triple_diff(tmp_path):
    qa = _qa(tmp_path)
    (qa.root / "notes.md").write_text("# v1")
    base = qa.commit("seed md")
    (qa.root / "notes.md").write_text("# v2 with more")

    p = build_preview(qa, qa.manifest_since(base), base)
    assert p.nonrdf_files == ["notes.md"]
    assert p.rdf_files == []
    assert p.triples_added == 0 and p.triples_removed == 0
    assert "non-RDF: notes.md" in p.summary()


def test_preview_to_dict_roundtrips_shape(tmp_path):
    qa = _qa(tmp_path)
    (qa.root / "works.ttl").write_text(WORKS_BASE)
    base = qa.commit("seed")
    (qa.root / "works.ttl").write_text(WORKS_BASE + 'ex:w9 a <http://example.org/Work> .\n')
    d = build_preview(qa, qa.manifest_since(base), base).to_dict()
    assert set(d) >= {"manifest", "rdf_files", "triples_added", "summary", "added_by_type"}
    assert d["manifest"]["modifies"] == ["works.ttl"]


def test_a_relative_IRI_does_not_CRASH_the_preview(tmp_path):
    """One artist record carrying `foaf:homepage <bj.net>` made every preview
    raise — reaching Rick as a server error with no failing gate to explain it
    (2026-09-17). The base is stable AND resolvable now: stable so the same
    relative IRI reads the same before and after, resolvable because rdflib
    refuses a URN as a base ("has no slash after colon").
    """
    qa = _qa(tmp_path)
    base = qa.commit("seed", allow_empty=True)
    (qa.root / "artist.ttl").write_text(
        "@prefix foaf: <http://xmlns.com/foaf/0.1/> .\n"
        "<http://example.org/work/a> foaf:homepage <bj.net> .\n"
    )

    p = build_preview(qa, qa.manifest_since(base), base)

    assert p.triples_added == 1
    assert p.triples_removed == 0
