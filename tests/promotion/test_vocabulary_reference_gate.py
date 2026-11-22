"""Vocabulary-reference gate: vad:hasPaper resolves to a declared concept.

The graph-fact complement of the asset gate's filesystem fact. Two properties
pinned here:

1. **The reference graph must be loaded.** The vocabulary lives in the QA tree,
   NOT in a work-entry's manifest, so checking the manifest alone reports every
   hasPaper as dangling. The load is the whole point — a test asserts that
   omitting the vocab dir turns a valid reference into a false positive, and
   supplying it clears it. (This is why it is a gate that loads a reference
   graph, not a bare SPARQL assertion over the manifest.)
2. **A typo dangles; a declared concept resolves.** `the:StrathmoreColdPres`
   (missing 's') is caught where valid TTL + the parse gate would pass it — the
   exact guard the Groovy dropdown used to provide.
"""

from __future__ import annotations

import shutil

import pytest
from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import RDF, SKOS

from cwva_dashboard.promotion.gates import vocabulary_reference_gate
from cwva_dashboard.promotion.qa_git import QAGit
from cwva_dashboard.promotion.transports import FilesTransport
from cwva_dashboard.sandbox.fileops import FileOps
from cwva_dashboard.sandbox.paths import Sandbox
from cwva_dashboard.workflows.promote import run_promotion

VAD = Namespace("http://visualartsdna.org/model/")
THE = Namespace("http://visualartsdna.org/thesaurus/")
WORK = Namespace("http://visualartsdna.org/work/")
VOCAB_DIR = "content/ttl/vocab"


def _write_vocab(root, *concept_localnames):
    d = root / VOCAB_DIR
    d.mkdir(parents=True, exist_ok=True)
    g = Graph()
    for ln in concept_localnames:
        # Papers are declared as vad:WatercolorPaper (Q5: the gate checks that
        # specific class, matching the entry picker, not the skos:Concept super).
        g.add((THE[ln], RDF.type, VAD.WatercolorPaper))
        g.add((THE[ln], RDF.type, SKOS.Concept))  # they are both in real data
    g.serialize(str(d / "papers.ttl"), format="turtle")


def _manifest_graph(paper_localname):
    g = Graph()
    g.add((WORK["w1"], RDF.type, VAD.Watercolor))
    g.add((WORK["w1"], VAD.hasPaper, THE[paper_localname]))
    return g


# -- the reference graph is load-bearing -------------------------------------


def test_valid_reference_dangles_without_vocab_but_resolves_with_it(tmp_path):
    """The property that makes this a reference-graph gate, not a manifest
    assertion: the same valid reference is a false positive without the vocab
    loaded and clean with it."""
    data = _manifest_graph("StrathmoreColdPress")

    # vocab dir empty / not written -> the concept is nowhere -> false dangling
    (tmp_path / VOCAB_DIR).mkdir(parents=True)
    r_without = vocabulary_reference_gate(data, tmp_path, [VOCAB_DIR])
    assert not r_without.ok and len(r_without.details["dangling"]) == 1

    # write the concept into the vocab -> resolves
    _write_vocab(tmp_path, "StrathmoreColdPress")
    r_with = vocabulary_reference_gate(data, tmp_path, [VOCAB_DIR])
    assert r_with.ok and r_with.details["resolved"] == 1


def test_concept_that_is_not_a_paper_is_rejected(tmp_path):
    """Q5: the gate checks vad:WatercolorPaper specifically, not skos:Concept.
    A concept that exists but is not a paper must not satisfy hasPaper."""
    d = tmp_path / VOCAB_DIR
    d.mkdir(parents=True)
    g = Graph()
    g.add((THE["SomeColor"], RDF.type, SKOS.Concept))  # a concept, but not a paper
    g.serialize(str(d / "colors.ttl"), format="turtle")
    data = _manifest_graph("SomeColor")

    r = vocabulary_reference_gate(data, tmp_path, [VOCAB_DIR])
    assert not r.ok
    assert "not a WatercolorPaper" in r.details["dangling"][0]


def test_typo_dangles_where_the_parse_gate_would_pass(tmp_path):
    _write_vocab(tmp_path, "StrathmoreColdPress")
    data = _manifest_graph("StrathmoreColdPres")  # missing trailing 's'

    r = vocabulary_reference_gate(data, tmp_path, [VOCAB_DIR])
    assert not r.ok
    assert "StrathmoreColdPres" in r.details["dangling"][0]
    assert "in w1)" in r.details["dangling"][0]


def test_topic_requires_both_concept_and_topicscheme(tmp_path):
    """the:topic (new_entity media) matches the entity picker's two-clause query:
    the object must be a skos:Concept AND skos:inScheme the:TopicScheme."""
    d = tmp_path / VOCAB_DIR
    d.mkdir(parents=True)
    g = Graph()
    # a proper topic
    g.add((THE["Watercolor"], RDF.type, SKOS.Concept))
    g.add((THE["Watercolor"], SKOS.inScheme, THE.TopicScheme))
    # a concept that is NOT in the topic scheme
    g.add((THE["Loose"], RDF.type, SKOS.Concept))
    g.serialize(str(d / "topics.ttl"), format="turtle")

    def _entity_with_topic(topic_ln):
        g2 = Graph()
        g2.add((WORK["e1"], RDF.type, THE.Article))
        g2.add((WORK["e1"], THE.topic, THE[topic_ln]))
        return g2

    assert vocabulary_reference_gate(_entity_with_topic("Watercolor"), tmp_path, [VOCAB_DIR]).ok
    r = vocabulary_reference_gate(_entity_with_topic("Loose"), tmp_path, [VOCAB_DIR])
    assert not r.ok
    assert "missing inScheme TopicScheme" in r.details["dangling"][0]


def test_no_vocabulary_reference_is_a_clean_pass_without_loading(tmp_path):
    g = Graph()
    g.add((WORK["w1"], RDF.type, VAD.Watercolor))  # no hasPaper at all
    r = vocabulary_reference_gate(g, tmp_path, [VOCAB_DIR])
    assert r.ok and r.summary == "no vocabulary references"


# -- vad:background: a CONTENT-sourced referent (2026-09) ---------------------
#
# Previously skipped by this gate as an undefined "work: cross-reference". It
# was deferred for being undefined, not for being expensive: a background is an
# entity record (`a the:Image` with `the:topic the:Background`), which makes it
# the same two-condition test as any other referent — it just lives in the
# record store rather than the thesaurus.

DATA_DIR = "content/ttl/data"


def _write_background(root, guid="bg1", *, topic=THE.Background, typ=THE.Image):
    d = root / DATA_DIR
    d.mkdir(parents=True, exist_ok=True)
    g = Graph()
    g.add((WORK[guid], RDF.type, typ))
    g.add((WORK[guid], THE.topic, topic))
    g.serialize(str(d / f"{guid}.ttl"), format="turtle")
    return WORK[guid]


def _digital_with_background(subject=WORK["bg1"]):
    g = Graph()
    g.add((WORK["w1"], RDF.type, VAD.BlenderComposition))
    g.add((WORK["w1"], VAD.background, subject))
    return g


def test_a_declared_background_resolves(tmp_path):
    _write_background(tmp_path)
    r = vocabulary_reference_gate(
        _digital_with_background(), tmp_path, [VOCAB_DIR], content_dirs=[DATA_DIR]
    )
    assert r.ok and r.details["resolved"] == 1


def test_a_background_that_is_not_a_background_dangles(tmp_path):
    """Right type, wrong topic: an image entity that is not a background. This
    is what makes the picker's query meaningful — anything else and the field
    might as well be free text."""
    _write_background(tmp_path, topic=THE.Portrait)
    r = vocabulary_reference_gate(
        _digital_with_background(), tmp_path, [VOCAB_DIR], content_dirs=[DATA_DIR]
    )
    assert not r.ok
    assert "missing topic Background" in r.details["dangling"][0]


def test_a_background_pointing_at_nothing_dangles(tmp_path):
    (tmp_path / DATA_DIR).mkdir(parents=True)
    r = vocabulary_reference_gate(
        _digital_with_background(WORK["nosuch"]), tmp_path, [VOCAB_DIR],
        content_dirs=[DATA_DIR],
    )
    assert not r.ok


def test_an_unarmed_content_dir_fails_LOUDLY(tmp_path):
    """Arm the gates in fixtures. Without `content_dirs` the referent cannot be
    found, so a valid background reports as dangling. That is the right way for
    an unarmed gate to fail — a gate that refuses everything gets fixed, one
    that silently passes does not."""
    _write_background(tmp_path)
    r = vocabulary_reference_gate(_digital_with_background(), tmp_path, [VOCAB_DIR])
    assert not r.ok, "an unarmed content gate must fail loudly, not pass"


def test_the_record_store_is_not_loaded_for_a_concept_only_manifest(tmp_path, monkeypatch):
    """Lazy per source: a manifest referencing only papers must not pay to parse
    hundreds of record files."""
    _write_vocab(tmp_path, "StrathmoreColdPress")
    _write_background(tmp_path)
    seen = []
    real = Graph.parse

    def _spy(self, source=None, **kw):
        seen.append(str(source))
        return real(self, source, **kw)

    monkeypatch.setattr(Graph, "parse", _spy)
    r = vocabulary_reference_gate(
        _manifest_graph("StrathmoreColdPress"), tmp_path, [VOCAB_DIR],
        content_dirs=[DATA_DIR],
    )
    assert r.ok
    assert not any(DATA_DIR in s for s in seen), seen


def test_picker_and_gate_read_the_SAME_table(tmp_path):
    """The two halves of "what the form offers is what the system enforces".
    They were once two hand-kept maps agreeing only by comment; a drifting pair
    of enumerations is what caused the asset-collision bug the same week."""
    from cwva_dashboard import referents
    from cwva_dashboard.promotion import gates as gates_mod
    from cwva_dashboard.ux import affordance

    assert gates_mod._VOCABULARY_REQUIREMENTS is referents.REQUIREMENTS
    assert affordance.REFERENTS is referents.REFERENTS


def test_a_malformed_vocab_file_does_not_crash_the_check(tmp_path):
    """A broken vocab TTL is the parse gate's concern; this gate must skip it,
    not raise (it would still report the reference dangling, correctly, since
    the concept never loaded)."""
    _write_vocab(tmp_path, "GoodConcept")
    (tmp_path / VOCAB_DIR / "broken.ttl").write_text("this is not turtle {{{")
    data = _manifest_graph("GoodConcept")
    r = vocabulary_reference_gate(data, tmp_path, [VOCAB_DIR])
    assert r.ok and r.details["resolved"] == 1


# -- armed in run_promotion (mutation discipline) ----------------------------


def _entry(root, paper):
    qa = QAGit.init(root)
    ops = FileOps(Sandbox.open(root))
    ops.write_text(
        "content/ttl/data/w1.ttl",
        f"@prefix vad: <{VAD}> .\n@prefix the: <{THE}> .\n"
        f"<{WORK}w1> a vad:Watercolor ; vad:hasPaper the:{paper} .\n",
        make_parents=True,
    )
    return qa, ops


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_dangling_paper_blocks_promotion_when_armed(tmp_path):
    root = tmp_path / "qa"; root.mkdir()
    qa, _ = _entry(root, "StrathmoreColdPres")  # typo
    _write_vocab(root, "StrathmoreColdPress")
    sot = FilesTransport(tmp_path / "sot")

    res = run_promotion(
        qa, sot, workflow="entry", base_commit=_base(qa),
        description="typo paper", expected_stamp=sot.current_stamp(),
        vocab_dirs=[VOCAB_DIR],
    )
    assert not res.ok and res.status == "gates_failed"
    vg = [g for g in res.unit.gates if g.name == "vocabulary_reference"]
    assert vg and not vg[0].ok
    assert not (sot.target / "content/ttl/data/w1.ttl").exists()


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_not_armed_lets_the_dangling_paper_through(tmp_path):
    root = tmp_path / "qa"; root.mkdir()
    qa, _ = _entry(root, "StrathmoreColdPres")
    _write_vocab(root, "StrathmoreColdPress")
    sot = FilesTransport(tmp_path / "sot")

    res = run_promotion(  # vocab_dirs omitted -> gate not armed
        qa, sot, workflow="entry", base_commit=_base(qa),
        description="typo paper", expected_stamp=sot.current_stamp(),
    )
    assert res.ok and res.status == "converged"
    assert [g for g in res.unit.gates if g.name == "vocabulary_reference"] == []


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_declared_paper_promotes_when_armed(tmp_path):
    root = tmp_path / "qa"; root.mkdir()
    qa, _ = _entry(root, "StrathmoreColdPress")
    _write_vocab(root, "StrathmoreColdPress")
    sot = FilesTransport(tmp_path / "sot")

    res = run_promotion(
        qa, sot, workflow="entry", base_commit=_base(qa),
        description="valid paper", expected_stamp=sot.current_stamp(),
        vocab_dirs=[VOCAB_DIR],
    )
    assert res.ok and res.status == "converged"
    vg = [g for g in res.unit.gates if g.name == "vocabulary_reference"]
    assert vg and vg[0].ok and vg[0].details["resolved"] == 1


def _base(qa):
    # the pre-work commit: the vocab write happens after init, so HEAD already
    # includes it; the manifest is diffed from the initial (pre-vocab) commit.
    return qa._run("rev-list", "--max-parents=0", "HEAD").strip()
