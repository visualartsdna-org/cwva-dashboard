"""`dts.ground_entity`: the tagging run's evidence, under the status node.

Rick, 2026-10-02, looking at a criticism page after the production DTS: "the
criticism page in the browser contains too many status properties and values.
The grounding is meaningless here. Can the grounding be moved under status?"
Twelve `ground verified` nodes hung off the subject put twelve rows of nothing
at the top of the page, above the concepts they are evidence for.

It is also where they belong. A grounding on the ENTITY is this run's account
of why it tagged what it tagged, and `ops:status` is the record of what the run
did. A grounding on a CONCEPT is a different claim and stays where it is —
that one is about the concept, which is why the vocabulary stayed in `the:`.

The tool had no tests at all, which is why moving it broke nothing.
"""

from __future__ import annotations

import pytest
from rdflib import BNode, Graph, URIRef

from cwva_dashboard.dts.state import OPS, status_node, write_stamp
from cwva_dashboard.sandbox.fileops import FileOps
from cwva_dashboard.sandbox.paths import Sandbox
from cwva_dashboard.tools.base import ToolError
from cwva_dashboard.tools.dts_tools import _ground_entity

THE = "http://visualartsdna.org/thesaurus/"
W = "http://visualartsdna.org/work/"
SUBJECT = W + "e1"
PATH = "ttl/data/e1.ttl"

ENTITY = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix the: <http://visualartsdna.org/thesaurus/> .
@prefix work: <http://visualartsdna.org/work/> .

work:e1 a the:AI ; rdfs:label "A criticism" ;
    skos:inScheme the:entities ;
    the:mdDocument <http://visualartsdna.org/documents/Doc.md> .
"""

GROUNDINGS = [
    {"concept": THE + "Prestress", "phrase": "the figures appear prestressed",
     "verified": True},
    {"concept": THE + "Triad", "phrase": "three figures", "verified": True},
]


def _ops(tmp_path, *, stamps=("derived", "derivationCurated", "tagged")):
    fileops = FileOps(Sandbox.open(tmp_path / "stage", create=True))
    g = Graph().parse(data=ENTITY, format="turtle")
    for stage in stamps:
        write_stamp(g, URIRef(SUBJECT), stage,
                    by="http://visualartsdna.org/operations/claude-opus-5-5")
    fileops.write_text(PATH, g.serialize(format="turtle"), make_parents=True)
    return fileops


def _graph(fileops):
    return Graph().parse(data=fileops.read_text(PATH), format="turtle")


# -- where it lands ----------------------------------------------------------


def test_the_grounding_hangs_off_the_STATUS_NODE(tmp_path):
    ops = _ops(tmp_path)

    _ground_entity(ops, path=PATH, subject=SUBJECT, groundings=GROUNDINGS)
    g = _graph(ops)

    assert (status_node(g, URIRef(SUBJECT)), URIRef(THE + "grounding"), None) in g


def test_it_does_NOT_hang_off_the_ENTITY(tmp_path):
    """The whole point: the criticism page lists the subject's own properties,
    so this is what took twelve rows."""
    ops = _ops(tmp_path)

    _ground_entity(ops, path=PATH, subject=SUBJECT, groundings=GROUNDINGS)

    assert (URIRef(SUBJECT), URIRef(THE + "grounding"), None) not in _graph(ops)


def test_every_grounding_keeps_its_CONCEPT_and_PHRASE(tmp_path):
    """Moved, not flattened. The evidence is the point of the node."""
    ops = _ops(tmp_path)

    _ground_entity(ops, path=PATH, subject=SUBJECT, groundings=GROUNDINGS)
    g = _graph(ops)
    node = status_node(g, URIRef(SUBJECT))
    found = {}
    for child in g.objects(node, URIRef(THE + "grounding")):
        found[str(g.value(child, URIRef(THE + "concept")))] = str(
            g.value(child, URIRef(THE + "phrase")))

    assert found == {d["concept"]: d["phrase"] for d in GROUNDINGS}


def test_the_STAMPS_are_untouched(tmp_path):
    """It writes into the status node; it must not disturb what is there."""
    from cwva_dashboard.dts.state import read_stamps

    ops = _ops(tmp_path)

    _ground_entity(ops, path=PATH, subject=SUBJECT, groundings=GROUNDINGS)

    assert set(read_stamps(_graph(ops), URIRef(SUBJECT))) == {
        "derived", "derivationCurated", "tagged"}


# -- replacing, and the records written before the move ----------------------


def test_running_TWICE_leaves_ONE_set(tmp_path):
    """"A second set of grounding nodes beside the first would be two answers
    to why this was tagged"."""
    ops = _ops(tmp_path)

    _ground_entity(ops, path=PATH, subject=SUBJECT, groundings=GROUNDINGS)
    _ground_entity(ops, path=PATH, subject=SUBJECT, groundings=GROUNDINGS)
    g = _graph(ops)

    assert len(list(g.objects(status_node(g, URIRef(SUBJECT)),
                              URIRef(THE + "grounding")))) == len(GROUNDINGS)


def test_a_LEGACY_set_on_the_entity_is_swept(tmp_path):
    """A record written before the move has them on the subject. Re-curating
    it must not leave a set in each place, which would be the same two answers
    with a harder-to-see cause."""
    ops = _ops(tmp_path)
    g = _graph(ops)
    old = BNode()
    g.add((URIRef(SUBJECT), URIRef(THE + "grounding"), old))
    g.add((old, URIRef(THE + "phrase"), URIRef(THE + "x")))
    ops.write_text(PATH, g.serialize(format="turtle"))

    _ground_entity(ops, path=PATH, subject=SUBJECT, groundings=GROUNDINGS)
    g = _graph(ops)

    assert (URIRef(SUBJECT), URIRef(THE + "grounding"), None) not in g
    assert len(list(g.objects(status_node(g, URIRef(SUBJECT)),
                              URIRef(THE + "grounding")))) == len(GROUNDINGS)


def test_an_EMPTY_grounding_list_clears_without_adding(tmp_path):
    ops = _ops(tmp_path)
    _ground_entity(ops, path=PATH, subject=SUBJECT, groundings=GROUNDINGS)

    _ground_entity(ops, path=PATH, subject=SUBJECT, groundings=[])
    g = _graph(ops)

    assert (None, URIRef(THE + "grounding"), None) not in g


# -- the invariant -----------------------------------------------------------


def test_an_entity_with_NO_status_node_is_REFUSED(tmp_path):
    """There is no run for the grounding to belong to. Tagging stamps the
    status node before curation writes grounding, so this can only mean the
    stages ran out of order — and inventing a status node to hold it would
    assert that a run happened."""
    ops = _ops(tmp_path, stamps=())

    with pytest.raises(ToolError) as exc:
        _ground_entity(ops, path=PATH, subject=SUBJECT, groundings=GROUNDINGS)

    assert "no_status" in str(exc.value.code if hasattr(exc.value, "code")
                              else exc.value)


def test_nothing_is_written_when_it_refuses(tmp_path):
    ops = _ops(tmp_path, stamps=())
    before = ops.read_text(PATH)

    with pytest.raises(ToolError):
        _ground_entity(ops, path=PATH, subject=SUBJECT, groundings=GROUNDINGS)

    assert ops.read_text(PATH) == before


# -- and the consequence for reset -------------------------------------------


def test_CLEAR_STATUS_now_takes_the_groundings_with_it(tmp_path):
    """It falls out of the move: a reset has one less thing to remember, and
    the thing it used to have to remember was in a different module."""
    from cwva_dashboard.dts.state import clear_status

    ops = _ops(tmp_path)
    _ground_entity(ops, path=PATH, subject=SUBJECT, groundings=GROUNDINGS)
    g = _graph(ops)

    clear_status(g, URIRef(SUBJECT))

    assert (None, URIRef(THE + "grounding"), None) not in g
    assert (None, URIRef(THE + "phrase"), None) not in g


# -- a DTS record stays a ONE-SUBJECT file ----------------------------------
#
# Rick, 2026-10-02: "There are 93 drafts in QA. I don't see either of the Three
# Graces Criticism entities." They were there, as `<guid>.ttl (4 subjects)`
# with no link back in — because DTS inlined an agent declaration per agent it
# cited, and a statement about `ops:user` makes `ops:user` a named subject
# wherever in the file it is written. Edit Record would not open them either:
# the picker and the editor both require one named subject.


def _named(g):
    return {s for s in g.subjects() if isinstance(s, URIRef)}


def test_a_STAMPED_record_has_one_named_subject(tmp_path):
    ops = _ops(tmp_path)

    assert _named(_graph(ops)) == {URIRef(SUBJECT)}


def test_it_stays_one_subject_through_GROUNDING(tmp_path):
    ops = _ops(tmp_path)

    _ground_entity(ops, path=PATH, subject=SUBJECT, groundings=GROUNDINGS)

    assert _named(_graph(ops)) == {URIRef(SUBJECT)}


def test_the_record_DECLARES_nothing_about_the_operations_vocabulary(tmp_path):
    """It cites `ops:claude-opus-5-5`; `operations.ttl` says what that is — the
    same way a record cites `the:Prestress` without inlining its definition.
    The inline copy also typed `ops:user` as a `prov:SoftwareAgent`, which the
    ontology contradicts with `prov:Agent, prov:Person`."""
    ops = _ops(tmp_path)
    g = _graph(ops)
    OPS_NS = "http://visualartsdna.org/operations/"

    assert not [s for s in g.subjects() if str(s).startswith(OPS_NS)]


def test_the_ATTRIBUTION_itself_survives(tmp_path):
    """Dropping the declaration must not drop the provenance — the reference is
    the point of the structure."""
    from rdflib.namespace import Namespace

    PROV = Namespace("http://www.w3.org/ns/prov#")
    ops = _ops(tmp_path)
    g = _graph(ops)

    attributed = {str(o) for o in g.objects(None, PROV.wasAttributedTo)}
    assert attributed, "the stamps still say who did the work"
    assert all(a.startswith("http://visualartsdna.org/operations/")
               for a in attributed)
