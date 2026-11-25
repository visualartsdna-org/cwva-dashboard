"""The DTS surface and its curation stops.

Two properties matter here beyond "the page renders". The queue page must
show every queue including the empty ones, because a queue that disappears
when it empties teaches you the list is a list of problems rather than a model
of the workflow. And every curation default must be overridable, because the
dashboard's findings are a reading and the curator's decision is the ruling.
"""

from __future__ import annotations

import json
import re
import shutil

import pytest
from fastapi.testclient import TestClient

from conftest import TEST_DOMAIN
from cwva_dashboard.inbox import Inbox
from cwva_dashboard.main import create_app
from cwva_dashboard.promotion.driver import PromotionDriver
from cwva_dashboard.promotion.layout import Layout
from cwva_dashboard.promotion.qa_git import QAGit
from cwva_dashboard.promotion.transports import FilesTransport
from cwva_dashboard.tools.record_tools import documents_base, image_base

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

THE = "http://visualartsdna.org/thesaurus/"
WORK = "http://visualartsdna.org/work/"

#: The concept the cached `duplicate` proposal collides with. It has to be IN
#: the store, because curation re-assesses against the store rather than
#: trusting what the model-time pass recorded — a duplicate test whose
#: counterpart does not exist tests nothing.
VOCAB = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix the: <http://visualartsdna.org/thesaurus/> .

the:Existing a skos:Concept ; rdfs:label "Existing concept" .
the:Parent a skos:Concept ; rdfs:label "Parent" ;
    skos:inScheme the:visualArtTerms .
"""

MODEL = """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix vad: <http://visualartsdna.org/model/> .
vad:ArtForm a owl:Class .
vad:Watercolor a owl:Class ; rdfs:subClassOf vad:ArtForm ; rdfs:label "Watercolor" .
"""

#: WORKS, so queue 0 has something to offer as the criticised work. The
#: fixture was entities-only, which is why the missing `the:tag` field went
#: unnoticed: with no works the dropdown is empty and the matcher finds
#: nothing either way.
#:
#: THREE, with deliberately awkward dates: the newest sorts first, the oldest
#: last, and the UNDATED one last of all however its label sorts. One work
#: cannot show an order, and two whose dates agree with their labels cannot
#: show which key was used.
WORK_RECORDS = {
    "w1": """work:w1 a vad:Watercolor ; rdfs:label "Fairy Pool" ;
    schema:datePublished "2026-05-01"^^xsd:date .
""",
    "w2": """work:w2 a vad:Watercolor ; rdfs:label "Aardvark" ;
    schema:datePublished "2026-09-20"^^xsd:date .
""",
    "w3": """work:w3 a vad:Watercolor ; rdfs:label "Bramble, undated" .
""",
}

# Three entities, one per stage, and **one file each** — which is how
# `record.new_entity` writes them and therefore what `expect_stage` reads
# before a curation writes anything. Bundling them into one file made the
# fixture convenient and the curation routes untestable (2026-10-01).
PREAMBLE = """@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix schema: <https://schema.org/> .
@prefix vad: <http://visualartsdna.org/model/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix the: <http://visualartsdna.org/thesaurus/> .
@prefix ops: <http://visualartsdna.org/operations/> .
@prefix work: <http://visualartsdna.org/work/> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

"""

ENTITIES = {
    "fresh": """work:fresh a the:AI ; rdfs:label "Fresh criticism" ;
    skos:inScheme the:entities ;
    the:mdDocument <http://visualartsdna.org/documents/Fresh.md> .
""",
    "derived": """work:derived a the:AI ; rdfs:label "Derived criticism" ;
    skos:inScheme the:entities ;
    the:mdDocument <http://visualartsdna.org/documents/Derived.md> ;
    ops:status [ rdfs:label "derived" ;
        ops:derived [ ops:at "2026-09-30T10:00:00+00:00"^^xsd:dateTime ] ] .
""",
    "done": """work:done a the:AI ; rdfs:label "Finished criticism" ;
    skos:inScheme the:entities ;
    the:mdDocument <http://visualartsdna.org/documents/Done.md> ;
    ops:status [ rdfs:label "summaryCurated" ;
        ops:derived [ ops:at "2026-09-30T10:00:00+00:00"^^xsd:dateTime ] ;
        ops:derivationCurated [ ops:at "2026-09-30T10:01:00+00:00"^^xsd:dateTime ] ;
        ops:tagged [ ops:at "2026-09-30T10:02:00+00:00"^^xsd:dateTime ] ;
        ops:taggingCurated [ ops:at "2026-09-30T10:03:00+00:00"^^xsd:dateTime ] ;
        ops:summarized [ ops:at "2026-09-30T10:04:00+00:00"^^xsd:dateTime ] ;
        ops:summaryCurated [ ops:at "2026-09-30T10:05:00+00:00"^^xsd:dateTime ] ] .
""",
}

PROPOSALS = {
    "entity": WORK + "derived",
    "document": "Derived.md",
    "model": "claude-sonnet-5",
    "input_tokens": 100,
    "output_tokens": 50,
    "proposals": [
        {"label": "Good term", "definition": "A reusable one.",
         "category": "formal", "alt_labels": [], "broader_label": "Parent",
         "broader_uri": "", "confidence": "high", "wikipedia_url": "",
         "close_match_url": "", "scope_note": "",
         "grounding_phrase": "the critic wrote this", "grounded": True,
         "duplicate_of": "", "duplicate_label": "", "duplicate_score": 0.0,
         "near": [], "orphan": False, "reference_fits": True,
         "reference_title": "", "source_speaker": "critic",
         "status": "proposed", "notes": []},
        {"label": "Existing concept", "definition": "A duplicate.",
         "category": "formal", "alt_labels": [], "broader_label": "Parent",
         "broader_uri": "", "confidence": "high", "wikipedia_url": "",
         "close_match_url": "", "scope_note": "",
         "grounding_phrase": "the critic wrote this", "grounded": True,
         "duplicate_of": THE + "Existing", "duplicate_label": "Existing concept",
         "duplicate_score": 0.95, "near": [], "orphan": False,
         "reference_fits": True, "reference_title": "",
         "source_speaker": "critic", "status": "duplicate",
         "notes": ["the store already has 'Existing concept' at 0.95"]},
        {"label": "Your phrase", "definition": "From the artist's turn.",
         "category": "contextual", "alt_labels": [], "broader_label": "Parent",
         "broader_uri": "", "confidence": "high", "wikipedia_url": "",
         "close_match_url": "", "scope_note": "",
         "grounding_phrase": "I said this", "grounded": True,
         "duplicate_of": "", "duplicate_label": "", "duplicate_score": 0.0,
         "near": [], "orphan": False, "reference_fits": True,
         "reference_title": "", "source_speaker": "user",
         "status": "user_sourced", "notes": []},
    ],
}


#: A concept the store gains AFTER the model answered. Written into the vocab
#: directory by the test that needs it, because the point is that the store
#: moves between derive and curate.
LATER = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix the: <http://visualartsdna.org/thesaurus/> .

the:GoodTerm a skos:Concept ; rdfs:label "Good term" .
"""


@pytest.fixture
def client(tmp_path):
    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    qa = QAGit.init(qa_root)
    layout = Layout.default()
    model_dir = qa_root / layout.dir("model_ttl")
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "tiny.ttl").write_text(MODEL)
    data = qa_root / layout.dir("work_ttl")
    data.mkdir(parents=True, exist_ok=True)
    for guid, body in ENTITIES.items():
        (data / f"{guid}.ttl").write_text(PREAMBLE + body)
    for guid, body in WORK_RECORDS.items():
        (data / f"{guid}.ttl").write_text(PREAMBLE + body)
    vocab = qa_root / layout.dir("vocab_ttl")
    vocab.mkdir(parents=True, exist_ok=True)
    (vocab / "vocab.ttl").write_text(VOCAB)
    (qa_root / layout.dir("document")).mkdir(parents=True, exist_ok=True)
    cache = qa_root / ".qa" / "dts" / "derived"
    cache.mkdir(parents=True)
    (cache / "derive.json").write_text(json.dumps(PROPOSALS))

    # FLAT, like the real drop folder: kind is decided by extension, not by a
    # subdirectory (`~/cwva-py/stage/data` holds .md, .jpg and .pdf together).
    drop = tmp_path / "drop"
    drop.mkdir()
    (drop / "Waiting.md").write_text(
        "# A painting review\n\n## User:\n\nProvide an art criticism of this "
        "watercolor.\n\n## Assistant:\n\nThe wash carries it.\n")
    app = create_app(
        domain=TEST_DOMAIN, sandbox_root=qa_root, enforce_landlock=False,
        audit_path=tmp_path / "audit.jsonl",
        inbox=Inbox(drop),
        promotion_driver=PromotionDriver(
            qa, FilesTransport(tmp_path / "sot"), layout=layout,
            image_base=image_base(TEST_DOMAIN),
            documents_base=documents_base(TEST_DOMAIN)),
    )
    with TestClient(app) as c:
        yield c, qa_root


#: Everything the fixture wrote, so a test looking for "the record that was
#: just generated" does not have to list them again every time one is added.
FIXTURE_FILES = ({f"{g}.ttl" for g in ENTITIES}
                 | {f"{g}.ttl" for g in WORK_RECORDS})


def _queues(html):
    return {m[1]: int(m[0]) for m in re.findall(
        r'<summary><span class="n">(\d+)</span><span>([^<]+)</span>', html)}


# -- the surface -------------------------------------------------------------


def test_the_hub_card_resolves(client):
    c, _ = client

    assert 'href="dts"' in c.get("/").text
    assert c.get("/dts").status_code == 200


def test_every_queue_is_shown_INCLUDING_the_empty_ones(client):
    """A queue that disappears when it empties teaches you the list is a list
    of problems rather than a model of the workflow."""
    c, _ = client

    queues = _queues(c.get("/dts").text)

    assert set(queues) == {
        "Documents to process", "Pending derivation",
        "Pending derivation curation", "Pending tagging",
        "Pending tagging curation", "Pending summarization",
        "Pending summary curation"}


def test_an_entity_appears_in_the_queue_its_STAMPS_put_it_in(client):
    c, _ = client

    queues = _queues(c.get("/dts").text)

    assert queues["Pending derivation"] == 1
    assert queues["Pending derivation curation"] == 1


def test_a_COMPLETE_entity_is_in_no_queue(client):
    c, _ = client
    html = c.get("/dts").text

    assert sum(v for k, v in _queues(html).items()
               if k != "Documents to process") == 2
    assert "Finished criticism" not in html


def test_each_queue_states_its_RULE(client):
    """The rule is the thing that makes a count trustworthy."""
    c, _ = client
    html = c.get("/dts").text

    assert "derived, not curated" in html
    assert "tagging curated, not summarized" in html


# -- the curation stop -------------------------------------------------------


def test_the_entity_door_opens_the_screen_its_STATE_calls_for(client):
    """One door per entity rather than one per stage, so a stale link cannot
    run the wrong step."""
    c, _ = client

    html = c.get("/dts/entity?guid=derived").text

    assert "Curate derivation" in html
    assert "Good term" in html and "Existing concept" in html


def test_a_DUPLICATE_defaults_to_reject_and_says_why(client):
    c, _ = client
    html = c.get("/dts/entity?guid=derived").text
    block = html[html.index("Existing concept"):html.index("Your phrase")]

    assert 'value="reject" checked' in block
    assert "the store already has" in block


def test_a_proposal_from_the_ARTISTS_words_defaults_to_reject(client):
    c, _ = client
    html = c.get("/dts/entity?guid=derived").text
    block = html[html.index("Your phrase"):]

    assert 'value="reject" checked' in block
    assert "your own turn" in block or "your words" in block


def test_a_clean_proposal_defaults_to_KEEP(client):
    c, _ = client
    html = c.get("/dts/entity?guid=derived").text
    block = html[html.index("Good term"):html.index("Existing concept")]

    assert 'value="keep" checked' in block


def test_every_default_is_OVERRIDABLE(client):
    """The findings are a reading, not a ruling: all three answers are
    offered on every proposal."""
    c, _ = client
    html = c.get("/dts/entity?guid=derived").text

    for label in ("Good term", "Existing concept", "Your phrase"):
        start = html.index(label)
        block = html[start:start + 2000]
        assert 'value="keep"' in block and 'value="reject"' in block


def test_a_duplicate_offers_DEMOTION_to_what_it_duplicates(client):
    """The third answer, offered only where there is something to demote
    onto — a demotion with no target is a wish, not a decision."""
    c, _ = client
    html = c.get("/dts/entity?guid=derived").text
    block = html[html.index("Existing concept"):html.index("Your phrase")]

    assert 'value="demote"' in block
    assert "altLabel of Existing concept" in block


def test_a_proposal_with_NOTHING_NEAR_offers_no_demotion(client):
    c, _ = client
    html = c.get("/dts/entity?guid=derived").text
    block = html[html.index("Good term"):html.index("Existing concept")]

    assert 'value="demote"' not in block


def test_an_unknown_entity_is_a_404_not_a_crash(client):
    c, _ = client

    assert c.get("/dts/entity?guid=nope").status_code == 404


def test_a_complete_entity_is_sent_BACK_to_the_queues(client):
    c, _ = client

    r = c.get("/dts/entity?guid=done", follow_redirects=False)

    assert r.status_code == 303 and r.headers["location"].startswith("/dts")


# -- the sentences around the phrase, on the screen --------------------------


def test_the_curation_screen_shows_the_SURROUNDING_SENTENCES(client):
    """A phrase alone cannot show a negation: `Color symbolism` was proposed on
    "simple symbolic diagram", which is in the document inside "Yet the effect
    avoids becoming a simple symbolic diagram"."""
    c, qa_root = client
    doc = qa_root / "content" / "documents" / "Derived.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("## Assistant:\n\nThe polarity is bodily. Yet the effect "
                   "avoids becoming the critic wrote this because the figures "
                   "cross it. A third sentence.\n")

    html = c.get("/dts/entity?guid=derived").text

    assert "avoids becoming" in html, "the negation is on the screen"
    assert "<mark>the critic wrote this</mark>" in html, "and the phrase is marked"


def test_a_MISSING_document_costs_the_context_and_nothing_else(client):
    """It can legitimately be absent — deleted, not yet synced, renamed — and a
    screen that refused to open would strip the curator of decisions that are
    perfectly judgeable without the prose."""
    c, qa_root = client
    assert not (qa_root / "content" / "documents" / "Derived.md").exists()

    r = c.get("/dts/entity?guid=derived")

    assert r.status_code == 200
    assert "Good term" in r.text and 'value="keep" checked' in r.text


# -- the store moves between derive and curate -------------------------------
#
# Rick curated one Three Graces document, which minted `the:ThreeGraces`. The
# other document's proposal for the same concept was still marked `proposed`
# from derive time, so submitting it hit the mint-collision guard — and the
# guard raised a StageError no route handled, which arrived as an Internal
# Server Error (2026-10-01).


def _vocab(qa_root):
    d = qa_root / Layout.default().dir("vocab_ttl")
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_the_curation_form_RE_ASSESSES_against_the_store_as_it_is_now(client):
    """A concept minted since the model answered is a duplicate now, whatever
    the cached proposal says."""
    c, qa_root = client
    (_vocab(qa_root) / "later.ttl").write_text(LATER)

    html = c.get("/dts/entity?guid=derived").text
    block = html[html.index(">Good term"):]

    assert "(duplicate)" in block[:400]
    assert 'value="reject" checked' in block[:2000], "and defaults to reject"


def test_curating_a_concept_that_became_a_DUPLICATE_is_a_message_not_a_500(client):
    """The guard is right; a 500 is not how it should speak."""
    c, qa_root = client
    (_vocab(qa_root) / "later.ttl").write_text(LATER)

    r = c.post("/dts/curate/derive",
               data={"guid": "derived", "choice:Good term": "keep",
                     "choice:Existing concept": "reject",
                     "choice:Your phrase": "reject"},
               follow_redirects=False)

    assert r.status_code == 400
    assert "already exists" in r.text
    assert "Good term" in r.text, "and the form comes back with the proposals"


def test_a_clean_curation_still_SUCCEEDS(client):
    c, _qa_root = client

    r = c.post("/dts/curate/derive",
               data={"guid": "derived", "choice:Good term": "keep",
                     "choice:Existing concept": "reject",
                     "choice:Your phrase": "reject"},
               follow_redirects=False)

    import re as _re
    msg = _re.search(r'<div class="err">([^<]*)</div>', r.text)
    assert r.status_code == 303, msg.group(1) if msg else r.text[:400]
    assert r.headers["location"].startswith("/dts?notice=")


def test_a_duplicate_says_where_the_evidence_BELONGS(client):
    """Rejecting it is not a loss, and the screen should say so rather than
    leaving a curator to wonder what happened to the phrase (Rick,
    2026-10-01): a subsequent use of a concept shows up in tagging, where it
    gets its own grounding on the document."""
    c, qa_root = client
    (_vocab(qa_root) / "later.ttl").write_text(LATER)

    html = c.get("/dts/entity?guid=derived").text

    assert "belongs in tagging" in html


# -- queue 0: generate the entity the document implies ------------------------


def test_a_waiting_document_offers_to_GENERATE_its_entity(client):
    """Rick, 2026-10-01: the entity is derivable from the document, so the step
    is a button rather than a form to retype."""
    c, _qa_root = client

    html = c.get("/dts").text

    assert "Waiting.md" in html
    assert 'name="doc" value="Waiting.md"' in html
    assert "Generate entity" in html


def test_generating_lands_in_the_EDITOR_for_review(client):
    """"The document can then be reviewed and edited as needed" — so it opens
    in Edit Record, which opens entities."""
    c, _qa_root = client

    r = c.post("/dts/entity/new", data={"doc": "Waiting.md"},
               follow_redirects=False)

    assert r.status_code == 303
    assert r.headers["location"].startswith("/edit/open?path=")
    assert "kind=entity" in r.headers["location"]


def test_the_generated_entity_carries_what_was_DERIVED(client):
    c, qa_root = client

    c.post("/dts/entity/new", data={"doc": "Waiting.md"}, follow_redirects=False)

    written = list((qa_root / Layout.default().dir("work_ttl")).glob("*.ttl"))
    body = "\n".join(f.read_text() for f in written)
    assert "the:Criticism" in body
    assert "Provide an art criticism" in body, "the definition"
    assert "Generated from Waiting.md" in body, "and why, on the record"


def test_it_leaves_QUEUE_0_once_it_HAS_an_entity(client):
    """The filename stays on the page — as the new entity's document, in
    "pending derivation" — so what has to go is the OFFER to generate it."""
    c, _qa_root = client
    assert 'name="doc" value="Waiting.md"' in c.get("/dts").text

    c.post("/dts/entity/new", data={"doc": "Waiting.md"}, follow_redirects=False)
    html = c.get("/dts").text

    assert 'name="doc" value="Waiting.md"' not in html, "no longer offered"
    assert "Waiting.md" in html, "but listed as the entity's document"


def test_a_document_that_is_not_waiting_is_refused(client):
    c, _qa_root = client

    r = c.post("/dts/entity/new", data={"doc": "Nothing.md"},
               follow_redirects=False)

    assert r.status_code == 404
    assert "not a document waiting" in r.text


def test_a_document_with_no_human_turn_is_sent_to_the_ENTITY_FORM(client):
    """It cannot describe itself, and an entity with an empty definition is
    worse than none."""
    c, _qa_root = client
    import pathlib as _p
    (_p.Path(c.app.state.inbox.root) / "Prose.md").write_text(
        "# Just prose, no turns at all.\n")

    r = c.post("/dts/entity/new", data={"doc": "Prose.md"},
               follow_redirects=False)

    assert r.status_code == 400
    assert "no human turn" in r.text and "Entity form" in r.text



# -- queue 0 offers the work, because the editor cannot add a predicate ------
#
# Rick, 2026-10-01: "It said to add the:tag IRI in edit. I'm in the edit screen
# for the entity and there is no the:tag property field." Edit Record renders
# one field per predicate IN THE FILE, so a record created without `the:tag`
# has no field in which to add one — and the derivation note was telling him to
# do exactly that. Adding a predicate from the type's domain is a deferred Edit
# Record item, so the place to answer is before the record exists.


def test_queue_0_OFFERS_the_work(client):
    c, _ = client

    html = c.get("/dts").text

    assert 'name="work"' in html, "the work is offered, not only derived"
    assert "Fairy Pool" in html


def test_the_default_is_still_to_DERIVE_it(client):
    """The matcher is right when the document names its subject in a heading,
    so the picker is the override and the fallback, never a required field."""
    c, _ = client

    html = c.get("/dts").text

    assert '<option value="">' in html
    assert "derive the work from the document" in html


def test_the_options_are_the_SAME_SET_the_matcher_searches(client):
    """What the page offers is what the matcher could have found. A picker over
    a different set would let a criticism be tagged onto something the matcher
    would never have proposed."""
    c, _ = client

    html = c.get("/dts").text
    picker = re.findall(r'<select name="work".*?</select>', html, re.S)[0]
    offered = set(re.findall(r'<option value="(http[^"]*)"', picker))

    assert offered == {WORK + g for g in WORK_RECORDS}, "the works, and nothing else"


def test_a_NAMED_work_is_written_as_the_tag(client):
    c, qa_root = client

    c.post("/dts/entity/new", data={"doc": "Waiting.md", "work": WORK + "w1"},
           follow_redirects=False)

    data = qa_root / Layout.default().dir("work_ttl")
    body = "\n".join(f.read_text() for f in data.glob("*.ttl")
                     if f.name not in FIXTURE_FILES)
    assert "w1" in body, "the work reference the editor could not have added"


def test_a_named_work_CORRECTS_the_derivation_note(client):
    """The record's `skos:note` is built from the proposal's evidence, so
    leaving "no work matched" on a record that HAS one would make the record
    lie about itself tomorrow."""
    c, qa_root = client

    c.post("/dts/entity/new", data={"doc": "Waiting.md", "work": WORK + "w1"},
           follow_redirects=False)

    data = qa_root / Layout.default().dir("work_ttl")
    body = "\n".join(f.read_text() for f in data.glob("*.ttl")
                     if f.name not in FIXTURE_FILES)
    assert "no work matched" not in body
    assert "named on the generate card" in body


def test_a_named_work_is_the_one_the_LABEL_names(client):
    """Chania Harbor's criticism was tagged to Chania Harbor and labelled
    "Sunlit Pines Criticism chatGpt": a heading resembled that work, the card's
    choice replaced the tag, and the label kept the guess (2026-11-24)."""
    c, qa_root = client
    (qa_root.parent / "drop" / "Misleading.md").write_text(
        "# Aardvark study\n\n## User:\n\nProvide an art criticism of this "
        "watercolor.\n\n## Assistant:\n\nThe wash carries it.\n")

    c.post("/dts/entity/new", data={"doc": "Misleading.md", "work": WORK + "w1"},
           follow_redirects=False)

    data = qa_root / Layout.default().dir("work_ttl")
    body = "\n".join(f.read_text() for f in data.glob("*.ttl")
                     if f.name not in FIXTURE_FILES)
    assert 'rdfs:label "Fairy Pool Criticism' in body
    assert "Aardvark Criticism" not in body


def test_an_UNKNOWN_work_is_refused(client):
    """A work IRI arriving in a POST is a value from the page, not a fact, so
    it is checked against the same set that was offered."""
    c, _ = client

    r = c.post("/dts/entity/new",
               data={"doc": "Waiting.md", "work": "http://evil/not-a-work"},
               follow_redirects=False)

    assert r.status_code == 400
    assert "is not a work in this store" in r.text


def test_naming_NO_work_still_generates(client):
    """The picker is optional; the matcher's answer, or none, still stands."""
    c, _ = client

    r = c.post("/dts/entity/new", data={"doc": "Waiting.md", "work": ""},
               follow_redirects=False)

    assert r.status_code == 303


# -- the editor's group comes from the RECORD, not the URL -------------------
#
# Rick, 2026-10-01: "the Works/Entities radio buttons had Works selected. I then
# hit Open with the new entity showing and it brought up the entity for
# Pillars." The Drafts page links to `/edit/open?path=…` with no `kind`, which
# read as the default group — so an entity was shown over the WORKS dropdown,
# the record was absent from the list it was being shown against, and the
# browser displayed its first option instead. Open then navigated there.


def _tab_on(html):
    return {m[2] for m in re.findall(
        r'<a class="tab( on)?" href="([^"]+)"[^>]*>([^<]+)</a>', html) if m[0]}


def test_opening_an_entity_with_NO_kind_lands_on_ENTITIES(client):
    """The URL the Drafts page actually produces."""
    c, _ = client

    html = c.get("/edit/open?path=content/ttl/data/derived.ttl").text

    assert _tab_on(html) == {"Entities"}


def test_opening_a_WORK_with_no_kind_lands_on_WORKS(client):
    c, _ = client

    html = c.get("/edit/open?path=content/ttl/data/w1.ttl").text

    assert _tab_on(html) == {"Works"}


def test_a_WRONG_kind_in_the_url_does_not_win(client):
    """`?kind=` is a hint anyone can type. The record knows which list it is
    in, so a stale link or a hand-edited URL cannot misfile it."""
    c, _ = client

    html = c.get("/edit/open?path=content/ttl/data/derived.ttl&kind=work").text

    assert _tab_on(html) == {"Entities"}


def test_the_record_ON_SCREEN_is_the_one_SELECTED_in_the_dropdown(client):
    """The dangerous half, and the reason the group matters at all: an option
    list that does not contain the record being edited shows its first entry
    instead, so Open navigates somewhere else while looking like it reopens
    this one."""
    c, _ = client
    path = "content/ttl/data/derived.ttl"

    html = c.get(f"/edit/open?path={path}&kind=work").text
    selected = re.findall(r'<option value="([^"]*)"[^>]*selected', html)

    assert path in selected, "the record being edited is the selected option"


def test_the_hidden_kind_matches_the_record_so_OPEN_round_trips(client):
    """Open submits the dropdown plus this hidden field; a wrong one sends you
    to a record from the other group."""
    c, _ = client

    html = c.get("/edit/open?path=content/ttl/data/derived.ttl&kind=work").text

    assert set(re.findall(r'name="kind" value="([^"]*)"', html)) == {"entity"}


def test_the_works_are_offered_NEWEST_FIRST(client):
    """Rick, 2026-10-01: "derive the work from the document should be in
    descending chronological order." A criticism is written about a work while
    it is still the one you were working on — the same reason the Edit Record
    picker defaults to date order, and the same key, so the two cannot drift.
    """
    c, _ = client

    picker = re.findall(r'<select name="work".*?</select>',
                        c.get("/dts").text, re.S)[0]
    offered = re.findall(r'<option value="(?:http[^"]*)"[^>]*>([^&<]*)', picker)

    assert [s.strip() for s in offered] == ["Aardvark", "Fairy Pool",
                                            "Bramble, undated"]


def test_an_UNDATED_work_sorts_LAST_not_first(client):
    """An empty date string sorts before every real one lexicographically, so
    the key has to say "undated last" explicitly. A work with no date is one
    that has not been published, which is exactly what no date means."""
    c, _ = client

    picker = re.findall(r'<select name="work".*?</select>',
                        c.get("/dts").text, re.S)[0]
    offered = re.findall(r'<option value="(?:http[^"]*)"[^>]*>([^&<]*)', picker)

    assert [s.strip() for s in offered][-1] == "Bramble, undated"


def test_the_DATE_is_shown_beside_each_work(client):
    """An order you cannot see is one you have to trust — the reason the Edit
    Record picker shows it too."""
    c, _ = client

    picker = re.findall(r'<select name="work".*?</select>',
                        c.get("/dts").text, re.S)[0]

    assert "Aardvark &mdash; 2026-09-20" in picker
    assert "Bramble, undated</option>" in picker, "and nothing where there is no date"


def test_the_DERIVE_option_stays_FIRST(client):
    """Ordering the works must not push the default past them."""
    c, _ = client

    picker = re.findall(r'<select name="work".*?</select>',
                        c.get("/dts").text, re.S)[0]

    assert picker.index('value=""') < picker.index(f'value="{WORK}')

