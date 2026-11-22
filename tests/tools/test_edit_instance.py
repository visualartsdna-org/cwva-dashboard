"""Field-level instance editing: read a TTL as fields, write it back.

The property that matters most is **a save changes only what was edited**. Two
bugs found against the real store before this was believed:

- `schema:location "Woodstock, GA"` was split into two literals, because the
  widget joined multiple values with commas and the parser split on them. Arity
  is a property of the DATA, not of the text: a field that held one object
  writes back one object, commas and all. That corrupted 194 of 326 records on
  a save that changed nothing.
- `"9"` became `"9.0"`, and `a schema:QuantitativeValue` vanished, because a
  blank node was re-derived from its own rendering. An untouched field is now
  copied verbatim rather than round-tripped through a widget.

Verified across all 326 editable records: 290 byte-identical, 36 differing only
by the empty blank nodes we deliberately drop, 0 differing any other way.
"""

from __future__ import annotations

import pytest
from rdflib import BNode, Graph, Literal, URIRef
from rdflib.compare import graph_diff, isomorphic, to_isomorphic
from rdflib.namespace import RDF, RDFS, XSD

from cwva_dashboard.sandbox.fileops import FileOps
from cwva_dashboard.sandbox.paths import Sandbox
from cwva_dashboard.tools.base import ToolError
from cwva_dashboard.tools.edit_tools import (
    ENTITIES,
    WORKS,
    list_editable,
    read_instance,
    write_instance,
)

WORK = "http://visualartsdna.org/work/w1"

# Shaped after a real watercolour: a dimension blank node, a comma-bearing
# location, multi-valued concepts, and an empty blank node left by the Groovy.
RECORD = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix schema: <https://schema.org/> .
@prefix the: <http://visualartsdna.org/thesaurus/> .
@prefix vad: <http://visualartsdna.org/model/> .
@prefix work: <http://visualartsdna.org/work/> .
@prefix xs: <http://www.w3.org/2001/XMLSchema#> .

work:w1 a vad:Watercolor, vad:CreativeWork ;
    rdfs:label "Adelaide Sketch" ;
    schema:location "Woodstock, GA" ;
    schema:dateCreated "2024-01-11"^^xs:date ;
    schema:height [ a schema:QuantitativeValue ;
        rdfs:label "12 inches" ; schema:unitCode "INH" ; schema:value "12"^^xs:float ] ;
    vad:hasWatercolorPaint the:IndigoSCC, the:ManganeseDD ;
    the:document [ ] ;
    vad:hasNFT [ a vad:NFT ; vad:hasMarketPlace "OpenSea" ;
                 vad:hasNFTTokenID "7237923464623877" ] .
"""

# An ENTITY, shaped after the Pillars background image in production: a single
# subject, no art-form type, and `skos:inScheme the:entities` — which is what
# `record.new_entity` writes on every entity and nothing else in the store
# carries.
ENTITY = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix schema: <https://schema.org/> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix the: <http://visualartsdna.org/thesaurus/> .
@prefix work: <http://visualartsdna.org/work/> .

work:e1 a the:Image ;
    rdfs:label "Pillars" ;
    the:topic the:Background ;
    skos:inScheme the:entities ;
    schema:image <http://visualartsdna.org/images/pillars_2k.hdr> .
"""

AGGREGATE = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix work: <http://visualartsdna.org/work/> .
work:a rdfs:label "One" .
work:b rdfs:label "Two" .
"""


@pytest.fixture
def env(tmp_path):
    sb = Sandbox.open(tmp_path / "stage", create=True)
    ops = FileOps(sb)
    ops.write_text("ttl/data/w1.ttl", RECORD, make_parents=True)
    ops.write_text("ttl/data/agg.ttl", AGGREGATE, make_parents=True)
    ops.write_text("ttl/data/e1.ttl", ENTITY, make_parents=True)
    return ops


def _fields(ops, path="ttl/data/w1.ttl"):
    return {f["curie"]: f for f in read_instance(ops, path)["fields"]}


def _graph(ops, path="ttl/data/w1.ttl"):
    return Graph().parse(data=ops.read_text(path), format="turtle")


def _save(ops, **edits):
    r = read_instance(ops, "ttl/data/w1.ttl")
    values = {f["predicate"]: f["value"] for f in r["fields"]}
    for curie, new in edits.items():
        pred = next(f["predicate"] for f in r["fields"] if f["curie"] == curie)
        values[pred] = new
    return write_instance(ops, "ttl/data/w1.ttl", values)


# -- what may be edited ------------------------------------------------------


def test_a_single_subject_file_is_editable(env):
    assert read_instance(env, "ttl/data/w1.ttl")["editable"] is True


def test_an_AGGREGATE_is_refused(env):
    """Derived from the file, not from a maintained list: 8 of 334 real data
    files hold many subjects and they are exactly the aggregates and system
    output. A newly generated one is protected the day it appears."""
    r = read_instance(env, "ttl/data/agg.ttl")

    assert r["editable"] is False
    assert "2 subjects" in r["reason"]


def test_writing_an_aggregate_is_refused_by_the_TOOL(env):
    """Not merely hidden by the UI — the refusal is in the capability."""
    with pytest.raises(ToolError) as exc:
        write_instance(env, "ttl/data/agg.ttl", {})
    assert exc.value.code == "not_editable"


def test_list_editable_skips_aggregates(env):
    got = list_editable(env, "ttl/data", {"Watercolor"})["records"]
    assert [r["label"] for r in got] == ["Adelaide Sketch"]


def test_list_editable_offers_ONLY_ART_FORMS(env):
    """Artists and artist profiles are single-subject records too, and neither
    belongs in a picker whose form edits works (Rick, 2026-09-18): they have
    editors that know what a persona owns and what may not change about it. The
    set comes from the ontology — `art_form_names` — not from a list here.

    Entities were excluded by the same rule and should not have been; they are
    a GROUP of their own now, below."""
    env.write_text(
        "ttl/data/artist.ttl",
        '@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n'
        '@prefix vad: <http://visualartsdna.org/model/> .\n'
        '@prefix work: <http://visualartsdna.org/work/> .\n'
        'work:a1 a vad:Painter ; rdfs:label "A Painter" .\n',
    )

    got = list_editable(env, "ttl/data", {"Watercolor"})["records"]

    assert [r["label"] for r in got] == ["Adelaide Sketch"]


def test_list_editable_offers_NOTHING_when_the_model_cannot_classify(env):
    """Not everything. A store with no ontology cannot tell a work from an
    artist, and offering an artist to a form built for works is worse than an
    empty list with a reason."""
    assert list_editable(env, "ttl/data", None)["records"] == []


# -- two groups, named, never merged (Rick, 2026-09-27) -----------------------
#
# The picker was works-only, so the Pillars background image could be edited
# only by typing `/edit/open?path=…` by hand. The EDITOR always handled it —
# file-based, renders the whole file, preserves verbatim what it cannot render.
# Only the list was closed.


def test_the_entity_group_lists_entities(env):
    got = list_editable(env, "ttl/data", {"Watercolor"}, kind=ENTITIES)["records"]

    assert [r["label"] for r in got] == ["Pillars"]


def test_the_work_group_still_excludes_them(env):
    """A second group, not a loosened filter: the works list is unchanged."""
    got = list_editable(env, "ttl/data", {"Watercolor"}, kind=WORKS)["records"]

    assert [r["label"] for r in got] == ["Adelaide Sketch"]
    assert list_editable(env, "ttl/data", {"Watercolor"})["records"] == got


def test_entity_membership_is_the_SCHEME_not_the_type(env):
    """Derived, like the work rule. `the:Image` is not an entity type — the same
    class names a work's image — so a type list would be both wrong and
    destined to drift; `skos:inScheme the:entities` is what the entity tool
    writes and what the store actually carries."""
    env.write_text(
        "ttl/data/loose.ttl",
        '@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n'
        '@prefix the: <http://visualartsdna.org/thesaurus/> .\n'
        '@prefix work: <http://visualartsdna.org/work/> .\n'
        'work:x1 a the:Image ; rdfs:label "Not in the scheme" .\n',
    )

    got = list_editable(env, "ttl/data", {"Watercolor"}, kind=ENTITIES)["records"]

    assert [r["label"] for r in got] == ["Pillars"]


def test_an_ARTIST_is_in_neither_group(env):
    """The rule the original exclusion was really for, and it still holds."""
    env.write_text(
        "ttl/data/artist.ttl",
        '@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n'
        '@prefix vad: <http://visualartsdna.org/model/> .\n'
        '@prefix work: <http://visualartsdna.org/work/> .\n'
        'work:a1 a vad:Painter ; rdfs:label "A Painter" .\n',
    )

    for kind in (WORKS, ENTITIES):
        labels = [r["label"]
                  for r in list_editable(env, "ttl/data", {"Watercolor"},
                                         kind=kind)["records"]]
        assert "A Painter" not in labels, kind


def test_an_AGGREGATE_is_out_of_both_groups(env):
    """One named subject is the rule for editing at all; the group is a filter
    applied after it, never instead of it."""
    env.write_text(
        "ttl/data/entagg.ttl",
        '@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n'
        '@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n'
        '@prefix the: <http://visualartsdna.org/thesaurus/> .\n'
        '@prefix work: <http://visualartsdna.org/work/> .\n'
        'work:e8 rdfs:label "Eight" ; skos:inScheme the:entities .\n'
        'work:e9 rdfs:label "Nine" ; skos:inScheme the:entities .\n',
    )

    got = list_editable(env, "ttl/data", {"Watercolor"}, kind=ENTITIES)["records"]

    assert [r["label"] for r in got] == ["Pillars"]


# -- a save changes only what was edited -------------------------------------


def test_a_noop_save_is_lossless_apart_from_empty_blank_nodes(env):
    """Compared against `before` with its empty blank nodes removed, rather than
    by diffing the two graphs directly: dropping one blank node relabels the
    others under canonicalisation, so a direct diff reports untouched nodes as
    lost-and-added. That artifact is exactly what makes this property easy to
    believe wrongly in either direction."""
    before = _graph(env)
    expected = Graph()
    for s_, p_, o_ in before:
        if isinstance(o_, BNode) and not list(before.predicate_objects(o_)):
            continue  # the empty node we deliberately drop
        expected.add((s_, p_, o_))

    _save(env)

    after = _graph(env)
    # The save stamps schema:dateModified — an intended addition, removed here
    # so the rest of the record can be compared for the thing that matters.
    for o in list(after.objects(URIRef(WORK), URIRef("https://schema.org/dateModified"))):
        after.remove((URIRef(WORK), URIRef("https://schema.org/dateModified"), o))
    assert isomorphic(expected, after)


def test_a_comma_bearing_TEXT_value_survives(env):
    """`schema:location "Woodstock, GA"` became two literals. Arity comes from
    the data: one object in, one object out."""
    _save(env)

    locs = list(_graph(env).objects(URIRef(WORK), URIRef("https://schema.org/location")))
    assert locs == [Literal("Woodstock, GA")]


def test_a_multi_valued_field_still_splits(env):
    _save(env)
    paints = set(_graph(env).objects(
        URIRef(WORK), URIRef("http://visualartsdna.org/model/hasWatercolorPaint")))

    assert len(paints) == 2


def test_an_untouched_dimension_keeps_its_exact_literal(env):
    """`"12"^^xs:float` must not become `"12.0"`. Re-deriving a value from its
    own rendering is where silent change comes from."""
    _save(env)
    g = _graph(env)
    bn = g.value(URIRef(WORK), URIRef("https://schema.org/height"))

    assert g.value(bn, URIRef("https://schema.org/value")) == Literal("12", datatype=XSD.float)
    assert (bn, RDF.type, URIRef("https://schema.org/QuantitativeValue")) in g


# -- blank nodes -------------------------------------------------------------


def test_a_labelled_blank_node_edits_through_its_label(env):
    _save(env, **{"schema:height": "15.5 inches"})
    g = _graph(env)
    bn = g.value(URIRef(WORK), URIRef("https://schema.org/height"))

    assert g.value(bn, RDFS.label) == Literal("15.5 inches")
    assert g.value(bn, URIRef("https://schema.org/value")) == Literal("15.5", datatype=XSD.float)
    assert g.value(bn, URIRef("https://schema.org/unitCode")) == Literal("INH")
    assert (bn, RDF.type, URIRef("https://schema.org/QuantitativeValue")) in g, "type carried"


def test_an_unparseable_label_keeps_the_old_value_and_SAYS_SO(env):
    """Dropping the value loses data; deriving nothing and staying quiet leaves
    the node disagreeing with its own label."""
    out = _save(env, **{"schema:height": "about a foot"})
    g = _graph(env)
    bn = g.value(URIRef(WORK), URIRef("https://schema.org/height"))

    assert g.value(bn, URIRef("https://schema.org/value")) == Literal("12", datatype=XSD.float)
    assert out["warnings"] and "not 'number unit'" in out["warnings"][0]


def test_an_UNLABELLED_blank_node_is_read_only_and_survives(env):
    """Seven fields of NFT provenance have no faithful one-line summary.
    Inventing one would be a way to lose them."""
    fields = _fields(env)

    assert fields["vad:hasNFT"]["mode"] == "read_only"
    _save(env)
    g = _graph(env)
    nft = g.value(URIRef(WORK), URIRef("http://visualartsdna.org/model/hasNFT"))
    assert g.value(nft, URIRef("http://visualartsdna.org/model/hasNFTTokenID")) is not None


def test_an_EMPTY_blank_node_is_dropped(env):
    """`the:document [ ]` — 15 of them in the real store, left by the Groovy's
    conditional emission. They carry nothing and only invite poking at."""
    assert "the:document" not in _fields(env)

    _save(env)
    g = _graph(env)
    assert g.value(URIRef(WORK), URIRef("http://visualartsdna.org/thesaurus/document")) is None


# -- editing ------------------------------------------------------------------


def test_clearing_a_field_removes_the_triple(env):
    out = _save(env, **{"schema:location": ""})

    assert "schema:location" in out["cleared"]
    assert list(_graph(env).objects(URIRef(WORK), URIRef("https://schema.org/location"))) == []


def test_a_changed_field_is_reported(env):
    out = _save(env, **{"rdfs:label": "Adelaide Sketch II"})

    assert out["changed"] == ["rdfs:label"]
    assert _graph(env).value(URIRef(WORK), RDFS.label) == Literal("Adelaide Sketch II")


def test_sensitive_fields_carry_a_warning(env):
    """Not blocked — the user owns the data — but flagged, because these have
    consequences beyond the record. `rdf:type`, the GUID and the qrcode moved
    past warning to READ-ONLY: they are not things to be careful with, they are
    things not to touch."""
    ops = env
    ops.write_text(
        "ttl/data/w2.ttl",
        RECORD.replace("work:w1", "work:w2").replace(
            'rdfs:label "Adelaide Sketch" ;',
            'rdfs:label "Adelaide Sketch" ;\n    schema:image '
            "<http://visualartsdna.org/images/a.jpg> ;"),
        make_parents=True,
    )
    fields = {f["curie"]: f for f in read_instance(ops, "ttl/data/w2.ttl")["fields"]}

    assert "does NOT delete the image" in fields["schema:image"]["warning"]


def test_the_guid_and_qrcode_are_read_only(env):
    """The GUID is the tail of the record's URI: changing it orphans every
    reference to the work while leaving them all looking valid. The qrcode is
    derived from it, and editing the text cannot move the picture."""
    ops = env
    ops.write_text(
        "ttl/data/w3.ttl",
        RECORD.replace("work:w1", "work:w3").replace(
            'rdfs:label "Adelaide Sketch" ;',
            'rdfs:label "Adelaide Sketch" ;\n    schema:identifier "w3" ;\n'
            "    vad:qrcode <http://visualartsdna.org/images/qrc_w3.jpg> ;"),
        make_parents=True,
    )
    fields = {f["curie"]: f for f in read_instance(ops, "ttl/data/w3.ttl")["fields"]}

    assert fields["schema:identifier"]["mode"] == "read_only"
    assert fields["vad:qrcode"]["mode"] == "read_only"
    assert "orphan every reference" in fields["schema:identifier"]["reason"]


# -- system fields: shown, never edited --------------------------------------


def test_rdf_type_is_read_only(env):
    """Type is baked in: it decides which form created the record, which gates
    apply, and how every reader interprets the rest of it."""
    f = _fields(env)["rdf:type"]

    assert f["mode"] == "read_only"
    assert "baked in" in f["reason"]


def test_the_type_survives_an_attempt_to_change_it(env):
    """Read-only in the CAPABILITY, not just the page: a submitted value for a
    read-only field is ignored, not trusted."""
    r = read_instance(env, "ttl/data/w1.ttl")
    values = {f["predicate"]: f["value"] for f in r["fields"]}
    values[str(RDF.type)] = "vad:Sculpture"

    write_instance(env, "ttl/data/w1.ttl", values)

    types = set(_graph(env).objects(URIRef(WORK), RDF.type))
    assert URIRef("http://visualartsdna.org/model/Watercolor") in types
    assert URIRef("http://visualartsdna.org/model/Sculpture") not in types


def test_every_save_stamps_dateModified(env):
    out = _save(env)
    g = _graph(env)
    stamps = list(g.objects(URIRef(WORK), URIRef("https://schema.org/dateModified")))

    assert len(stamps) == 1
    assert stamps[0].datatype == XSD.dateTime, "dateModified takes a moment, not a day"
    assert out["stamped"]


def test_stamps_ACCUMULATE_rather_than_replace(env):
    """A record edited twice carries two stamps. The QA git has the history; the
    record travelling to SOT would not."""
    _save(env)
    _save(env)

    stamps = list(_graph(env).objects(URIRef(WORK), URIRef("https://schema.org/dateModified")))
    assert len(stamps) == 2


def test_dateModified_is_read_only(env):
    f = _fields(env)
    _save(env)
    f = _fields(env)

    assert f["schema:dateModified"]["mode"] == "read_only"


def test_dateCreated_stays_EDITABLE(env):
    """All date fields stay editable so dateCreated can be corrected. A user who
    knows better will leave the others alone."""
    assert _fields(env)["schema:dateCreated"]["mode"] == "editable"

    _save(env, **{"schema:dateCreated": "2023-05-04"})
    assert _graph(env).value(
        URIRef(WORK), URIRef("https://schema.org/dateCreated")) == Literal(
            "2023-05-04", datatype=XSD.date)


# -- a reference field accepts a LIST (Rick, 2026-09-28) ----------------------
#
# `the:tag` on the Prestress Images collection held one value, so the
# literal-arity rule took nine comma-separated CURIEs as ONE IRI with eight
# commas in it. That parses and serializes, so it was written, committed and
# converged to the real SOT with nothing complaining. Typed with spaces after
# the commas it did complain — a bare serializer exception out of a save.

TAGGED = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix schema: <https://schema.org/> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix the: <http://visualartsdna.org/thesaurus/> .
@prefix work: <http://visualartsdna.org/work/> .

work:c1 a the:Collection ;
    rdfs:label "Prestress Images" ;
    skos:inScheme the:entities ;
    the:tag work:t1 ;
    schema:sameAs <https://getty.edu/x#:~:text=the%20most%20innovative,the%20blue%20sky> .
"""

TAG = URIRef("http://visualartsdna.org/thesaurus/tag")
SAME_AS = URIRef("https://schema.org/sameAs")
COLLECTION = URIRef("http://visualartsdna.org/work/c1")


@pytest.fixture
def tagged(tmp_path):
    from cwva_dashboard.sandbox.fileops import FileOps
    from cwva_dashboard.sandbox.paths import Sandbox

    ops = FileOps(Sandbox.open(tmp_path / "stage", create=True))
    ops.write_text("ttl/data/c1.ttl", TAGGED, make_parents=True)
    return ops


def _save_tags(ops, text):
    r = read_instance(ops, "ttl/data/c1.ttl")
    values = {f["predicate"]: f["value"] for f in r["fields"]}
    values[str(TAG)] = text
    write_instance(ops, "ttl/data/c1.ttl", values)
    return Graph().parse(data=ops.read_text("ttl/data/c1.ttl"), format="turtle")


def test_a_single_valued_reference_field_can_be_given_a_list(tagged):
    g = _save_tags(tagged, "work:t1,work:t2,work:t3")

    assert sorted(str(o).rsplit("/", 1)[-1] for o in g.objects(COLLECTION, TAG)) == [
        "t1", "t2", "t3"]


def test_the_parts_are_whole_IRIs_not_one_with_commas_in_it(tagged):
    """The actual defect: one object whose IRI carried eight commas."""
    g = _save_tags(tagged, "work:t1,work:t2")

    assert not any("," in str(o) for o in g.objects(COLLECTION, TAG))


def test_spaces_after_the_commas_are_accepted_too(tagged):
    """The form of the list that used to raise a serializer exception."""
    g = _save_tags(tagged, "work:t1, work:t2, work:t3")

    assert len(list(g.objects(COLLECTION, TAG))) == 3


def test_a_COMMA_BEARING_IRI_is_left_whole(tagged):
    """A comma is a legal URI character, and 29 IRIs in the real store carry
    one — `#:~:text=` fragment links into Getty and Wikipedia. The
    discriminator is whether every part is itself a reference, not whether a
    comma is present."""
    url = ("https://getty.edu/x#:~:text=the%20most%20innovative,"
           "the%20blue%20sky")
    r = read_instance(tagged, "ttl/data/c1.ttl")
    values = {f["predicate"]: f["value"] for f in r["fields"]}
    write_instance(tagged, "ttl/data/c1.ttl", values)
    g = Graph().parse(data=tagged.read_text("ttl/data/c1.ttl"), format="turtle")

    assert list(g.objects(COLLECTION, SAME_AS)) == [URIRef(url)]


def test_a_value_that_is_not_an_IRI_is_REFUSED_not_written(tagged):
    """`URIRef` accepts anything and the Turtle serializer does not; the gap is
    where a record gets written that can be parsed and not re-written. The
    refusal names the field, because that is what the user can fix."""
    with pytest.raises(ToolError) as exc:
        _save_tags(tagged, "work:t1 and also work:t2")

    assert exc.value.code == "invalid_iri"
    assert "tag" in str(exc.value).lower()
    # Nothing written: the record still holds what it held.
    g = Graph().parse(data=tagged.read_text("ttl/data/c1.ttl"), format="turtle")
    assert list(g.objects(COLLECTION, TAG)) == [
        URIRef("http://visualartsdna.org/work/t1")]


def test_THE_REPAIR_IS_REPORTED_not_silent(tagged):
    """A save the user thinks changed nothing has just changed a field, and
    they are about to distribute it."""
    corrupt = "http://visualartsdna.org/work/t1,work:t2,work:t3"
    tagged.write_text(
        "ttl/data/c1.ttl",
        TAGGED.replace("the:tag work:t1", f"the:tag <{corrupt}>"),
    )
    r = read_instance(tagged, "ttl/data/c1.ttl")
    values = {f["predicate"]: f["value"] for f in r["fields"]}

    out = write_instance(tagged, "ttl/data/c1.ttl", values)

    assert any("the:tag" in w and "separated into 3" in w
               for w in out.get("warnings") or []), out.get("warnings")


def test_an_UNTOUCHED_reference_field_is_still_copied_verbatim(tagged):
    """The repair is narrow: a field that agrees with its own rendering is
    preserved exactly as before, which is the rule 2,828 of 2,829 real
    reference fields rely on."""
    before = tagged.read_text("ttl/data/c1.ttl")
    r = read_instance(tagged, "ttl/data/c1.ttl")
    values = {f["predicate"]: f["value"] for f in r["fields"]}

    out = write_instance(tagged, "ttl/data/c1.ttl", values)

    assert out.get("warnings") in (None, [])
    after = Graph().parse(data=tagged.read_text("ttl/data/c1.ttl"), format="turtle")
    was = Graph().parse(data=before, format="turtle")
    # Everything but the accumulating dateModified stamp is unchanged.
    stamp = URIRef("https://schema.org/dateModified")
    assert sorted((str(s_), str(p_), str(o_)) for s_, p_, o_ in after
                  if p_ != stamp) == sorted(
        (str(s_), str(p_), str(o_)) for s_, p_, o_ in was if p_ != stamp)


def test_REOPENING_A_CORRUPTED_FIELD_REPAIRS_IT(tagged):
    """The record already in production holds one IRI with eight commas. It
    renders as the CURIE list the user typed, so an ordinary open-and-save now
    separates it — the repair is the normal path, not a migration."""
    corrupt = ("http://visualartsdna.org/work/t1,work:t2,work:t3")
    tagged.write_text(
        "ttl/data/c1.ttl",
        TAGGED.replace("the:tag work:t1", f"the:tag <{corrupt}>"),
    )

    r = read_instance(tagged, "ttl/data/c1.ttl")
    values = {f["predicate"]: f["value"] for f in r["fields"]}
    write_instance(tagged, "ttl/data/c1.ttl", values)
    g = Graph().parse(data=tagged.read_text("ttl/data/c1.ttl"), format="turtle")

    assert sorted(str(o).rsplit("/", 1)[-1] for o in g.objects(COLLECTION, TAG)) == [
        "t1", "t2", "t3"]


# -- nested blank nodes are preserved WHOLE (Rick, 2026-09-28) ----------------
#
# Preservation went exactly one level down, which is faithful for the two
# shapes the editor was written against — a `schema:QuantitativeValue` and a
# `vad:NFT` node are both flat. A profile's `ops:template` is not: a list of
# `ops:field` blank nodes hung off a node that is itself blank. A no-op save on
# a real artist-profile record wrote back 29 of its 78 triples, and the file
# parsed and the gates passed with the template gone.

NESTED = """@prefix ops: <http://visualartsdna.org/operations/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix schema: <https://schema.org/> .
@prefix vad: <http://visualartsdna.org/model/> .
@prefix work: <http://visualartsdna.org/work/> .

work:p1 a vad:ArtistProfile ;
    rdfs:label "Blender Application" ;
    ops:template [ ops:templateType vad:Blender ;
        ops:field [ ops:property schema:height ; ops:order 1 ;
                    ops:required true ] ;
        ops:field [ ops:property schema:width ; ops:order 2 ;
                    ops:note [ rdfs:label "three levels down" ] ] ] .
"""

PROFILE = URIRef("http://visualartsdna.org/work/p1")


@pytest.fixture
def nested_env(tmp_path):
    from cwva_dashboard.sandbox.fileops import FileOps
    from cwva_dashboard.sandbox.paths import Sandbox

    ops = FileOps(Sandbox.open(tmp_path / "stage", create=True))
    ops.write_text("ttl/data/p1.ttl", NESTED, make_parents=True)
    return ops


def _resave(ops, path="ttl/data/p1.ttl"):
    before = Graph().parse(data=ops.read_text(path), format="turtle")
    r = read_instance(ops, path)
    write_instance(ops, path, {f["predicate"]: f["value"] for f in r["fields"]})
    after = Graph().parse(data=ops.read_text(path), format="turtle")
    stamp = URIRef("https://schema.org/dateModified")
    for g in (before, after):
        for t in list(g.triples((None, stamp, None))):
            g.remove(t)
    return before, after


def test_a_NO_OP_SAVE_KEEPS_EVERY_TRIPLE(nested_env):
    before, after = _resave(nested_env)

    assert len(after) == len(before), f"{len(before)} in, {len(after)} out"
    assert isomorphic(before, after)


def test_the_THIRD_LEVEL_survives_too(nested_env):
    """One level of recursion would be a fix that fails on the next record."""
    _, after = _resave(nested_env)

    assert Literal("three levels down") in set(after.objects())


def test_a_LABELLED_node_carries_its_nested_structure(nested_env):
    """The labelled-bnode branch REBUILDS rather than copies, and it too carried
    only one level. A label is no promise of flatness."""
    nested_env.write_text(
        "ttl/data/p2.ttl",
        NESTED.replace("work:p1", "work:p2").replace(
            "ops:template [ ops:templateType vad:Blender ;",
            'ops:template [ rdfs:label "9 inches" ; ops:templateType vad:Blender ;'),
    )

    before, after = _resave(nested_env, "ttl/data/p2.ttl")

    assert Literal("three levels down") in set(after.objects())
    assert len(after) >= len(before) - 1  # the label branch re-derives value/unit


def test_a_CYCLE_terminates(nested_env):
    """RDF permits a blank node to reach itself; the walk must not."""
    nested_env.write_text(
        "ttl/data/p3.ttl",
        """@prefix ops: <http://visualartsdna.org/operations/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix work: <http://visualartsdna.org/work/> .

work:p3 rdfs:label "Round" ; ops:template _:a .
_:a ops:field _:b .
_:b ops:back _:a .
""",
    )

    before, after = _resave(nested_env, "ttl/data/p3.ttl")

    assert isomorphic(before, after)


# -- a labelled blank node is a dimension only when the label IS the content --
#
# The branch assumed "labelled == dimension", which is true of 906 blank nodes
# in the real store and false of 43: a profile's `ops:template` is labelled
# "Input Form Spec", and a `the:document` node "gdoc source". Those were offered
# as an editable one-line text box that warned, on save, that the value was not
# "number unit" — an invitation to edit a whole form template through its title.

NAMED_STRUCTURE = """@prefix ops: <http://visualartsdna.org/operations/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix schema: <https://schema.org/> .
@prefix work: <http://visualartsdna.org/work/> .
@prefix xs: <http://www.w3.org/2001/XMLSchema#> .

work:s1 rdfs:label "A record" ;
    schema:height [ a schema:QuantitativeValue ; rdfs:label "12 inches" ;
                    schema:unitCode "INH" ; schema:value "12"^^xs:float ] ;
    ops:template [ rdfs:label "Input Form Spec" ;
                   ops:field [ ops:property schema:height ; ops:order 1 ] ] .
"""


@pytest.fixture
def named(tmp_path):
    from cwva_dashboard.sandbox.fileops import FileOps
    from cwva_dashboard.sandbox.paths import Sandbox

    ops = FileOps(Sandbox.open(tmp_path / "stage", create=True))
    ops.write_text("ttl/data/s1.ttl", NAMED_STRUCTURE, make_parents=True)
    return ops


def _by_curie(ops, path="ttl/data/s1.ttl"):
    return {f["curie"]: f for f in read_instance(ops, path)["fields"]}


def test_a_DIMENSION_is_still_editable_through_its_label(named):
    f = _by_curie(named)["schema:height"]

    assert f["mode"] == "editable"
    assert f["kind"] == "bnode_label"
    assert f["value"] == "12 inches"


def test_a_label_that_NAMES_a_structure_is_read_only(named):
    f = _by_curie(named)["ops:template"]

    assert f["mode"] == "read_only"
    assert f["kind"] == "structure"


def test_the_structure_shows_its_nesting_not_a_blank_node_id(named):
    """It printed the rdflib id — `ops:field=N7a3f9c...` — which tells a person
    nothing and reads as corruption."""
    f = _by_curie(named)["ops:template"]

    assert "ops:property=schema:height" in f["value"]
    assert "ops:order=1" in f["value"]
    assert "N" not in f["value"].replace("Input Form Spec", "")  # no bnode ids


def test_the_named_structure_still_survives_a_save(named):
    before, after = _resave(named, "ttl/data/s1.ttl")

    assert isomorphic(before, after)


# -- one picker per file, for a field that holds several ----------------------

TWO_IMAGES = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix schema: <https://schema.org/> .
@prefix work: <http://visualartsdna.org/work/> .

work:m1 rdfs:label "Two pictures" ;
    schema:image <http://visualartsdna.org/images/a.jpg>,
                 <http://visualartsdna.org/images/b.jpg> .
"""

IMAGE_KIND = {"https://schema.org/image": {"kind": "image", "subtree": "images"}}


@pytest.fixture
def two(tmp_path):
    from cwva_dashboard.sandbox.fileops import FileOps
    from cwva_dashboard.sandbox.paths import Sandbox

    ops = FileOps(Sandbox.open(tmp_path / "stage", create=True))
    ops.write_text("ttl/data/m1.ttl", TWO_IMAGES, make_parents=True)
    return ops


def test_each_file_gets_its_own_slot(two):
    f = {x["curie"]: x for x in
         read_instance(two, "ttl/data/m1.ttl", IMAGE_KIND)["fields"]}["schema:image"]

    assert [i["value"] for i in f["items"]] == ["a.jpg", "b.jpg"]
    assert len({i["name"] for i in f["items"]}) == 2


def test_replacing_ONE_file_leaves_the_other_alone(two):
    """A single select over two images could only offer both names joined, so
    choosing a replacement swapped both for one."""
    r = read_instance(two, "ttl/data/m1.ttl", IMAGE_KIND)
    f = {x["curie"]: x for x in r["fields"]}["schema:image"]
    values = {x["predicate"]: x["value"] for x in r["fields"]}
    values[f["items"][1]["name"]] = "c.jpg"
    values[f["items"][0]["name"]] = "a.jpg"

    write_instance(two, "ttl/data/m1.ttl", values, IMAGE_KIND,
                   image_base="http://visualartsdna.org/images/")

    g = Graph().parse(data=two.read_text("ttl/data/m1.ttl"), format="turtle")
    assert sorted(str(o).rsplit("/", 1)[-1]
                  for o in g.objects(URIRef("http://visualartsdna.org/work/m1"),
                                     URIRef("https://schema.org/image"))) == [
        "a.jpg", "c.jpg"]


def test_a_single_file_field_keeps_the_PREDICATE_as_its_name(two):
    """The common case does not learn a new spelling."""
    two.write_text("ttl/data/one.ttl", TWO_IMAGES.replace(
        ",\n                 <http://visualartsdna.org/images/b.jpg>", ""))
    f = {x["curie"]: x for x in
         read_instance(two, "ttl/data/one.ttl", IMAGE_KIND)["fields"]}["schema:image"]

    assert f["items"] == []
    assert f["value"] == "a.jpg"
