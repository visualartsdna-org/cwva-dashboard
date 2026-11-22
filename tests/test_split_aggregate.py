"""Splitting a multi-subject TTL into one file per subject.

The editors are file-based and refuse a file holding more than one named
subject, so seven artists in `artists.ttl` means Edit artist cannot open any of
them. The split is a RE-FILING — the same triples, one subject each — and the
script proves that before it writes anything.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from rdflib import Graph, URIRef
from rdflib.compare import isomorphic

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "split_aggregate.py"
_spec = importlib.util.spec_from_file_location("split_aggregate", _SCRIPT)
split_aggregate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(split_aggregate)

AGGREGATE = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix schema: <https://schema.org/> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ops:  <http://visualartsdna.org/operations/> .
@prefix vad:  <http://visualartsdna.org/model/> .
@prefix work: <http://visualartsdna.org/work/> .

work:a1 a vad:Painter ; rdfs:label "Rick Spates" ; vad:brand "visualartsdna.org" .

work:p1 a vad:ArtistProfile ;
    rdfs:label "Watercolor materials profile" ;
    vad:artist work:a1 ;
    vad:measurementSystem [ a skos:Concept ; schema:unitCode "INH" ] ;
    ops:template [ ops:templateType vad:Watercolor ;
        ops:field [ ops:property rdfs:label ; ops:order 10 ] ] .
"""


def _split(graph, subject):
    return split_aggregate.subgraph(graph, subject)


def test_the_union_of_the_parts_IS_the_graph():
    whole = Graph().parse(data=AGGREGATE, format="turtle")
    named = sorted({s for s in whole.subjects() if isinstance(s, URIRef)}, key=str)

    union = Graph()
    for subject in named:
        for triple in _split(whole, subject):
            union.add(triple)

    assert isomorphic(whole, union)
    assert len(union) == len(whole)


def test_BLANK_NODES_follow_the_record_that_owns_them():
    """A measurement system or a template field has no meaning apart from its
    profile, so it travels with it."""
    whole = Graph().parse(data=AGGREGATE, format="turtle")
    OPS = "http://visualartsdna.org/operations/"

    part = _split(whole, URIRef("http://visualartsdna.org/work/p1"))

    assert list(part.objects(None, URIRef(OPS + "templateType")))
    assert list(part.objects(None, URIRef(OPS + "property"))), "nested bnode too"


def test_a_NAMED_REFERENCE_is_not_copied_in():
    """The profile points at its artist. A reference is a reference — copying
    the artist in would put the same record in two files."""
    whole = Graph().parse(data=AGGREGATE, format="turtle")
    VAD = "http://visualartsdna.org/model/"

    part = _split(whole, URIRef("http://visualartsdna.org/work/p1"))

    assert URIRef("http://visualartsdna.org/work/a1") in set(
        part.objects(None, URIRef(VAD + "artist")))
    assert not list(part.objects(URIRef("http://visualartsdna.org/work/a1"), None)), (
        "the artist's own triples belong to the artist's file"
    )


def test_the_parts_are_each_EDITABLE(tmp_path):
    """The whole point: one named subject per file is what the editors require."""
    from cwva_dashboard.tools.edit_tools import _named_subjects

    whole = Graph().parse(data=AGGREGATE, format="turtle")
    for subject in {s for s in whole.subjects() if isinstance(s, URIRef)}:
        part = _split(whole, subject)
        assert len(_named_subjects(part)) == 1


# -- the script's refusals ----------------------------------------------------


def _sandbox(tmp_path, body=AGGREGATE, name="artists.ttl"):
    from cwva_dashboard.sandbox.fileops import FileOps
    from cwva_dashboard.sandbox.paths import Sandbox

    root = tmp_path / "qa"
    ops = FileOps(Sandbox.open(root, create=True))
    ops.write_text(f"ttl/data/{name}", body, make_parents=True)
    cfg = tmp_path / "c.rson"
    cfg.write_text('{"domain": "http://x.test", "sandbox": {"stage_root": "%s"}}'
                   % root)
    return root, str(cfg)


def test_it_SPLITS_and_trashes_the_original(tmp_path, capsys):
    root, cfg = _sandbox(tmp_path)

    rc = split_aggregate.main(["x", "--config", cfg, "--file", "ttl/data/artists.ttl"])

    assert rc == 0
    assert not (root / "ttl/data/artists.ttl").exists()
    assert (root / "ttl/data/a1.ttl").exists()
    assert (root / "ttl/data/p1.ttl").exists()
    # Trashed, not deleted: nothing hard-deletes what a person wrote.
    assert list((root / ".qa" / "trash").iterdir())


def test_a_DRY_RUN_writes_nothing(tmp_path):
    root, cfg = _sandbox(tmp_path)

    rc = split_aggregate.main(["x", "--config", cfg, "--file", "ttl/data/artists.ttl",
                               "--dry-run"])

    assert rc == 0
    assert (root / "ttl/data/artists.ttl").exists()
    assert not (root / "ttl/data/a1.ttl").exists()


def test_it_REFUSES_to_overwrite_an_existing_record(tmp_path):
    """Overwriting would destroy a record this script never read."""
    root, cfg = _sandbox(tmp_path)
    (root / "ttl/data/a1.ttl").write_text("# already here\n")

    rc = split_aggregate.main(["x", "--config", cfg, "--file", "ttl/data/artists.ttl"])

    assert rc == 1
    assert (root / "ttl/data/artists.ttl").exists(), "and wrote nothing"
    assert (root / "ttl/data/a1.ttl").read_text() == "# already here\n"


def test_a_SINGLE_SUBJECT_file_is_left_alone(tmp_path):
    root, cfg = _sandbox(tmp_path, body=(
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        "@prefix work: <http://visualartsdna.org/work/> .\n"
        'work:only rdfs:label "One" .\n'), name="one.ttl")

    rc = split_aggregate.main(["x", "--config", cfg, "--file", "ttl/data/one.ttl"])

    assert rc == 0
    assert (root / "ttl/data/one.ttl").exists()


def test_NAMING_THE_FILE_is_required(tmp_path):
    _root, cfg = _sandbox(tmp_path)

    assert split_aggregate.main(["x", "--config", cfg]) == 2


# -- importing from another sandbox ------------------------------------------
# Re-filing cannot serve every case. Production's artist profiles carry no
# `ops:template`, so re-filing them yields records `read_profile` refuses — dead
# cards, no entry forms. The records come from a sandbox that has templates
# instead, which changes the graph on purpose.

RICHER = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix schema: <https://schema.org/> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ops:  <http://visualartsdna.org/operations/> .
@prefix vad:  <http://visualartsdna.org/model/> .
@prefix work: <http://visualartsdna.org/work/> .

work:p1 a vad:ArtistProfile ;
    rdfs:label "Watercolor materials profile" ;
    vad:artist work:a1 ;
    vad:measurementSystem [ schema:unitCode "INH" ] ;
    ops:template [ ops:templateType vad:Watercolor ;
        ops:field [ ops:property rdfs:label ; ops:order 10 ] ,
                  [ ops:property schema:image ; ops:order 20 ] ] .
"""


def _with_source(tmp_path):
    """A target holding the aggregate, and a source holding a richer `p1`."""
    from cwva_dashboard.sandbox.fileops import FileOps
    from cwva_dashboard.sandbox.paths import Sandbox

    paths = {}
    for name, body, files in (
        ("target", AGGREGATE, [("ttl/data/artists.ttl", AGGREGATE)]),
        ("source", RICHER, [("ttl/data/p1.ttl", RICHER)]),
    ):
        root = tmp_path / name
        ops = FileOps(Sandbox.open(root, create=True))
        for rel, text in files:
            ops.write_text(rel, text, make_parents=True)
        cfg = tmp_path / f"{name}.rson"
        cfg.write_text('{"domain": "http://x.test", "sandbox": {"stage_root": "%s"}}'
                       % root)
        paths[name] = (root, str(cfg))
    return paths


def test_an_IMPORTED_record_replaces_the_aggregate_copy(tmp_path):
    p = _with_source(tmp_path)
    troot, tcfg = p["target"]

    rc = split_aggregate.main(["x", "--config", tcfg, "--file", "ttl/data/artists.ttl",
                               "--from", p["source"][1]])

    assert rc == 0
    got = Graph().parse(troot / "ttl/data/p1.ttl", format="turtle")
    OPS = "http://visualartsdna.org/operations/"
    assert list(got.objects(None, URIRef(OPS + "templateType"))), "the template came over"
    # A subject the source does not have falls back to the aggregate's copy.
    assert (troot / "ttl/data/a1.ttl").exists()
    a1 = Graph().parse(troot / "ttl/data/a1.ttl", format="turtle")
    assert len(a1) == 3


def test_an_import_does_NOT_require_the_graph_to_be_preserved(tmp_path, capsys):
    """Isomorphism is the wrong question for an import; the right one is "show
    me what changes", answered by a person."""
    p = _with_source(tmp_path)
    _troot, tcfg = p["target"]

    rc = split_aggregate.main(["x", "--config", tcfg, "--file", "ttl/data/artists.ttl",
                               "--from", p["source"][1], "--dry-run"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "graph preserved: False" in out
    assert "IMPORT would change the graph" in out


def test_every_LOSS_is_listed_in_full(tmp_path, capsys):
    """An addition you did not expect is a surprise; a removal you did not
    expect is a loss, so removals are never truncated."""
    p = _with_source(tmp_path)
    _troot, tcfg = p["target"]

    split_aggregate.main(["x", "--config", tcfg, "--file", "ttl/data/artists.ttl",
                          "--from", p["source"][1], "--dry-run"])
    out = capsys.readouterr().out

    assert "statement(s) production has and the source does NOT" in out
    # The aggregate's p1 had a measurement bnode typed skos:Concept; the richer
    # source's does not, so that is a loss and must be named.
    assert "skos:Concept" in out


def test_a_RE_FILING_still_refuses_when_the_graph_would_change(tmp_path, capsys):
    """The guard is only relaxed for an import."""
    root, cfg = _sandbox(tmp_path)
    original = split_aggregate.subgraph

    def lossy(graph, subject):
        part = original(graph, subject)
        for triple in list(part)[:1]:
            part.remove(triple)
        return part

    split_aggregate.subgraph = lossy
    try:
        rc = split_aggregate.main(["x", "--config", cfg, "--file", "ttl/data/artists.ttl"])
    finally:
        split_aggregate.subgraph = original
    out = capsys.readouterr().out

    assert rc == 1
    assert "would not preserve the graph" in out
    assert (root / "ttl/data/artists.ttl").exists()
