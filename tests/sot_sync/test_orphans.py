"""Orphan report: managed binaries present but not referenced by the RDF."""

from __future__ import annotations

from rdflib import Graph

from cwva_dashboard.sot_sync.orphans import orphan_binaries

REFERENCING_TTL = """
@prefix ex: <http://example.org/> .
ex:w1 a ex:Work ; ex:image <http://cdn.example.org/img/keep.png> .
ex:w2 a ex:Work ; ex:scan "docs/report.pdf" .
"""


def _seed(tmp_path):
    (tmp_path / "img").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "img" / "keep.png").write_bytes(b"1")
    (tmp_path / "img" / "orphan.png").write_bytes(b"2")
    (tmp_path / "docs" / "report.pdf").write_bytes(b"3")
    (tmp_path / "notes.md").write_text("not a binary")


def test_orphan_binaries_flags_unreferenced(tmp_path):
    _seed(tmp_path)
    g = Graph().parse(data=REFERENCING_TTL, format="turtle")
    report = orphan_binaries(g, tmp_path)
    assert report.orphans == ["img/orphan.png"]
    assert report.present == 3  # keep.png, orphan.png, report.pdf
    assert "img/keep.png" not in report.orphans
    assert "docs/report.pdf" not in report.orphans  # referenced by filename


def test_no_orphans_when_all_referenced(tmp_path):
    (tmp_path / "a.png").write_bytes(b"1")
    g = Graph().parse(
        data='@prefix ex: <http://example.org/> . ex:w ex:image <x/a.png> .', format="turtle"
    )
    assert orphan_binaries(g, tmp_path).orphans == []


def test_ignores_qa_internal_and_non_binary(tmp_path):
    (tmp_path / ".qa").mkdir()
    (tmp_path / ".qa" / "cached.png").write_bytes(b"x")  # internal, not content
    (tmp_path / "readme.md").write_text("text")
    g = Graph()
    report = orphan_binaries(g, tmp_path)
    assert report.orphans == []
    assert report.present == 0
