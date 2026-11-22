"""Form wording comes from the ONTOLOGY, resolved per render.

`rdfs:label` captions the field, `rdfs:comment` explains it underneath. The
point is not that the model's wording is ideal for a form — it is that changing
the model changes the form, with no code edit and no restart. So the test that
carries this file is `test_editing_the_model_changes_the_form`; the rest pin
the details around it.
"""

from __future__ import annotations

import re
import shutil

import pytest
from fastapi.testclient import TestClient

from cwva_dashboard.inbox import Inbox
from cwva_dashboard.main import create_app
from cwva_dashboard.promotion.qa_git import QAGit
from cwva_dashboard.tools.record_tools import WORK_FIELD_PROPERTIES

from conftest import TEST_DOMAIN

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

MODEL = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix vad: <http://visualartsdna.org/model/> .
@prefix schema: <https://schema.org/> .
vad:PaintingForm a owl:Class .
vad:Watercolor a owl:Class ; rdfs:subClassOf vad:PaintingForm .
schema:identifier rdfs:label "%s" ; rdfs:comment "%s" .
schema:height rdfs:label "height" .
"""


@pytest.fixture
def env(tmp_path):
    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    QAGit.init(qa_root)
    model = qa_root / "metacontent" / "model"
    model.mkdir(parents=True)
    (model / "m.ttl").write_text(MODEL % ("identifier", "A GUID"))
    drop = tmp_path / "drop"
    drop.mkdir()
    app = create_app(
        domain=TEST_DOMAIN,
        sandbox_root=qa_root, enforce_landlock=False,
        audit_path=tmp_path / "a.jsonl", inbox=Inbox(drop),
    )
    with TestClient(app) as c:
        yield c, model / "m.ttl"


def _caption(html: str, field: str) -> str:
    m = re.search(rf'<label for="{field}">(.*?)</label>', html, re.S)
    return re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else ""


def _comment(html: str, field: str) -> str:
    block = re.search(
        rf'<label for="{field}">.*?(?=<div class="field|</form>)', html, re.S
    )
    if not block:
        return ""
    hint = re.search(r'<div class="hint">(.*?)</div>', block.group(0), re.S)
    return hint.group(1).strip() if hint else ""


def test_label_and_comment_come_from_the_model(env):
    c, _ = env
    html = c.get("/rdf/entry").text
    assert _caption(html, "guid") == "identifier"
    assert _comment(html, "guid") == "A GUID"


def test_editing_the_model_changes_the_form_without_a_restart(env):
    """The whole point. The ontology is re-read per render, so a term edited in
    the model is reflected on the next page load — no restart, no code change."""
    c, model_file = env
    assert _caption(c.get("/rdf/entry").text, "guid") == "identifier"

    model_file.write_text(MODEL % ("work number", "The catalogue number."))

    html = c.get("/rdf/entry").text
    assert _caption(html, "guid") == "work number"
    assert _comment(html, "guid") == "The catalogue number."


def test_a_property_with_no_comment_renders_no_hint(env):
    """Absence is normal — `height` has no rdfs:comment — and must not leave an
    empty help line under the field."""
    c, _ = env
    html = c.get("/rdf/entry").text
    assert _caption(html, "height").rstrip(" *") == "height"
    assert _comment(html, "height") == "", "no comment must mean no hint line"


def test_an_unmodelled_field_falls_back_to_its_name(env):
    """A field the ontology says nothing about is still labelled."""
    c, _ = env
    html = c.get("/rdf/entry").text
    assert _caption(html, "location") == "location"


def test_required_fields_keep_the_asterisk(env):
    c, _ = env
    html = c.get("/rdf/entry").text
    schema = next(
        s for s in c.get("/api/tools").json() if s["name"] == "record.new_work"
    )
    required = schema["inputSchema"].get("required", [])
    assert "label" in required
    for name in required:
        assert _caption(html, name).endswith("*"), name
    assert not _caption(html, "location").endswith("*"), "optional field"


def test_the_legend_explains_the_asterisk(env):
    c, _ = env
    html = c.get("/rdf/entry").text
    assert re.search(r'class="legend".*?required', html, re.S)
    assert "rdfs:label" in html and "rdfs:comment" in html


def test_every_mapped_field_names_a_real_property():
    """The map mirrors what `_new_work` writes; a bare name would silently
    resolve to nothing and the field would lose its caption."""
    for field, uri in WORK_FIELD_PROPERTIES.items():
        assert uri.startswith("http"), f"{field} -> {uri}"


# -- date display format ------------------------------------------------------


def _render(date_format="", **kw):
    from cwva_dashboard.tools.fileops_tools import build_default_registry
    from cwva_dashboard.ux.affordance import resolve_field_terms
    from cwva_dashboard.tools.record_tools import WORK_FIELD_PROPERTIES
    from cwva_dashboard.ux.forms import render_entry_form
    from rdflib import Graph

    model = Graph()
    model.parse(data=(
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        "@prefix schema: <https://schema.org/> .\n"
        'schema:dateCreated rdfs:label "created date" ;\n'
        '  rdfs:comment "The date the work was completed." .\n'
        'schema:datePublished rdfs:label "published date" .\n'
    ), format="turtle")
    schema = next(
        s for s in build_default_registry(domain=TEST_DOMAIN).schemas() if s["name"] == "record.new_work"
    )
    return render_entry_form(
        schema, guid="g1", date_format=date_format,
        terms=resolve_field_terms(model, WORK_FIELD_PROPERTIES), **kw
    )


def _hint(html: str, field: str) -> str:
    import html as H

    block = re.search(
        rf'<label for="{field}">.*?(?=<div class="field|</form>)', html, re.S
    )
    m = re.search(r'<div class="hint">(.*?)</div>', block.group(0), re.S) if block else None
    return H.unescape(m.group(1)).strip() if m else ""


def test_us_format_is_appended_to_the_comment():
    html = _render(date_format="MM/DD/YYYY")
    assert _hint(html, "completed_date") == "The date the work was completed. (MM/DD/YYYY)"


def test_european_format_is_appended_instead():
    html = _render(date_format="DD/MM/YYYY")
    assert _hint(html, "completed_date") == "The date the work was completed. (DD/MM/YYYY)"


def test_a_date_field_with_no_comment_still_shows_the_format():
    """`published date` has a label but no rdfs:comment, and the format is still
    worth saying — so the hint is the pattern alone, not an empty parenthesis."""
    html = _render(date_format="MM/DD/YYYY")
    assert _hint(html, "recorded_date") == "(MM/DD/YYYY)"


def test_non_date_fields_are_untouched():
    html = _render(date_format="MM/DD/YYYY")
    assert "MM/DD/YYYY" not in _hint(html, "label")


def test_no_configured_format_leaves_hints_alone():
    html = _render(date_format="")
    assert _hint(html, "completed_date") == "The date the work was completed."


def test_the_format_is_DISPLAY_ONLY_and_the_stored_date_stays_ISO(tmp_path):
    """The load-bearing one. xs:date is ISO 8601 by definition, so a US display
    hint must not leak into the triple — the field stays <input type="date">,
    which submits ISO whatever the browser shows."""
    from rdflib import Graph, URIRef

    from cwva_dashboard.sandbox.fileops import FileOps
    from cwva_dashboard.sandbox.paths import Sandbox

    html = _render(date_format="MM/DD/YYYY")
    assert re.search(r'<input type="date"[^>]*id="completed_date"', html), (
        "must remain a date input, which submits ISO"
    )

    ops = FileOps(Sandbox.open(tmp_path))
    from cwva_dashboard.tools.record_tools import build_record_tools

    tool = next(
        t for t in build_record_tools(TEST_DOMAIN) if t.name == "record.new_work"
    )
    out = tool.handler(
        ops, type="Watercolor", label="L", description="d", height=1, width=1,
        units="inch", recorded_date="2026-09-04", completed_date="2026-09-04",
        has_paper="the:X", has_artist_profile="work:a", image="i.jpg", guid="g1",
    )
    g = Graph()
    g.parse(tmp_path / out["path"], format="turtle")
    stored = g.value(
        URIRef("http://visualartsdna.org/work/g1"), URIRef("https://schema.org/dateCreated")
    )
    assert str(stored) == "2026-09-04", "stored date must stay ISO"
    assert stored.datatype == URIRef("http://www.w3.org/2001/XMLSchema#date")


def test_auto_defers_to_the_browser(_unused=None):
    """`auto` renders a slot the browser fills, not a server guess.

    <input type="date"> is rendered by the browser in its own locale and the
    server cannot override it, so a server-side guess — from Accept-Language,
    say — reintroduces the very mismatch this removes. The slot is filled from
    the same Intl data the picker uses.
    """
    html = _render(date_format="auto")

    assert '<span class="date-fmt">' in html
    assert "formatToParts" in html, "the browser must supply the pattern"
    assert re.search(r'<input type="date"[^>]*id="completed_date"', html)


def test_the_auto_fallback_is_what_the_field_actually_submits():
    """Before the script runs, and with scripting off, the slot reads
    YYYY-MM-DD — which is exactly what <input type="date"> submits, so the
    fallback is never a lie even if it is not what the picker draws."""
    html = _render(date_format="auto")
    slot = re.search(r'<span class="date-fmt">(.*?)</span>', html).group(1)
    assert slot == "YYYY-MM-DD"


def test_an_explicit_format_forces_a_static_hint():
    """A deployment can still state a house convention; it just owns the risk
    of disagreeing with the picker, which is why auto is the default."""
    html = _render(date_format="MM/DD/YYYY")
    assert "MM/DD/YYYY" in _hint(html, "completed_date")
    assert 'class="date-fmt"' not in html


def test_the_date_format_script_parses():
    """Same check that caught the dead leave guard."""
    html = _render(date_format="auto")
    for block in re.findall(r"<script>(.*?)</script>", html, re.S):
        for line in block.splitlines():
            stripped = re.sub(r"\\.", "", line)
            assert stripped.count("'") % 2 == 0, line
            assert stripped.count('"') % 2 == 0, line


def test_an_ontology_comment_is_still_escaped():
    """The hint became trusted markup to carry the slot, so the model-sourced
    text must be escaped where it is taken — a comment is ontology content, and
    ontology content is data."""
    from rdflib import Graph

    from cwva_dashboard.tools.fileops_tools import build_default_registry
    from cwva_dashboard.tools.record_tools import WORK_FIELD_PROPERTIES
    from cwva_dashboard.ux.affordance import resolve_field_terms
    from cwva_dashboard.ux.forms import render_entry_form

    model = Graph()
    model.parse(data=(
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        "@prefix schema: <https://schema.org/> .\n"
        'schema:location rdfs:comment "<script>alert(1)</script> & more" .\n'
    ), format="turtle")
    schema = next(
        s for s in build_default_registry(domain=TEST_DOMAIN).schemas() if s["name"] == "record.new_work"
    )
    html = render_entry_form(
        schema, guid="g1", date_format="auto",
        terms=resolve_field_terms(model, WORK_FIELD_PROPERTIES),
    )

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "&amp; more" in html
