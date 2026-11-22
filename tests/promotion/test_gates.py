"""Validation gates: parse, SHACL conformance, SPARQL assertions."""

from __future__ import annotations

from rdflib import Graph

from cwva_dashboard.promotion.gates import (
    Assertion,
    load_graph,
    parse_gate,
    shacl_gate,
    sparql_assertions_gate,
)

EX = "http://example.org/"

GOOD_TTL = """
@prefix ex: <http://example.org/> .
ex:w1 a ex:Work ; ex:title "Sunrise" .
ex:w2 a ex:Work ; ex:title "Dusk" .
"""

# w3 has no title — fails the SHACL shape and the SPARQL assertion.
MISSING_TITLE_TTL = """
@prefix ex: <http://example.org/> .
ex:w3 a ex:Work .
"""

SHAPES_TTL = """
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix ex: <http://example.org/> .
ex:WorkShape a sh:NodeShape ;
    sh:targetClass ex:Work ;
    sh:property [ sh:path ex:title ; sh:minCount 1 ] .
"""

# A malformed Turtle file (unterminated string).
BAD_TTL = '@prefix ex: <http://example.org/> .\nex:w a ex:Work ; ex:title "oops .\n'


def _write(dirpath, name, text):
    p = dirpath / name
    p.write_text(text)
    return p


def test_parse_gate_passes_on_valid_ttl(tmp_path):
    _write(tmp_path, "a.ttl", GOOD_TTL)
    _write(tmp_path, "b.ttl", MISSING_TITLE_TTL)
    res = parse_gate([tmp_path / "a.ttl", tmp_path / "b.ttl"])
    assert res.ok
    assert res.details["files"] == 2


def test_parse_gate_attributes_failure_to_file(tmp_path):
    good = _write(tmp_path, "good.ttl", GOOD_TTL)
    bad = _write(tmp_path, "bad.ttl", BAD_TTL)
    res = parse_gate([good, bad])
    assert not res.ok
    assert any("bad.ttl" in m for m in res.messages)
    assert all("good.ttl" not in m for m in res.messages)


def test_parse_gate_ignores_non_rdf(tmp_path):
    _write(tmp_path, "notes.md", "# not rdf")
    res = parse_gate([tmp_path / "notes.md"])
    assert res.ok and res.details["files"] == 0


def test_shacl_gate_conforms(tmp_path):
    data = Graph().parse(data=GOOD_TTL, format="turtle")
    shapes = Graph().parse(data=SHAPES_TTL, format="turtle")
    res = shacl_gate(data, shapes)
    assert res.ok
    assert "conforms" in res.summary


def test_shacl_gate_reports_violation(tmp_path):
    data = Graph().parse(data=GOOD_TTL + MISSING_TITLE_TTL, format="turtle")
    shapes = Graph().parse(data=SHAPES_TTL, format="turtle")
    res = shacl_gate(data, shapes)
    assert not res.ok
    assert res.messages  # human-readable violation lines present


def test_sparql_assertion_empty_expectation(tmp_path):
    data = Graph().parse(data=GOOD_TTL, format="turtle")
    missing_title = Assertion(
        name="work_without_title",
        query=(
            "PREFIX ex: <http://example.org/> "
            "SELECT ?w WHERE { ?w a ex:Work . FILTER NOT EXISTS { ?w ex:title ?t } }"
        ),
        expect="empty",
    )
    assert sparql_assertions_gate(data, [missing_title]).ok

    data_bad = Graph().parse(data=GOOD_TTL + MISSING_TITLE_TTL, format="turtle")
    res = sparql_assertions_gate(data_bad, [missing_title])
    assert not res.ok
    assert any("work_without_title" in m for m in res.messages)


def test_sparql_assertion_ask_expectation(tmp_path):
    data = Graph().parse(data=GOOD_TTL, format="turtle")
    has_two_works = Assertion(
        name="at_least_one_work",
        query="PREFIX ex: <http://example.org/> ASK { ?w a ex:Work }",
        expect="true",
    )
    assert sparql_assertions_gate(data, [has_two_works]).ok


def test_load_graph_merges_files(tmp_path):
    _write(tmp_path, "a.ttl", GOOD_TTL)
    _write(tmp_path, "b.ttl", MISSING_TITLE_TTL)
    g = load_graph([tmp_path / "a.ttl", tmp_path / "b.ttl"])
    # 3 works total across the two files.
    works = set(g.subjects(predicate=None, object=None))
    assert len(list(g.triples((None, None, None)))) >= 3


def test_a_deleted_rdf_file_is_not_parsed(tmp_path):
    """Gates read only what will EXIST after the unit.

    `all_paths()` includes deletes, so a gate built on it opens a file that is
    being removed and raises FileNotFoundError. Latent until the first promotion
    containing a deleted RDF file — which arrived when two superseded
    workOnSite snapshots were cleaned up and the next preview crashed.
    """
    from cwva_dashboard.promotion.unit import ChangeManifest

    m = ChangeManifest(
        adds=["ttl/data/new.ttl"],
        modifies=["ttl/data/changed.ttl"],
        deletes=["ttl/data/gone.ttl"],
    )

    assert "ttl/data/gone.ttl" in m.all_paths(), "deletes still converge"
    assert m.present_paths() == ["ttl/data/changed.ttl", "ttl/data/new.ttl"]
