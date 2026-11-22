"""Context is not stored, so it has to be recoverable — Rick's condition on
that decision (2026-09-29). These tests are the guarantee.
"""

from __future__ import annotations

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDFS

from cwva_dashboard.dts.grounding import THE, attach_grounding, ground
from cwva_dashboard.dts.recall import recover_context, source_document

DOCS_BASE = "http://visualartsdna.org/documents/"
DOCS_DIR = "content/documents"
ENTITY = URIRef("http://visualartsdna.org/work/e1")
CONCEPT = URIRef("http://visualartsdna.org/thesaurus/SilhouetteMerging")
DOC = ("# Criticism\n\nThe figures read as one mass from several angles; the "
       "critic notes merged silhouettes and faint tension cables throughout "
       "the orbit.\n")


def _store():
    g = Graph()
    g.add((ENTITY, THE.mdDocument, URIRef(DOCS_BASE + "Claude-Criticism.md")))
    return g


def _reader(files):
    def read(path):
        return files[path]
    return read


def _recover(g, node, files=None):
    if files is None:
        files = {f"{DOCS_DIR}/Claude-Criticism.md": DOC}
    return recover_context(g, node, _reader(files),
                           docs_base=DOCS_BASE, docs_dir=DOCS_DIR)


def test_the_document_path_comes_from_the_RECORD_and_the_layout():
    """Not from a filename convention: where a document lands is the active
    target's business (CE_DESIGN §3.6)."""
    assert source_document(_store(), ENTITY, docs_base=DOCS_BASE,
                           docs_dir=DOCS_DIR) == f"{DOCS_DIR}/Claude-Criticism.md"


def test_a_grounding_on_a_CONCEPT_recovers_through_srcEntity():
    g = _store()
    node = attach_grounding(g, CONCEPT, ground("merged silhouettes", DOC,
                                               src_entity=ENTITY))

    out = _recover(g, node)

    assert out.found
    assert "merged silhouettes" in out.context
    assert out.entity == str(ENTITY) and out.concept == str(CONCEPT)


def test_a_grounding_on_an_ENTITY_recovers_in_ONE_HOP():
    """The entity it hangs from IS the source."""
    g = _store()
    node = attach_grounding(g, ENTITY, ground("faint tension cables", DOC,
                                              concept_uri=CONCEPT))

    out = _recover(g, node)

    assert out.found and "faint tension cables" in out.context
    assert out.concept == str(CONCEPT)


def test_the_context_carries_the_SURROUNDING_sentences():
    g = _store()
    node = attach_grounding(g, CONCEPT, ground("merged silhouettes", DOC,
                                               src_entity=ENTITY))

    assert "the critic notes" in _recover(g, node).context.lower()


def test_a_CHANGED_document_is_reported_not_guessed_at():
    """A verified grounding whose phrase is now absent means the document
    moved underneath it, and a window of arbitrary text would look like
    evidence."""
    g = _store()
    node = attach_grounding(g, CONCEPT, ground("merged silhouettes", DOC,
                                               src_entity=ENTITY))

    out = _recover(g, node, files={f"{DOCS_DIR}/Claude-Criticism.md": "# Rewritten\n"})

    assert not out.found and not out.context
    assert "not in the document as it now stands" in out.reason
    assert "ground verified" in out.reason, "and what it used to claim"


def test_a_MISSING_document_says_which_one():
    g = _store()
    node = attach_grounding(g, CONCEPT, ground("merged silhouettes", DOC,
                                               src_entity=ENTITY))

    out = _recover(g, node, files={})

    assert not out.found
    assert out.document == f"{DOCS_DIR}/Claude-Criticism.md"
    assert "could not be read" in out.reason


def test_an_entity_with_NO_markdown_is_reported():
    g = Graph()
    node = attach_grounding(g, CONCEPT, ground("merged silhouettes", DOC,
                                               src_entity=ENTITY))

    out = _recover(g, node)

    assert not out.found and "cites no markdown" in out.reason


def test_recovery_survives_a_ROUND_TRIP_through_turtle():
    """The real path: the node is written to a file, distributed, and read
    back by something that never saw the object that composed it."""
    g = _store()
    attach_grounding(g, CONCEPT, ground("merged silhouettes", DOC, src_entity=ENTITY))
    reloaded = Graph().parse(data=g.serialize(format="turtle"), format="turtle")
    node = reloaded.value(CONCEPT, THE.grounding)

    assert _recover(reloaded, node).found
