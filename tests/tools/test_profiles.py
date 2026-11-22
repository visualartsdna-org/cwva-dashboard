"""Reading an artist profile — the record that drives an entry form.

CE_DESIGN §14. A profile names an artist, a measurement system and an ordered
list of properties; the dashboard builds the form from it. So reading is
VALIDATING: a profile that cannot be honoured must fail here, with a reason,
rather than produce a form that renders half its fields and silently drops the
rest. The artist would find that out at the review, or never.

Rick's constraint (2026-09-14): "It shouldn't be saved without coherence."
"""

from __future__ import annotations

import pytest
from rdflib import Graph

from cwva_dashboard.profiles import (
    ProfileError,
    list_profiles,
    read_profile,
    shapes_graph,
)

PREFIXES = """@prefix vad:    <http://visualartsdna.org/model/> .
@prefix ops:    <http://visualartsdna.org/operations/> .
@prefix work:   <http://visualartsdna.org/work/> .
@prefix schema: <https://schema.org/> .
@prefix skos:   <http://www.w3.org/2004/02/skos/core#> .
@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#> .
@prefix rdf:    <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
"""

ARTIST = """
work:artist-1 a vad:Painter ;
    rdfs:label "Rick Spates" ;
    vad:brand "visualartsdna.org" .
"""

PROFILE = """
work:prof-1 a vad:ArtistProfile ;
    vad:artist work:artist-1 ;
    rdfs:label "Watercolor materials profile" ;
    schema:description "watercolours" ;
    skos:note "Assumptions for this profile" ;
    vad:measurementSystem [ a skos:Concept ; schema:unitCode "INH" ;
                            skos:note "Imperial and US customary" ] ;
    ops:template [
        rdfs:label "Input Form Spec" ;
        ops:templateType vad:Watercolor ;
        ops:field [ ops:property rdf:type          ; ops:order 2 ; ops:required true ] ;
        ops:field [ ops:property rdfs:label        ; ops:order 3 ; ops:required true ] ;
        ops:field [ ops:property schema:identifier ; ops:order 4 ; ops:required true ] ;
        ops:field [ ops:property vad:qrcode        ; ops:order 5 ; ops:required true ] ;
        ops:field [ ops:property schema:image      ; ops:order 6 ; ops:required true ] ;
    ] .
"""

URI = "http://visualartsdna.org/work/prof-1"


def g(*blocks) -> Graph:
    return Graph().parse(data=PREFIXES + "".join(blocks), format="turtle")


@pytest.fixture(scope="module")
def shapes():
    """The shipped shapes, not a copy: a test against its own shapes proves the
    test's shapes."""
    return shapes_graph()


def test_a_coherent_profile_reads(shapes):
    p = read_profile(g(ARTIST, PROFILE), URI, shapes=shapes)

    assert p.label == "Watercolor materials profile"
    assert p.template.type_default == "http://visualartsdna.org/model/Watercolor"
    assert [f.order for f in p.template.ordered()] == [2, 3, 4, 5, 6]


def test_the_units_come_from_the_MEASUREMENT_SYSTEM(shapes):
    """So "inches" is said once per profile instead of once per record — the one
    field this approach removes."""
    p = read_profile(g(ARTIST, PROFILE), URI, shapes=shapes)

    assert p.units == ("INH", "inches")


def test_the_brand_comes_from_the_ARTIST_not_the_profile(shapes):
    """One artist may hold several profiles and they all publish under the same
    signature, so the brand lives one hop away (CE_DESIGN §14.5)."""
    p = read_profile(g(ARTIST, PROFILE), URI, shapes=shapes)

    assert p.brand == "visualartsdna.org"
    assert p.artist_uri.endswith("artist-1")


def test_an_artist_who_declares_no_brand_is_not_an_error(shapes):
    """Absence is a decision: brand if the artist has one, otherwise do not."""
    plain = """
work:artist-1 a vad:Painter ; rdfs:label "Rick Spates" .
"""
    p = read_profile(g(plain, PROFILE), URI, shapes=shapes)

    assert p.brand == ""


# ---------------------------------------------------------------------------
# What SHACL refuses. Each of these would otherwise render a broken form.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("edit,expected", [
    ('rdfs:label "Watercolor materials profile" ;', "names the card"),
    ("vad:artist work:artist-1 ;", "exactly one artist"),
    ("ops:templateType vad:Watercolor ;", "exactly one ops:templateType"),
])
def test_a_profile_missing_an_essential_is_refused(edit, expected, shapes):
    broken = PROFILE.replace(edit, "")

    with pytest.raises(ProfileError, match=expected):
        read_profile(g(ARTIST, broken), URI, shapes=shapes)


def test_two_artists_on_one_profile_is_refused(shapes):
    """n:1, profile to artist (Rick's constraint) — two artists means no answer
    to "whose brand is this?"."""
    two = PROFILE.replace("vad:artist work:artist-1 ;",
                          "vad:artist work:artist-1, work:artist-2 ;")

    with pytest.raises(ProfileError, match="exactly one artist"):
        read_profile(g(ARTIST, two), URI, shapes=shapes)


def test_a_template_with_no_fields_describes_no_form(shapes):
    empty = PROFILE.split("ops:field")[0] + "] .\n"

    with pytest.raises(ProfileError, match="no ops:field"):
        read_profile(g(ARTIST, empty), URI, shapes=shapes)


def test_a_field_with_no_ORDER_is_refused(shapes):
    """Order is what makes the list a sequence. Without it the form's field
    order is whatever the parser returned — the exact failure per-field blank
    nodes exist to prevent."""
    no_order = PROFILE.replace("ops:property schema:image      ; ops:order 6 ;",
                               "ops:property schema:image      ;")

    with pytest.raises(ProfileError, match="ops:order"):
        read_profile(g(ARTIST, no_order), URI, shapes=shapes)


def test_a_bare_turtle_integer_IS_a_valid_order(shapes):
    """`ops:order 2` is an xsd:integer, not an xsd:int. A shape demanding
    xsd:int rejected every profile Rick had written."""
    p = read_profile(g(ARTIST, PROFILE), URI, shapes=shapes)

    assert p.template.ordered()[0].order == 2


def test_a_measurement_system_with_only_PROSE_is_refused(shapes):
    """The note is for a human. Without `schema:unitCode` the dashboard would
    have to read English to know what "measurements are in pixels" means."""
    prose = PROFILE.replace('schema:unitCode "INH" ;', "")

    with pytest.raises(ProfileError, match="unitCode"):
        read_profile(g(ARTIST, prose), URI, shapes=shapes)


def test_a_unit_code_the_dashboard_cannot_use_is_refused(shapes):
    """Structurally fine, semantically useless: every measurement on every
    record made from this profile would be labelled with nothing."""
    odd = PROFILE.replace('"INH"', '"FURLONG"')

    with pytest.raises(ProfileError, match="not one the dashboard knows"):
        read_profile(g(ARTIST, odd), URI, shapes=shapes)


# ---------------------------------------------------------------------------
# What the property map refuses — the checks SHACL cannot make.
# ---------------------------------------------------------------------------

def test_a_property_the_dashboard_cannot_RENDER_is_refused(shapes):
    """Law 3: a profile is stored data, stored data is hostile, and a template
    may order and select — never define."""
    rogue = PROFILE.replace(
        "ops:field [ ops:property schema:image      ; ops:order 6 ; ops:required true ] ;",
        "ops:field [ ops:property <http://evil.example/exec> ; ops:order 6 ] ;")

    with pytest.raises(ProfileError, match="cannot render"):
        read_profile(g(ARTIST, rogue), URI, shapes=shapes)


def test_two_fields_at_the_same_POSITION_are_refused(shapes):
    """Not a SHACL constraint — it is about siblings, not about a node — and
    worth its own message, because the form would order them arbitrarily."""
    clash = PROFILE.replace("ops:property schema:image      ; ops:order 6", 
                            "ops:property schema:image      ; ops:order 3")

    with pytest.raises(ProfileError, match="share an ops:order"):
        read_profile(g(ARTIST, clash), URI, shapes=shapes)


def test_a_dependency_on_a_property_the_template_LACKS_is_refused(shapes):
    """The guarded field could never be filled in: its trigger is not on the
    form at all."""
    dangling = PROFILE.replace(
        "ops:field [ ops:property schema:image      ; ops:order 6 ; ops:required true ] ;",
        "ops:field [ ops:property schema:image      ; ops:order 6 ; "
        "ops:dependsOn vad:image3d ] ;")

    with pytest.raises(ProfileError, match="does not include"):
        read_profile(g(ARTIST, dangling), URI, shapes=shapes)


def test_something_that_is_not_a_profile_at_all(shapes):
    with pytest.raises(ProfileError, match="not a vad:ArtistProfile"):
        read_profile(g(ARTIST, PROFILE), "http://visualartsdna.org/work/artist-1",
                     shapes=shapes)


# ---------------------------------------------------------------------------
# Listing: the cards, and what could not become one.
# ---------------------------------------------------------------------------

def test_listing_reports_the_BROKEN_ones_rather_than_hiding_them(shapes):
    """A profile that simply does not appear, with nothing said, looks exactly
    like a profile nobody created — and the one person who can fix it is the one
    looking at the screen."""
    second = PROFILE.replace("work:prof-1", "work:prof-2").replace(
        '"Watercolor materials profile"', '"Broken profile"').replace(
        "ops:templateType vad:Watercolor ;", "")

    good, broken = list_profiles(g(ARTIST, PROFILE, second), shapes=shapes)

    assert [p.label for p in good] == ["Watercolor materials profile"]
    assert len(broken) == 1
    assert broken[0]["label"] == "Broken profile"
    assert "templateType" in broken[0]["reason"]
    assert broken[0]["uri"].endswith("prof-2")


def test_one_profiles_problem_is_not_reported_on_ANOTHERS_card(shapes):
    """Validation is scoped to the profile being read; the store holds several."""
    second = PROFILE.replace("work:prof-1", "work:prof-2").replace(
        "ops:templateType vad:Watercolor ;", "")

    p = read_profile(g(ARTIST, PROFILE, second), URI, shapes=shapes)

    assert p.label == "Watercolor materials profile"


def test_the_cards_come_out_in_a_STABLE_order(shapes):
    second = PROFILE.replace("work:prof-1", "work:prof-2").replace(
        '"Watercolor materials profile"', '"Blender application profile"')

    good, _ = list_profiles(g(ARTIST, PROFILE, second), shapes=shapes)

    assert [p.label for p in good] == ["Blender application profile",
                                       "Watercolor materials profile"]


# ---------------------------------------------------------------------------
# The whole point: a profile becomes a form.
# ---------------------------------------------------------------------------

def test_a_profile_produces_a_FORM_through_the_property_map(shapes):
    """Reader plus map, end to end — the schema `validate_args` will enforce and
    the renderer will draw, from a record in the store."""
    from cwva_dashboard.tools.property_map import schema_from_template

    p = read_profile(g(ARTIST, PROFILE), URI, shapes=shapes)
    schema = schema_from_template(p.template, images_dir="content/images")

    # rdf:type and schema:image are fields; identifier and qrcode are derived
    # and stay in the TTL without appearing on the form (Rick, 2026-09-16).
    assert set(schema["properties"]) == {"type", "label", "image", "guid"}
    assert schema["additionalProperties"] is False


def test_a_profile_produces_the_RECORD_too(shapes):
    """The same template writes the triples, with the unit taken from the
    profile rather than asked for."""
    from cwva_dashboard.tools.property_map import graph_from_template
    from cwva_dashboard.tools.record_tools import (
        _expand, _prefixes, image_base, work_namespace)
    from conftest import TEST_DOMAIN

    p = read_profile(g(ARTIST, PROFILE), URI, shapes=shapes)
    ns = work_namespace(TEST_DOMAIN)
    out = graph_from_template(
        p.template, {"type": "Watercolor", "label": "A Work", "image": "a.jpg"},
        work_ns=ns, img_base=image_base(TEST_DOMAIN), guid="g1", units=p.units,
        expand=lambda c: _expand(c, _prefixes(ns)),
    )

    from rdflib.namespace import RDF
    from rdflib import Namespace
    VAD = Namespace("http://visualartsdna.org/model/")
    assert (ns["g1"], RDF.type, VAD.Watercolor) in out
    assert (ns["g1"], VAD.qrcode, None) in out, "derived, though never a field"
