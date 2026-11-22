"""Drafts as records (promotion/drafts.py).

Rick, 2026-09-18: "we need to treat drafts as first-class citizens." They were
files git had not seen, visible only in a preview or on a page that speaks in
paths. A draft is a RECORD — label, kind, age, its attachments, and a way back
to the editor that made it.
"""

from __future__ import annotations

import shutil

import pytest

from cwva_dashboard.promotion.drafts import DraftIndex
from cwva_dashboard.promotion.layout import Layout
from cwva_dashboard.promotion.qa_git import QAGit
from cwva_dashboard.sandbox.pointers import PointerManager

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

GUID = "a6671c83-4ebc-4c2d-84f2-8671d2c8e597"
OTHER = "b7782d94-5fcd-4e3d-95g3-9782e3d9a608".replace("g", "a")

REC = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix vad: <http://visualartsdna.org/model/> .
@prefix work: <http://visualartsdna.org/work/> .
work:{guid} a vad:Watercolor ; rdfs:label "{label}" .
"""


@pytest.fixture
def qa(tmp_path):
    root = tmp_path / "qa"
    root.mkdir()
    repo = QAGit.init(root)
    (root / Layout.default().dir("work_ttl")).mkdir(parents=True)
    return repo


@pytest.fixture
def index(qa):
    return DraftIndex(qa, pointers=PointerManager(qa.root),
                      work_ns="http://visualartsdna.org/work/")


def _write(qa, guid, label="A work"):
    p = qa.root / Layout.default().dir("work_ttl") / f"{guid}.ttl"
    p.write_text(REC.format(guid=guid, label=label))
    return p


def test_a_draft_is_a_RECORD_not_a_path(index, qa):
    _write(qa, GUID, "Spirited Tree")

    drafts, orphans = index.list()

    assert len(drafts) == 1
    d = drafts[0]
    assert d["label"] == "Spirited Tree" and d["guid"] == GUID
    assert d["kinds"] == ["Watercolor"] and d["new"] is True
    assert orphans == []


def test_its_ATTACHMENTS_come_with_it(index, qa):
    """A QR and an ingested image are part of the draft, not three drafts."""
    _write(qa, GUID)
    images = qa.root / Layout.default().dir("image")
    images.mkdir(parents=True, exist_ok=True)
    (images / f"qrc_{GUID}.jpg").write_bytes(b"\xff\xd8qr")
    (images / f"qrc_{GUID}.jpg.ptr").write_text("{}")

    drafts, orphans = index.list()

    assert len(drafts) == 1
    assert any(f.endswith(f"qrc_{GUID}.jpg.ptr") for f in drafts[0]["files"])
    assert orphans == [], "nothing loose that belongs to a record"


def test_a_file_it_cannot_ATTRIBUTE_is_reported_not_absorbed(index, qa):
    """A file we cannot place must not disappear into somebody's record."""
    _write(qa, GUID)
    images = qa.root / Layout.default().dir("image")
    images.mkdir(parents=True, exist_ok=True)
    (images / "stray.jpg.ptr").write_text("{}")

    drafts, orphans = index.list()

    assert len(drafts) == 1
    assert any(o.endswith("stray.jpg.ptr") for o in orphans)


def test_a_MODIFIED_record_is_a_draft_too_and_knows_it(index, qa):
    _write(qa, GUID, "Distributed")
    qa.stage_all(); qa.commit("distributed")
    _write(qa, GUID, "Changed since")

    drafts, _ = index.list()

    assert drafts[0]["new"] is False
    assert drafts[0]["label"] == "Changed since"


def test_DISCARDING_a_new_draft_removes_it(index, qa):
    _write(qa, GUID)
    path = qa.root / Layout.default().dir("work_ttl") / f"{GUID}.ttl"

    out = index.discard([GUID])

    assert out["discarded"] and not path.exists()
    assert index.list()[0] == []


def test_DISCARDING_a_modified_draft_returns_it_to_the_DISTRIBUTED_state(index, qa):
    """Not to where this session started — to what the SOT last agreed to.
    That is the difference between discarding a draft and leaving a review."""
    _write(qa, GUID, "Distributed")
    qa.stage_all(); qa.commit("distributed")
    _write(qa, GUID, "Changed since")

    index.discard([GUID])

    path = qa.root / Layout.default().dir("work_ttl") / f"{GUID}.ttl"
    assert "Distributed" in path.read_text()
    assert index.list()[0] == []


def test_discarding_ONE_leaves_the_others(index, qa):
    _write(qa, GUID, "Keep me")
    _write(qa, OTHER, "Throw me")

    index.discard([OTHER])

    labels = [d["label"] for d in index.list()[0]]
    assert labels == ["Keep me"]


def test_DISCARD_ALL_is_just_every_guid(index, qa):
    _write(qa, GUID, "One")
    _write(qa, OTHER, "Two")

    out = index.discard([d["guid"] for d in index.list()[0]])

    assert sorted(out["records"]) == ["One", "Two"]
    assert index.count() == 0


def test_the_count_is_what_the_hub_shows(index, qa):
    assert index.count() == 0
    _write(qa, GUID)
    assert index.count() == 1


# -- one draft, in detail -----------------------------------------------------


def test_detail_shows_the_record_AS_WRITTEN(index, qa):
    """Only the text says whether the triples are right — the same reasoning as
    the review stop's Generated RDF."""
    _write(qa, GUID, "Spirited Tree")

    d = index.detail(GUID)

    assert 'rdfs:label "Spirited Tree"' in d["text"]
    assert d["distributed"] is False
    assert d["triples"] == 2


def test_a_NEW_draft_is_ALL_ADDITION(index, qa):
    """Against nothing, every triple is new. The page says so in a sentence
    instead of listing them beside the text that already shows them."""
    _write(qa, GUID)

    d = index.detail(GUID)

    assert d["distributed"] is False
    assert len(d["added"]) == 2 and d["removed"] == []


def test_a_MODIFIED_draft_diffs_against_the_DISTRIBUTED_version(index, qa):
    _write(qa, GUID, "As distributed")
    qa.stage_all(); qa.commit("distributed")
    _write(qa, GUID, "Renamed since")

    d = index.detail(GUID)

    assert d["distributed"] is True
    assert d["added"] == ['work:a6671c83-4ebc-4c2d-84f2-8671d2c8e597 rdfs:label '
                          '"Renamed since"']
    assert d["removed"] == ['work:a6671c83-4ebc-4c2d-84f2-8671d2c8e597 rdfs:label '
                            '"As distributed"']


def test_the_diff_is_ISOMORPHIC_not_textual(index, qa):
    """Two writings of one graph differ in blank-node labels and statement order
    and are the same graph. A text diff would report a change that is not
    there, which on a page whose whole job is "what changed" is the worst
    possible lie."""
    path = _write(qa, GUID, "Same graph")
    qa.stage_all(); qa.commit("distributed")
    # Re-serialize: different statement order, different blank-node names.
    from rdflib import Graph

    g = Graph().parse(data=path.read_text(), format="turtle")
    path.write_text(g.serialize(format="xml"), encoding="utf-8")
    path.rename(path)  # same path, XML content under a .ttl name

    d = index.detail(GUID)

    # The parse is by extension, so this is deliberately a BROKEN file: the page
    # must still show it and say why it could not compare.
    assert d["text"].startswith("<?xml") and d["error"]


def test_a_REORDERED_record_reports_no_change(index, qa):
    from rdflib import Graph

    path = _write(qa, GUID, "Same graph")
    qa.stage_all(); qa.commit("distributed")
    g = Graph().parse(data=path.read_text(), format="turtle")
    path.write_text(g.serialize(format="turtle"), encoding="utf-8")

    d = index.detail(GUID)

    assert d["added"] == [] and d["removed"] == []


def test_a_draft_that_is_GONE_reports_nothing_rather_than_raising(index, qa):
    assert index.detail("no-such-guid") == {}


# -- blank nodes are paired by POSITION, not by graph hash --------------------
# `rdflib.compare.graph_diff` labels a blank node by canonicalising the whole
# graph, so one added `ops:field` re-labelled a profile's template node, its
# twelve field nodes and every triple touching them: 22 added, 18 removed, every
# line reading `[ ]`, for a one-field change (Rick, 2026-09-19).

PROFILE = """@prefix ops: <http://visualartsdna.org/operations/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix schema: <https://schema.org/> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix vad: <http://visualartsdna.org/model/> .
@prefix work: <http://visualartsdna.org/work/> .

work:{guid} a vad:ArtistProfile ;
    rdfs:label "A profile" ;
    vad:measurementSystem [ a skos:Concept ; schema:unitCode "{unit}" ;
        skos:note "centimeters" ] ;
    ops:template [ rdfs:label "Input Form Spec" ;
        ops:templateType vad:VirtualRealityArt ;
{fields}    ] .
"""

FIELD = ('        ops:field [ ops:property <{p}> ; ops:order {o} ; '
         "ops:required true ] ;\n")


def _profile(qa, guid=GUID, unit="CTM", fields=(("rdfs:label", 10),
                                                ("schema:image", 20),
                                                ("schema:height", 30))):
    body = "".join(FIELD.format(p=_expand(p), o=o) for p, o in fields)
    p = qa.root / Layout.default().dir("work_ttl") / f"{guid}.ttl"
    p.write_text(PROFILE.format(guid=guid, unit=unit, fields=body))
    return p


def _expand(curie):
    pre, _, local = curie.partition(":")
    return {"rdfs": "http://www.w3.org/2000/01/rdf-schema#",
            "schema": "https://schema.org/",
            "ops": "http://visualartsdna.org/operations/",
            "skos": "http://www.w3.org/2004/02/skos/core#"}[pre] + local


def test_ADDING_ONE_FIELD_shows_one_field(index, qa):
    """Not the whole template twice."""
    _profile(qa)
    qa.stage_all(); qa.commit("distributed")
    _profile(qa, fields=(("rdfs:label", 10), ("schema:image", 20),
                         ("schema:height", 30), ("schema:video", 40)))

    d = index.detail(GUID)

    assert d["removed"] == []
    assert len(d["added"]) == 4, d["added"]
    assert any("ops:field [field schema:video]" in x for x in d["added"])
    assert any("[field schema:video] ops:order" in x for x in d["added"])


def test_a_CHANGED_VALUE_inside_a_blank_node_is_one_line_each_way(index, qa):
    """The measurement system is the same measurement system; its unit changed."""
    _profile(qa, unit="CTM")
    qa.stage_all(); qa.commit("distributed")
    _profile(qa, unit="MTR")

    d = index.detail(GUID)

    assert d["removed"] == [
        '[measurementSystem skos:Concept] schema:unitCode "CTM"']
    assert d["added"] == [
        '[measurementSystem skos:Concept] schema:unitCode "MTR"']


def test_a_REORDERED_FIELD_is_the_same_field(index, qa):
    """Identity is the property it carries, not the position it sits in — or
    moving a field would read as one field removed and another added."""
    _profile(qa)
    qa.stage_all(); qa.commit("distributed")
    _profile(qa, fields=(("rdfs:label", 10), ("schema:image", 20),
                         ("schema:height", 99)))

    d = index.detail(GUID)

    assert d["removed"] == ['[field schema:height] ops:order "30"^^xsd:integer']
    assert d["added"] == ['[field schema:height] ops:order "99"^^xsd:integer']


def test_RESERIALIZING_a_blank_node_record_is_still_no_change(index, qa):
    """The isomorphism guarantee this replaces has to survive it: a file written
    out again has different blank-node labels and a different statement order,
    and is the same graph."""
    from rdflib import Graph

    path = _profile(qa)
    qa.stage_all(); qa.commit("distributed")
    g = Graph().parse(data=path.read_text(), format="turtle")
    path.write_text(g.serialize(format="xml"), encoding="utf-8")
    path.write_text(Graph().parse(data=g.serialize(format="xml"), format="xml")
                    .serialize(format="turtle"), encoding="utf-8")

    d = index.detail(GUID)

    assert d["added"] == [] and d["removed"] == []


def test_INDISTINGUISHABLE_SIBLINGS_do_not_report_a_change(index, qa):
    """Two blank nodes with identical content under one predicate can only be
    told apart by an index. It has to be stable, or a record would diff against
    itself."""
    body = ("work:x a <http://visualartsdna.org/model/Watercolor> ;\n"
            '    <https://schema.org/height> [ <https://schema.org/value> "12" ],\n'
            '        [ <https://schema.org/value> "12" ] .\n')
    path = qa.root / Layout.default().dir("work_ttl") / f"{GUID}.ttl"
    from rdflib import Graph

    text = "@prefix work: <http://visualartsdna.org/work/> .\n" + body
    path.write_text(text)
    qa.stage_all(); qa.commit("distributed")
    # Written out again, so the FILE differs and the GRAPH does not — otherwise
    # there is no draft to diff and the test proves nothing.
    path.write_text(Graph().parse(data=text, format="turtle")
                    .serialize(format="turtle"), encoding="utf-8")

    d = index.detail(GUID)

    assert d["added"] == [] and d["removed"] == []


# -- a discarded draft is gone from GIT too (2026-10-05) ---------------------
#
# Rick discarded one and the Drafts page went on listing it. `full.unlink()`
# removed the working-tree file and left the STAGED ADDITION in the index, so
# `git status` read `AD` — and the draft index is derived from git status.
# Opening the draft it still offered produced a FileNotFoundError over an empty
# husk that invited you to discard it again.
#
# A record is staged whenever it has been through a preview, because building a
# manifest stages the tree. So this is the ordinary case, not an edge one.


def test_discarding_a_STAGED_new_draft_leaves_git_CLEAN(index, qa):
    """The condition that made it come back: `git status` must not report the
    path at all afterwards."""
    _write(qa, GUID)
    qa.stage_all()
    assert any(GUID in p for p in qa.uncommitted_paths()), "staged to begin with"

    index.discard([GUID])

    assert not any(GUID in p for p in qa.uncommitted_paths())


def test_a_STAGED_draft_does_not_come_BACK_in_the_list(index, qa):
    """The symptom, asserted on the index rather than on git."""
    _write(qa, GUID)
    qa.stage_all()

    index.discard([GUID])

    assert index.list()[0] == []


def test_the_discard_REPORTS_what_git_forgot(index, qa):
    _write(qa, GUID)
    qa.stage_all()

    out = index.discard([GUID])

    assert out["forgotten"] == [f"{Layout.default().dir('work_ttl')}/{GUID}.ttl"]


def test_an_UNSTAGED_new_draft_still_discards(index, qa):
    """Never staged, so there is no index entry to remove and `git rm --cached`
    would fail on it. The path that worked before must keep working."""
    _write(qa, GUID)

    out = index.discard([GUID])

    assert out["discarded"] and out["forgotten"] == []
    assert index.list()[0] == []


def test_a_DISTRIBUTED_record_is_RESTORED_not_forgotten(index, qa):
    """Git must go on tracking a record that has a committed version — the
    discard puts it back, it does not remove it."""
    _write(qa, GUID, "Distributed")
    qa.stage_all(); qa.commit("distributed")
    _write(qa, GUID, "Changed since")
    qa.stage_all()

    out = index.discard([GUID])

    assert out["forgotten"] == []
    assert (qa.root / Layout.default().dir("work_ttl") / f"{GUID}.ttl").exists()
    assert index.list()[0] == []


def test_discarding_ONE_staged_draft_does_not_untrack_ANOTHER(index, qa):
    _write(qa, GUID)
    _write(qa, OTHER)
    qa.stage_all()

    index.discard([GUID])

    remaining = [d["guid"] for d in index.list()[0]]
    assert remaining == [OTHER]
