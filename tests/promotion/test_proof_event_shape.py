"""`config/shapes/proof_event.ttl` — and that it really refuses bad proofs.

A shape that passes proves nothing until it is shown to fail, which is the
lesson `test_shacl_armed.py` exists for: the SHACL gate was written, tested and
never actually run for four phases because `driver.py` passed `shapes=None`.
Every constraint here is asserted in both directions.
"""

import pathlib

import pytest
from rdflib import Graph, Literal, Namespace, RDF
from rdflib.namespace import XSD

from cwva_dashboard.promotion import gates

VAD = Namespace("http://visualartsdna.org/model/")
W = Namespace("http://visualartsdna.org/work/")
SHAPES = pathlib.Path(__file__).resolve().parents[2] / "config" / "shapes"

H = "0x" + "ab" * 32
PATH = "L:" + "cd" * 32
WHEN = Literal("2026-01-01T00:00:00-05:00", datatype=XSD.dateTime)


@pytest.fixture(scope="module")
def shapes():
    g = Graph()
    for f in sorted(SHAPES.glob("*.ttl")):
        g.parse(f, format="turtle")
    return g


def _proof(g, name, **props):
    s = W[name]
    g.add((s, RDF.type, VAD.ProofEvent))
    for p, v in props.items():
        g.add((s, VAD[p], v if isinstance(v, Literal) else Literal(v)))
    return s


def _complete(g, name, **over):
    props = dict(dataHash=H, transaction=H, rootHash=H, timestamp=WHEN, merklePath=PATH)
    props.update(over)
    return _proof(g, name, **props)


def _ok(shapes, g):
    return gates.shacl_gate(g, shapes).ok


def test_the_shape_file_is_actually_loaded(shapes):
    """Scoped the way `test_shacl_armed` is: an empty shapes graph conforms to
    everything, so the file being present is itself an assertion."""
    assert (None, None, VAD.ProofEvent) in shapes, "proof_event.ttl is not in config/shapes"


def test_a_complete_proof_conforms(shapes):
    g = Graph(); _complete(g, "good")
    assert _ok(shapes, g)


def test_an_INCIPIENT_proof_conforms(shapes):
    """No transaction means the anchor does not exist yet. That is a legitimate
    state, not an incomplete record, and the shape must not punish it."""
    g = Graph(); _proof(g, "incipient", dataHash=H)
    assert _ok(shapes, g)


@pytest.mark.parametrize("missing", ["merklePath", "rootHash", "timestamp"])
def test_a_transaction_without_its_whole_anchor_FAILS(shapes, missing):
    """The middle state UnmooredSwing.jpg occupied: a transaction borrowed from
    a sibling, for a proof that had never been created."""
    g = Graph()
    props = dict(dataHash=H, transaction=H, rootHash=H, timestamp=WHEN, merklePath=PATH)
    del props[missing]
    _proof(g, "partial", **props)
    assert not _ok(shapes, g)


@pytest.mark.parametrize("bad", [
    "X:" + "cd" * 32,                      # not L or R
    "L:" + "CD" * 32,                      # uppercase hex
    "L:" + "cd" * 31,                      # too short
    "L:" + "cd" * 32 + "  R:" + "cd" * 32,  # two spaces
    "L" + "cd" * 32,                       # no colon
    "",
])
def test_a_malformed_merklePath_FAILS(shapes, bad):
    g = Graph(); _complete(g, "badpath", merklePath=Literal(bad))
    assert not _ok(shapes, g)


def test_a_wellformed_multilevel_path_conforms(shapes):
    g = Graph(); _complete(g, "multi", merklePath=Literal(f"{PATH} R:{'ef' * 32}"))
    assert _ok(shapes, g)


def test_proofs_SHARING_a_transaction_must_agree(shapes):
    """One anchoring event produced them, so they agree or one is wrong. This
    invariant found two transcription errors in records that were each
    individually plausible."""
    g = Graph()
    _complete(g, "a")
    _complete(g, "b", timestamp=Literal("2026-01-02T00:00:00-05:00", datatype=XSD.dateTime))
    assert not _ok(shapes, g)

    g2 = Graph()
    _complete(g2, "a")
    _complete(g2, "b", rootHash="0x" + "99" * 32)
    assert not _ok(shapes, g2)


def test_proofs_in_DIFFERENT_batches_may_differ(shapes):
    g = Graph()
    _complete(g, "a")
    _complete(g, "b", transaction="0x" + "11" * 32,
              timestamp=Literal("2026-02-02T00:00:00-05:00", datatype=XSD.dateTime))
    assert _ok(shapes, g)


def test_dataHash_is_required_even_when_incipient(shapes):
    """It is the join key the whole workflow turns on."""
    g = Graph(); _proof(g, "nohash")
    assert not _ok(shapes, g)


@pytest.mark.parametrize("prop", ["dataHash", "rootHash", "transaction"])
def test_a_hash_without_its_0x_prefix_FAILS(shapes, prop):
    g = Graph(); _complete(g, "nopfx", **{prop: "ab" * 32})
    assert not _ok(shapes, g)


def test_a_timestamp_that_is_not_a_dateTime_FAILS(shapes):
    g = Graph(); _complete(g, "badts", timestamp=Literal("2026-01-01", datatype=XSD.date))
    assert not _ok(shapes, g)


def test_SHACL_cannot_tell_whether_the_path_is_TRUE(shapes):
    """Recorded so a green gate is not misread. There is no sha256 in SPARQL,
    so a well-formed path that folds nowhere near the root still conforms.
    Checking that is gate 2 in `cwva_dashboard.proof.validate`, at the moment
    the record is written."""
    g = Graph(); _complete(g, "liar", merklePath=Literal("L:" + "00" * 32))
    assert _ok(shapes, g), "the shape checks form, never correctness"
