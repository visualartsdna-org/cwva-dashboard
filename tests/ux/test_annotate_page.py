"""Annotate Work wired from function.html (Phase 4.7, cycle 5).

The user picks CONCEPTS, never properties. TCAP decides which typed property
each concept belongs on by walking to the most specific one the ontology allows
— that is the entire workflow, and a form offering `vad:hasWatercolorTechnique`
directly would be asking the user to do the navigation by hand and be right
about it.

So the page is two pickers and a result, and the result is the interesting part:
what was placed, what tied, what nothing accepted.
"""

from __future__ import annotations

import re
import shutil

import pytest
from fastapi.testclient import TestClient

from rdflib import Graph, URIRef

from conftest import TEST_DOMAIN
from cwva_dashboard.main import create_app
from cwva_dashboard.promotion.driver import PromotionDriver
from cwva_dashboard.promotion.layout import Layout
from cwva_dashboard.promotion.qa_git import QAGit
from cwva_dashboard.promotion.transports import FilesTransport
from cwva_dashboard.tools.record_tools import documents_base, image_base

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

# A miniature of the real shape: a property hierarchy TCAP can navigate, two
# schemes, and a work to annotate.
MODEL = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix vad: <http://visualartsdna.org/model/> .
# `vad:ArtForm` is the root the pickers ask about: what they offer is its
# downward closure, so a fixture without it offers nothing.
vad:ArtForm a owl:Class .
vad:PaintingForm a owl:Class ; rdfs:subClassOf vad:ArtForm .
vad:Watercolor a owl:Class ; rdfs:subClassOf vad:PaintingForm .
vad:hasTechnique a owl:ObjectProperty ;
    rdfs:domain vad:PaintingForm ; rdfs:range vad:Technique .
vad:hasWatercolorTechnique a owl:ObjectProperty ;
    rdfs:subPropertyOf vad:hasTechnique ;
    rdfs:domain vad:Watercolor ; rdfs:range vad:WatercolorTechnique .
vad:Technique a owl:Class .
vad:WatercolorTechnique a owl:Class ; rdfs:subClassOf vad:Technique .
"""

VOCAB = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix vad: <http://visualartsdna.org/model/> .
@prefix the: <http://visualartsdna.org/thesaurus/> .
the:WatercolorTechniqueScheme a skos:ConceptScheme ; rdfs:label "Watercolor Techniques" .
the:EmptyScheme a skos:ConceptScheme ; rdfs:label "Empty Scheme" .
the:wetInWet a skos:Concept , vad:WatercolorTechnique ;
    rdfs:label "wet in wet" ; skos:inScheme the:WatercolorTechniqueScheme .
the:drybrush a skos:Concept , vad:WatercolorTechnique ;
    rdfs:label "drybrush" ; skos:inScheme the:WatercolorTechniqueScheme .
"""

WORKS = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix the: <http://visualartsdna.org/thesaurus/> .
@prefix vad: <http://visualartsdna.org/model/> .
@prefix work: <http://visualartsdna.org/work/> .
work:w1 a vad:Watercolor ; rdfs:label "Spirited Tree" .
work:w2 a vad:Watercolor ; rdfs:label "Adelaide Sketch" .
work:e1 a the:Article ; rdfs:label "An Essay" ; skos:inScheme the:entities .
"""


@pytest.fixture
def client(tmp_path):
    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    qa = QAGit.init(qa_root)
    layout = Layout.default()
    for kind, text in (("model_ttl", MODEL), ("vocab_ttl", VOCAB), ("work_ttl", WORKS)):
        d = qa_root / layout.dir(kind)
        d.mkdir(parents=True, exist_ok=True)
        (d / "x.ttl").write_text(text)
    app = create_app(
        domain=TEST_DOMAIN, sandbox_root=qa_root, enforce_landlock=False,
        audit_path=tmp_path / "audit.jsonl",
        promotion_driver=PromotionDriver(
            qa, FilesTransport(tmp_path / "sot"), layout=layout,
            # ARM the asset gate too, as create_app does. A driver without
            # image_base runs no asset gate at all, so "gates passed" would mean
            # "no gates ran" — and the failed-gate test below would pass for the
            # wrong reason by never failing.
            image_base=image_base(TEST_DOMAIN),
            documents_base=documents_base(TEST_DOMAIN),
            vocab_dirs=[layout.dir("vocab_ttl"), layout.dir("tags_ttl")],
            content_dirs=[layout.dir("work_ttl")],
        ),
    )
    with TestClient(app) as c:
        yield c, qa


def _works(html):
    m = re.search(r'<select id="work" [^>]*>(.*?)</select>', html, re.S)
    return re.findall(r'<option value="([^"]+)"', m.group(1)) if m else []


def _selected(html):
    m = re.search(r'<option value="([^"]+)"[^>]*\sselected', html)
    return m.group(1) if m else ""


def _concepts_checked(html):
    return re.findall(r'name="concepts" value="([^"]+)" checked', html)


def _concepts(html):
    return re.findall(r'name="concepts" value="([^"]+)"', html)


def test_the_card_on_the_hub_now_resolves(client):
    c, _ = client
    hub = c.get("/").text

    assert 'href="annotate"' in hub
    assert "annotateWork.html" not in hub, "the legacy Groovy page must not linger"
    assert c.get("/annotate").status_code == 200


def test_only_WORKS_are_offered_not_entities(client):
    """A `vad:` type is what separates a work from an entity. Entities are
    annotated by the batch path (#15) from their queue tags, so offering them
    here would invite the user to do #15's job one record at a time."""
    c, _ = client
    offered = _works(c.get("/annotate").text)

    assert set(offered) == {"work:w1", "work:w2"}
    assert "work:e1" not in offered


def test_the_NEWEST_work_is_first_and_title_order_is_a_radio_away(client):
    """Rick, 2026-09-18: "99% of the time you want to annotate or edit a work
    just entered", and the date has to be one he can recognise — so it is
    `schema:datePublished`, shown beside the label. Alphabetical is one radio
    click, done in the browser so an unsubmitted concept selection is not lost
    to a round trip."""
    c, qa = client
    data = qa.root / Layout.default().dir("work_ttl")
    (data / "later.ttl").write_text(
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        "@prefix schema: <https://schema.org/> .\n"
        "@prefix vad: <http://visualartsdna.org/model/> .\n"
        "@prefix work: <http://visualartsdna.org/work/> .\n"
        'work:w9 a vad:Watercolor ; rdfs:label "Zebra, published last" ;\n'
        '    schema:datePublished "2026-09-17" .\n'
    )

    html = c.get("/annotate").text

    assert _works(html)[0] == "work:w9", "newest first, though Z sorts last"
    assert "2026-09-17" in html, "the date the order is by, on the option"
    # Both orders are in the markup: the radio reorders what is already there.
    assert re.search(r'<option value="work:w9"[^>]*data-d="0"', html)
    assert re.search(r'<option value="work:w9"[^>]*data-t="2"', html)
    assert 'name="workOrder" value="t"' in html


def test_every_scheme_with_concepts_is_offered(client):
    """The Groovy named six schemes in its source while the store holds 17. The
    other eleven were invisible with nothing saying so."""
    c, _ = client
    html = c.get("/annotate").text

    assert "Watercolor Techniques" in html
    assert set(_concepts(html)) == {"the:wetInWet", "the:drybrush"}
    assert "Empty Scheme" not in html, "a scheme with no concepts is not a choice"


def test_TCAP_places_the_most_specific_property(client):
    """The point of the workflow. `wet in wet` could sit on hasTechnique; the
    ontology allows hasWatercolorTechnique on a Watercolor, so that is where it
    goes."""
    c, qa = client
    r = c.post("/annotate", data={"work": "work:w1", "concepts": ["the:wetInWet"]})

    assert r.status_code == 200, r.text
    assert "hasWatercolorTechnique" in r.text
    ttl = (qa.root / "content/ttl/data/w1.ttl").read_text()
    assert "hasWatercolorTechnique" in ttl


def test_the_result_shows_what_was_placed(client):
    """The user picked concepts, not properties, so the placement IS the result.
    "1 file changed" would hide the entire content of the workflow."""
    c, _ = client
    r = c.post("/annotate", data={"work": "work:w1",
                                  "concepts": ["the:wetInWet", "the:drybrush"]})

    assert "What TCAP placed" in r.text
    assert "wetInWet" in r.text and "drybrush" in r.text


def test_it_stops_at_the_review_without_converging(client):
    c, qa = client
    r = c.post("/annotate", data={"work": "work:w1", "concepts": ["the:wetInWet"]})

    assert "Distribute Data — review" in r.text
    assert not list((qa.root.parent / "sot").rglob("*.ttl")), "must not converge"


def test_annotating_with_nothing_selected_is_refused(client):
    """Writing nothing and reporting success is the failure this workflow can
    most easily produce."""
    c, _ = client
    r = c.post("/annotate", data={"work": "work:w1"})

    assert r.status_code == 400
    assert "at least one concept" in r.text


def test_the_selection_survives_a_refusal(client):
    c, _ = client
    r = c.post("/annotate", data={"work": "work:w2", "concepts": []})

    assert _selected(r.text) == "work:w2"


def test_a_concept_no_property_accepts_is_reported_not_silent(client):
    """Nothing is written for it, and the page says so — otherwise a concept
    that quietly vanished looks identical to one that was placed."""
    c, _ = client
    # `the:drybrush` is fine; an unknown concept has no typed property at all.
    r = c.post("/annotate", data={"work": "work:w1",
                                  "concepts": ["the:drybrush", "the:nosuchconcept"]})

    assert r.status_code == 200
    assert "No typed property accepts" in r.text
    assert "nosuchconcept" in r.text


# -- which schemes to offer is CONFIGURED AS DATA (Rick, 2026-09-10) ----------
#
# An `the:Operation` record carrying BOTH `the:topic the:Thesaurus` and
# `the:topic the:Annotation` names the schemes to show, via `the:tag`. Neither
# topic is a single-purpose marker — both are ordinary topics a person would
# reach for on the Entity form — and it is carrying BOTH that means
# "dashboard / annotation". `the:Thesaurus` alone is worn by six Operations in
# the real store, so the pair does real discriminating work.
#
# It lives in the data rather than dashboard.rson because it is curation: it
# syncs between a workstation and a hosted instance, and it is editable through
# the Entity form. Config does neither.

CONFIG_TOPICS = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix the: <http://visualartsdna.org/thesaurus/> .
the:Thesaurus a skos:Concept ; rdfs:label "Thesaurus" ; skos:inScheme the:TopicScheme .
the:Annotation a skos:Concept ; rdfs:label "Annotation" ; skos:inScheme the:TopicScheme .
the:OtherScheme a skos:ConceptScheme ; rdfs:label "Other Scheme" .
the:somethingElse a skos:Concept ; rdfs:label "something else" ;
    skos:inScheme the:OtherScheme .
"""


def _config_record(topics: str, tags: str, label="Annotation Schemes") -> str:
    return (
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        "@prefix the: <http://visualartsdna.org/thesaurus/> .\n"
        "@prefix work: <http://visualartsdna.org/work/> .\n"
        f'work:cfg a the:Operation ; rdfs:label "{label}" ;\n'
        f"    the:topic {topics} ;\n    the:tag {tags} .\n"
    )


@pytest.fixture
def wider(client, tmp_path):
    """The fixture store plus a second scheme, so narrowing is observable."""
    c, qa = client
    (qa.root / Layout.default().dir("vocab_ttl") / "more.ttl").write_text(CONFIG_TOPICS)
    return c, qa


def _schemes_shown(html):
    return re.findall(r"<summary>([^<]+?)\s*<span", html)


def test_with_no_config_record_every_scheme_is_offered(wider):
    """Absence can never silently empty the picker: a fresh deployment needs no
    setup, and the record narrows rather than enables."""
    c, _qa = wider
    shown = _schemes_shown(c.get("/annotate").text)

    assert set(shown) == {"Watercolor Techniques", "Other Scheme"}


def test_a_config_record_narrows_the_picker(wider):
    c, qa = wider
    (qa.root / Layout.default().dir("work_ttl") / "cfg.ttl").write_text(
        _config_record("the:Thesaurus , the:Annotation", "the:WatercolorTechniqueScheme")
    )

    html = c.get("/annotate").text

    assert _schemes_shown(html) == ["Watercolor Techniques"]
    assert "Annotation Schemes" in html, "and the page names what narrowed it"


def test_the_TOPIC_PAIR_is_what_marks_it_not_either_topic_alone(wider):
    """Six Operations in the real store carry `the:Thesaurus` and are ordinary
    notes. If one topic were enough, every one of them would silently reconfigure
    the picker."""
    c, qa = wider
    (qa.root / Layout.default().dir("work_ttl") / "cfg.ttl").write_text(
        _config_record("the:Thesaurus", "the:WatercolorTechniqueScheme",
                       label="Ontology and Thesaurus Review")
    )

    shown = _schemes_shown(c.get("/annotate").text)

    assert set(shown) == {"Watercolor Techniques", "Other Scheme"}, "must not narrow"


def test_several_config_records_union_their_tags(wider):
    """Additive and deterministic. Picking "the most recent" would make the
    answer depend on a date nobody thinks of as load-bearing."""
    c, qa = wider
    data = qa.root / Layout.default().dir("work_ttl")
    (data / "cfg.ttl").write_text(
        _config_record("the:Thesaurus , the:Annotation", "the:WatercolorTechniqueScheme")
    )
    (data / "cfg2.ttl").write_text(
        _config_record("the:Thesaurus , the:Annotation", "the:OtherScheme",
                       label="Extra Schemes").replace("work:cfg", "work:cfg2")
    )

    html = c.get("/annotate").text

    assert set(_schemes_shown(html)) == {"Watercolor Techniques", "Other Scheme"}
    assert "Annotation Schemes" in html and "Extra Schemes" in html


def test_a_tag_that_is_not_a_scheme_is_ignored_and_SAID(wider):
    """`the:tag` is general-purpose, so a record may carry tags meaning other
    things. Silently treating one as a scheme would drop concepts with no
    explanation."""
    c, qa = wider
    (qa.root / Layout.default().dir("work_ttl") / "cfg.ttl").write_text(
        _config_record("the:Thesaurus , the:Annotation",
                       "the:WatercolorTechniqueScheme , the:wetInWet")
    )

    html = c.get("/annotate").text

    assert _schemes_shown(html) == ["Watercolor Techniques"]
    assert "Ignored" in html and "wetInWet" in html


# -- the way back from the review stop ---------------------------------------


def test_the_review_offers_a_way_back_to_the_ANNOTATION(client):
    """`Edit form` posts a promotion token and returns to the record form that
    minted a draft. An annotation came from no record form, so that door leads
    to a blank RDF Entry — it needs its own."""
    c, _ = client
    r = c.post("/annotate", data={"work": "work:w1", "concepts": ["the:wetInWet"]})

    assert "Back to annotation" in r.text
    assert "/rdf/entry/edit" not in r.text, "the record-form door is the wrong one here"


def test_going_back_restores_the_selection(client):
    """Otherwise the only way to drop one concept is the dashboard and start
    over — re-picking the work and every other concept by hand."""
    c, _ = client
    picks = ["the:wetInWet", "the:drybrush"]
    r = c.post("/annotate", data={"work": "work:w1", "concepts": picks})

    back = re.search(r'href="(/annotate\?[^"]+)"', r.text).group(1)
    html = c.get(back.replace("&amp;", "&")).text

    assert _selected(html) == "work:w1"
    for concept in picks:
        assert re.search(rf'value="{re.escape(concept)}" checked', html), concept


def test_a_FAILED_gate_is_not_a_dead_end(client, tmp_path):
    """It was: that branch rendered the gate list and nothing else, for every
    workflow. A review stop you can only leave by starting over is a wall."""
    c, qa = client
    # A dangling asset reference fails the asset gate.
    (qa.root / Layout.default().dir("work_ttl") / "x.ttl").write_text(
        WORKS + '\nwork:w1 <https://schema.org/image> '
        '<http://visualartsdna.org/images/missing.jpg> .\n'
    )

    r = c.post("/annotate", data={"work": "work:w1", "concepts": ["the:wetInWet"]})

    assert "Gates failed" in r.text
    assert "Back to annotation" in r.text
    assert "Discard changes" in r.text, "and the way to put the record back"


def test_a_concept_that_did_not_land_is_INFORMATION_not_a_failure(client):
    """Not every concept has a typed property, and requiring one would mean
    curating the whole thesaurus against the ontology before annotating
    anything. Saying which did not land is enough."""
    c, _ = client
    r = c.post("/annotate", data={"work": "work:w1",
                                  "concepts": ["the:wetInWet", "the:nosuchconcept"]})

    assert r.status_code == 200
    assert "hasWatercolorTechnique" in r.text, "the ones that landed still landed"
    assert "nosuchconcept" in r.text


def test_schemes_start_collapsed(client):
    """17 schemes and 780 concepts open at once is a page you scroll past rather
    than read. The filter box opens whatever matches, so nothing is hidden from
    someone looking for it."""
    c, _ = client
    html = c.get("/annotate").text

    assert '<details class="scheme">' in html
    assert '<details class="scheme" open>' not in html


def test_a_scheme_holding_a_SELECTION_starts_open(client):
    """Returning from the review stop restores a selection, and a selection you
    cannot see is worse than none: it reads as if the choice was lost."""
    c, _ = client
    html = c.get("/annotate?work=work:w1&concepts=the:wetInWet").text

    assert '<details class="scheme" open>' in html
    assert re.search(r'value="the:wetInWet" checked', html)


# -- Annotate Work EDITS an annotation (Rick, 2026-09-18) ---------------------
# "Opening an already annotated work … have the current annotations be
# reselected … upon Annotate only the currently selected concepts are applied.
# Any previous concepts that were not in the current selection are discarded."


def _annotated(c, qa, work="work:w1", concepts=("the:wetInWet", "the:drybrush")):
    """Put annotations on a work the way the page does, and return its graph."""
    c.post("/annotate", data={"work": work, "loaded_for": work,
                              "concepts": list(concepts)})
    guid = work.split(":", 1)[1]
    return qa.root / Layout.default().dir("work_ttl") / f"{guid}.ttl"


def test_an_annotated_work_opens_with_its_concepts_TICKED(client):
    """The page replaces on submit, so one that opened empty would be a Clear
    button wearing an Annotate label."""
    c, qa = client
    _annotated(c, qa)

    html = c.get("/annotate?work=work:w1").text

    assert re.search(r'value="the:wetInWet" checked', html)
    assert re.search(r'value="the:drybrush" checked', html)


def test_UNTICKING_one_discards_it_from_the_record(client):
    c, qa = client
    path = _annotated(c, qa)

    r = c.post("/annotate", data={"work": "work:w1", "loaded_for": "work:w1",
                                  "concepts": ["the:wetInWet"]})

    g = Graph().parse(data=path.read_text(), format="turtle")
    kept = set(g.objects(URIRef("http://visualartsdna.org/work/w1"), None))
    assert URIRef("http://visualartsdna.org/thesaurus/wetInWet") in kept
    assert URIRef("http://visualartsdna.org/thesaurus/drybrush") not in kept
    assert "discarded" in r.text, "the review says what unticking meant"


def test_a_work_with_NO_ANNOTATIONS_YET_still_opens_empty(client):
    c, _qa = client

    html = c.get("/annotate?work=work:w2").text

    # The order radio is checked; no CONCEPT is.
    assert not _concepts_checked(html)


def test_the_page_opens_on_the_FIRST_work_when_none_is_named(client):
    """Whatever the dropdown shows is what Annotate will rewrite, so the ticks
    have to belong to it."""
    c, qa = client
    _annotated(c, qa)

    html = c.get("/annotate").text
    first = _works(html)[0]

    assert _selected(html) == first
    if first == "work:w1":
        assert re.search(r'value="the:wetInWet" checked', html)


def test_CHANGING_THE_WORK_without_reloading_is_refused(client):
    """A dropdown changed with no JavaScript, or a tab left open, would write
    one work's concepts over another's and call it an edit."""
    c, qa = client
    _annotated(c, qa)

    r = c.post("/annotate", data={"work": "work:w2", "loaded_for": "work:w1",
                                  "concepts": ["the:wetInWet"]})

    assert r.status_code == 409
    assert "changed the work" in r.text
    w2 = qa.root / Layout.default().dir("work_ttl") / "w2.ttl"
    assert not w2.exists() or "wetInWet" not in w2.read_text()


def test_CLEARING_every_concept_is_allowed_on_an_annotated_work(client):
    """It is the only way to undo an annotation, and the review stop lists what
    it discarded before anything converges."""
    c, qa = client
    path = _annotated(c, qa)

    r = c.post("/annotate", data={"work": "work:w1", "loaded_for": "work:w1"})

    assert r.status_code == 200
    assert "discarded" in r.text
    assert "wetInWet" not in path.read_text()


def test_CLEARING_an_unannotated_work_is_still_refused(client):
    """The original trap: a submit that writes nothing and looks like it did."""
    c, _qa = client

    r = c.post("/annotate", data={"work": "work:w2", "loaded_for": "work:w2"})

    assert r.status_code == 400
    assert "at least one concept" in r.text


def test_the_picker_does_not_list_TYPES(client):
    """Rick, 2026-09-18: they read as if the store were inconsistent, because
    ten records carry materialized types and the rest do not. True, and nothing
    to do with choosing a work."""
    c, _qa = client

    html = c.get("/annotate").text
    options = re.findall(r"<option[^>]*>([^<]+)</option>", html)

    assert options
    assert not any("Watercolor" in o for o in options), options


def test_LEAVING_with_a_changed_selection_is_challenged(client):
    """"No challenge was presented even though I had made changes." The ticks
    are edits, and the page navigates away from them in three ways."""
    c, _qa = client

    html = c.get("/annotate?work=work:w1").text

    assert 'id="annotateForm"' in html
    assert "data-guard=" in html and "without annotating" in html
    assert "beforeunload" in html


def test_the_review_offers_DISCARD_and_challenges_a_departure(client):
    """Approve & distribute is the save. Leaving without it puts the record
    back, so the review offers that as an act and asks before a link takes you
    off the page (Rick, 2026-09-18: the old behaviour "is counterintuitive and
    no user will understand it")."""
    c, qa = client

    r = c.post("/annotate", data={"work": "work:w1", "loaded_for": "work:w1",
                                  "concepts": ["the:wetInWet"]})

    assert 'action="/episode/abandon"' in r.text
    assert "Discard changes" in r.text
    # The challenge on the way out INFORMS; it does not discard. Leaving by a
    # link made the batch workflow throw a record away (2026-09-27), so
    # abandoning is the button and nothing else.
    assert "stays as a draft" in r.text
    assert "nothing is saved until you approve" in r.text


# Rick's exact shape (2026-09-18): an Operation record narrows the picker to one
# scheme, and the work carries a concept from another one.
NARROWED = _config_record("the:Thesaurus , the:Annotation",
                          "the:WatercolorTechniqueScheme")

CARRIES_OUTSIDE = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix the: <http://visualartsdna.org/thesaurus/> .
@prefix vad: <http://visualartsdna.org/model/> .
@prefix work: <http://visualartsdna.org/work/> .
work:w1 a vad:Watercolor ; rdfs:label "Spirited Tree" ;
    vad:hasTechnique the:somethingElse .
"""


@pytest.fixture
def narrowed(wider):
    c, qa = wider
    data = qa.root / Layout.default().dir("work_ttl")
    (data / "cfg.ttl").write_text(NARROWED)
    # Into the record's OWN file — `<guid>.ttl` is what the annotator rewrites,
    # and Rick's record is one file holding everything.
    (data / "w1.ttl").write_text(CARRIES_OUTSIDE)
    return c, qa


def test_a_concept_the_picker_CANNOT_SHOW_survives_a_replacement(narrowed):
    """The bug that cost Rick a paper: his picker was narrowed to two schemes,
    `vad:hasPaper` pointed into a third, and replacement read "absent from the
    selection" as "the user removed it"."""
    c, qa = narrowed
    path = qa.root / Layout.default().dir("work_ttl") / "w1.ttl"
    assert "somethingElse" in path.read_text()

    c.post("/annotate", data={"work": "work:w1", "loaded_for": "work:w1",
                              "concepts": ["the:wetInWet"]})

    assert "somethingElse" in path.read_text(), "not offered, so not discardable"
    assert "wetInWet" in path.read_text(), "and the selection still applies"


def test_the_page_SAYS_what_it_is_not_showing(narrowed):
    """A concept on the record that the page does not show is exactly the thing
    a user goes hunting for later, after an annotation they never made
    disappears."""
    c, _qa = narrowed

    html = c.get("/annotate?work=work:w1").text

    assert "the:somethingElse" in html
    assert "Not shown, not changed" in html


def test_BACK_TO_ANNOTATION_is_not_a_way_out(client):
    """Rick, 2026-09-19: clicking it raised "Discard it and leave?" and then, on
    OK, discarded the work and landed on the Discarded page. Going back to the
    form to make further changes is the opposite of leaving, and the link that
    does it must not be treated as a departure."""
    c, _qa = client

    r = c.post("/annotate", data={"work": "work:w1", "loaded_for": "work:w1",
                                  "concepts": ["the:wetInWet"]})
    back = re.search(r'<a class="button"([^>]*)href="(/annotate\?[^"]+)"', r.text)

    assert back, "the way back is there"
    assert "data-keep" in back.group(1), "and the guard leaves it alone"


def test_BACK_TO_ANNOTATION_carries_the_selection_you_just_made(client):
    """"I would have expected to arrive back at the annotation page with the
    concept selection changes I had just made, in order to make further
    changes." """
    c, _qa = client

    r = c.post("/annotate", data={"work": "work:w1", "loaded_for": "work:w1",
                                  "concepts": ["the:wetInWet"]})
    back = re.search(r'href="(/annotate\?[^"]+)"', r.text).group(1)
    html = c.get(back.replace("&amp;", "&")).text

    assert _selected(html) == "work:w1"
    assert re.search(r'value="the:wetInWet" checked', html)


def test_the_DISCARD_BUTTON_asks_too(client):
    """It deletes files and cannot be undone. Leaving asked and the button did
    not, which reads as the button being the safer of the two."""
    c, _qa = client

    r = c.post("/annotate", data={"work": "work:w1", "loaded_for": "work:w1",
                                  "concepts": ["the:wetInWet"]})

    assert 'id="abandonForm"' in r.text
    assert "Discard the changes in this session?" in r.text


# -- two paints, one name -----------------------------------------------------

PAINTS = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix schema: <https://schema.org/> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix the: <http://visualartsdna.org/thesaurus/> .
the:PaintScheme a skos:ConceptScheme ; rdfs:label "Watercolor Paints" .
the:DavidDavis rdfs:label "David Davis" ; skos:altLabel "DD" .
the:Cornelissen rdfs:label "L. Cornelissen & Son" ; skos:altLabel "LCS" .
the:UltramarineDD a skos:Concept ; rdfs:label "Ultramarine" ;
    the:symbol "UBD" ; schema:brand the:DavidDavis ; skos:inScheme the:PaintScheme .
the:UltramarineLCS a skos:Concept ; rdfs:label "Ultramarine" ;
    the:symbol "UBL" ; schema:brand the:Cornelissen ; skos:inScheme the:PaintScheme .
the:TwoColorGrey1 a skos:Concept ; rdfs:label "Two-Color Grey 1" ;
    skos:inScheme the:PaintScheme .
"""


@pytest.fixture
def paints(client):
    c, qa = client
    (qa.root / Layout.default().dir("vocab_ttl") / "paints.ttl").write_text(PAINTS)
    return c


def _boxes(html):
    """checkbox value -> the words beside it."""
    return dict(re.findall(
        r'name="concepts" value="([^"]+)"[^>]*><span>([^<]*)</span>', html))


def test_paints_sharing_a_name_are_told_apart_by_brand(paints):
    boxes = _boxes(paints.get("/annotate").text)

    assert boxes["the:UltramarineDD"] == "Ultramarine (DD)"
    assert boxes["the:UltramarineLCS"] == "Ultramarine (LCS)"


def test_a_concept_with_no_brand_keeps_its_plain_label(paints):
    boxes = _boxes(paints.get("/annotate").text)

    assert boxes["the:TwoColorGrey1"] == "Two-Color Grey 1"
    assert boxes["the:wetInWet"] == "wet in wet"
