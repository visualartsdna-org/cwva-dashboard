"""The agent-IRI migration: `…/agent/X` becomes `ops:X`.

An operator script, so what is tested here is the part that decides — the
mapping, the idempotency, and the rule that keeps a re-serialization from
handing the review stop a diff with no change in it.
"""

from __future__ import annotations

import sys
from pathlib import Path

from rdflib import Graph, URIRef
from rdflib.compare import isomorphic

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from migrate_agent_iris import (  # noqa: E402
    AGENCY_SECTION,
    add_agency,
    rewrite,
    target_iri,
)

OLD = "http://visualartsdna.org/agent/"
OPS = "http://visualartsdna.org/operations/"


# -- the mapping -------------------------------------------------------------


def test_an_agent_keeps_its_local_name():
    assert str(target_iri(OLD + "claude-sonnet-5")) == OPS + "claude-sonnet-5"
    assert str(target_iri(OLD + "updateWorkOnSite")) == OPS + "updateWorkOnSite"


def test_the_CURATOR_is_renamed_to_the_USER():
    """The one rename the new vocabulary implies: the user is an AGENT and
    `ops:Curator` is the role they act in. Attributing to the role would make
    "what did the curator decide" unanswerable without also knowing which
    model was in the chair."""
    assert str(target_iri(OLD + "curator")) == OPS + "user"


# -- the rewrite -------------------------------------------------------------


RECORD = f"""@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix the: <http://visualartsdna.org/thesaurus/> .
@prefix work: <http://visualartsdna.org/work/> .

work:e1 the:status [ prov:wasAttributedTo <{OLD}curator> ] ;
        the:summary "unchanged" .
<{OLD}claude-sonnet-5> a prov:SoftwareAgent ; rdfs:label "a model" .
work:e1 prov:wasAttributedTo <{OLD}claude-sonnet-5> .
"""


def test_an_agent_in_OBJECT_position_is_rewritten():
    g = Graph().parse(data=RECORD, format="turtle")

    rewrite(g)

    assert (None, None, URIRef(OPS + "user")) in g
    assert (None, None, URIRef(OLD + "curator")) not in g


def test_an_agent_in_SUBJECT_position_is_rewritten():
    """The inline declaration a record carries about its own agent — which is
    what keeps the record self-describing when the ontology lags."""
    g = Graph().parse(data=RECORD, format="turtle")

    rewrite(g)

    assert (URIRef(OPS + "claude-sonnet-5"), None, None) in g
    assert (URIRef(OLD + "claude-sonnet-5"), None, None) not in g


def test_everything_ELSE_is_left_alone():
    g = Graph().parse(data=RECORD, format="turtle")
    before = len(g)

    rewrite(g)

    assert len(g) == before, "a rewrite, not an edit"
    assert any(str(o) == "unchanged" for o in g.objects())


def test_a_record_with_no_agent_is_UNTOUCHED():
    plain = Graph().parse(
        data='<http://x/a> <http://x/p> "v" .', format="turtle")
    original = Graph().parse(
        data='<http://x/a> <http://x/p> "v" .', format="turtle")

    assert rewrite(plain) == 0
    assert isomorphic(plain, original)


def test_rewriting_TWICE_changes_nothing_the_second_time():
    g = Graph().parse(data=RECORD, format="turtle")
    rewrite(g)
    snapshot = Graph().parse(data=g.serialize(format="turtle"), format="turtle")

    assert rewrite(g) == 0
    assert isomorphic(g, snapshot)


# -- the ontology section ----------------------------------------------------


ONTOLOGY = """@prefix ops:    <http://visualartsdna.org/operations/> .
@prefix owl:    <http://www.w3.org/2002/07/owl#> .
@prefix rdf:    <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:    <http://www.w3.org/2001/XMLSchema#> .
@prefix dct:    <http://purl.org/dc/terms/> .

ops:Template a owl:Class ; rdfs:label "Template" .
"""


def test_the_agency_section_PARSES_onto_a_real_ontology():
    """The section is a paste in a Python string; the one thing that must be
    true of it is that the result is Turtle."""
    g = Graph().parse(data=add_agency(ONTOLOGY), format="turtle")

    assert (URIRef(OPS + "user"), None, None) in g
    assert (URIRef(OPS + "claude-sonnet-5"), None, None) in g


def test_it_declares_the_ROLES_and_the_property_that_carries_them():
    g = Graph().parse(data=add_agency(ONTOLOGY), format="turtle")

    for role in ("Curator", "CuratorAgent", "Scraper"):
        assert (URIRef(OPS + role), None, URIRef(OPS + "Role")) in g
    assert (URIRef(OPS + "hasRole"), None, None) in g


def test_a_role_is_not_an_AGENT():
    """`prov:wasAttributedTo` points at an agent; `ops:hasRole` says the
    capacity. The two must not be the same node."""
    from rdflib.namespace import RDF

    g = Graph().parse(data=add_agency(ONTOLOGY), format="turtle")
    PROV = "http://www.w3.org/ns/prov#"

    assert (URIRef(OPS + "user"), URIRef(OPS + "hasRole"),
            URIRef(OPS + "Curator")) in g
    assert (URIRef(OPS + "Curator"), RDF.type, URIRef(PROV + "Agent")) not in g


def test_the_prov_prefix_is_added_when_missing():
    assert "@prefix prov:" in add_agency(ONTOLOGY)


def test_adding_it_TWICE_adds_it_once():
    once = add_agency(ONTOLOGY)

    assert add_agency(once) == once
    assert once.count(AGENCY_SECTION) == 1


def test_an_ontology_that_already_has_prov_does_not_get_it_twice():
    with_prov = ONTOLOGY.replace(
        "@prefix dct:", "@prefix prov:   <http://www.w3.org/ns/prov#> .\n@prefix dct:")

    assert add_agency(with_prov).count("@prefix prov:") == 1


# -- an IMPORTED ontology is always written ----------------------------------
#
# The first cut compared the result with the input and skipped the write when
# they matched. Correct for a local file; silently wrong for an imported one,
# because the source already HAS the agency section — so the production run
# reported "already present" and left the deployment with no `operations.ttl`
# at all. Caught by a preview showing 0 adds (2026-10-01).


def test_adding_the_section_to_an_ontology_that_HAS_it_is_a_no_op():
    """The condition the skip was built for, which is still right."""
    once = add_agency(ONTOLOGY)

    assert add_agency(once) == once


def test_an_ontology_that_already_has_it_is_UNCHANGED_not_absent():
    """So a caller cannot tell "nothing to add" from "nothing to write" by
    comparing the text — which is exactly the mistake. The script tracks
    whether it IMPORTED instead."""
    source = add_agency(ONTOLOGY)

    assert add_agency(source) == source
    assert "ops:Role" in source, "and the content is there to be written"


def test_the_script_writes_an_imported_ontology_even_when_unchanged(tmp_path,
                                                                    monkeypatch):
    """The end-to-end property: a deployment with no operations.ttl gets one,
    whatever the source already contains."""
    import migrate_agent_iris as mod

    source = add_agency(ONTOLOGY)
    written = {}

    class _Ops:
        def read_text(self, path):
            raise FileNotFoundError(path)

        def write_text(self, path, text, make_parents=False):
            written[path] = text

    monkeypatch.setattr(mod, "_ontology_from", lambda cfg: source)
    monkeypatch.setattr(mod.cfgmod, "load_config", lambda p=None: {})
    monkeypatch.setattr(mod.cfgmod, "sandbox_root", lambda c, create=False: tmp_path)
    monkeypatch.setattr(mod.cfgmod, "git_content_extensions", lambda c: frozenset())
    monkeypatch.setattr(mod.cfgmod, "active_layout",
                        lambda c: type("L", (), {"dir": lambda s, k: "ttl/model"})())
    monkeypatch.setattr(mod, "FileOps", lambda *a, **k: _Ops())
    monkeypatch.setattr(mod.Sandbox, "open", staticmethod(lambda r, create=False: None))

    mod.main(["migrate_agent_iris.py", "--ontology-from", "other.rson"])

    assert "ttl/model/operations.ttl" in written
    assert "ops:Role" in written["ttl/model/operations.ttl"]
