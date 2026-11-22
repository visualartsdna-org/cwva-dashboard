"""`type` is an ontology-backed dispatch enum (Q9).

The candidate set is the RDFS subclass closure of a per-form `type_root` in the
ontology — resolved at registry-build time and materialized into the schema
`enum`, so it enforces at dispatch (binding both drivers, store-free) while the
set comes from the model, not hardcoded. Adding a work kind is an ontology edit,
not a code change. `allow_abstract_root` keeps the abstract parent a valid
fallback for a novel medium not yet modeled as its own class.
"""

from __future__ import annotations

import pytest
from rdflib import Graph, Namespace
from rdflib.namespace import OWL, RDF, RDFS

from cwva_dashboard.sandbox.fileops import FileOps
from cwva_dashboard.sandbox.paths import Sandbox
from cwva_dashboard.tools.record_tools import build_record_tools, subclass_closure
from cwva_dashboard.tools.registry import ToolRegistry

VAD = Namespace("http://visualartsdna.org/model/")


def _model():
    """A synthetic mini-ontology: PaintingForm with a two-hop descendant
    (EggTempera → TemperaPainting → PaintingForm) so the closure test proves it
    is transitive, not just direct children. SculptureForm is a sibling root."""
    g = Graph()
    g.add((VAD.PaintingForm, RDF.type, OWL.Class))
    g.add((VAD.Watercolor, RDFS.subClassOf, VAD.PaintingForm))
    g.add((VAD.TemperaPainting, RDFS.subClassOf, VAD.PaintingForm))
    g.add((VAD.EggTempera, RDFS.subClassOf, VAD.TemperaPainting))  # two hops
    g.add((VAD.SculptureForm, RDF.type, OWL.Class))
    g.add((VAD.BlenderComposition, RDFS.subClassOf, VAD.SculptureForm))
    return g


_FORMS = {
    "work": {"type_root": "vad:PaintingForm", "allow_abstract_root": True},
    "digital": {"type_root": "vad:SculptureForm", "allow_abstract_root": True},
}


# -- the closure function ----------------------------------------------------


def test_closure_is_transitive_and_includes_root():
    s = subclass_closure(_model(), VAD.PaintingForm, include_root=True)
    assert s == ["EggTempera", "PaintingForm", "TemperaPainting", "Watercolor"]


def test_closure_can_exclude_root():
    s = subclass_closure(_model(), VAD.PaintingForm, include_root=False)
    assert "PaintingForm" not in s and "Watercolor" in s


def test_closure_none_when_root_absent():
    assert subclass_closure(_model(), VAD.NotAClass) is None


# -- the type field on the built tools ---------------------------------------


def _registry(model, forms=_FORMS):
    reg = ToolRegistry()
    for t in build_record_tools("http://visualartsdna.org", model=model, entry_forms=forms):
        reg.register(t)
    return reg


def _type_schema(reg, tool):
    return reg.get(tool).input_schema["properties"]["type"]


def test_type_is_a_strict_enum_from_the_ontology(tmp_path):
    reg = _registry(_model())
    wt = _type_schema(reg, "record.new_work")
    assert wt["enum"] == ["EggTempera", "PaintingForm", "TemperaPainting", "Watercolor"]
    assert "default" not in wt  # no default (Rick)
    assert "x-enum-suggested" not in wt


@pytest.fixture
def ops(tmp_path):
    return FileOps(Sandbox.open(tmp_path / "stage", create=True))


_WORK = dict(
    label="x", description="d", height=1, width=1, units="inch",
    recorded_date="2026-08-05", completed_date="2026-08-05",
    has_paper="the:P", has_artist_profile="work:a", image="a.jpg",
)


def test_a_type_in_the_closure_is_accepted(ops):
    reg = _registry(_model())
    dr = reg.dispatch("record.new_work", {**_WORK, "type": "Watercolor"}, ops)
    assert dr.ok, dr.error


def test_the_abstract_parent_is_accepted_as_fallback(ops):
    """allow_abstract_root: a novel medium not modeled as a class falls back to
    vad:PaintingForm itself."""
    reg = _registry(_model())
    dr = reg.dispatch("record.new_work", {**_WORK, "type": "PaintingForm"}, ops)
    assert dr.ok, dr.error


def test_a_typo_is_rejected(ops):
    reg = _registry(_model())
    dr = reg.dispatch("record.new_work", {**_WORK, "type": "Watercolour"}, ops)  # sic
    assert not dr.ok and dr.error["code"] == "not_in_enum"


def test_a_wrong_root_type_is_rejected_per_form(ops):
    """The per-form point: a SculptureForm value on the painting form is rejected
    at dispatch — the reason type lives at dispatch (each tool has its own root),
    not the promotion gate (which can't tell the forms apart)."""
    reg = _registry(_model())
    dr = reg.dispatch("record.new_work", {**_WORK, "type": "BlenderComposition"}, ops)
    assert not dr.ok and dr.error["code"] == "not_in_enum"
    # and it IS valid on the digital form
    _DIG = dict(
        label="x", description="d", note="n", height=1, width=1, depth=1, units="meter",
        recorded_date="2026-08-05", completed_date="2026-08-05",
        has_artist_profile="work:a", image="a.jpg", type="BlenderComposition",
    )
    assert reg.dispatch("record.new_digital", _DIG, ops).ok


def test_allow_abstract_root_false_excludes_the_parent(ops):
    forms = {"work": {"type_root": "vad:PaintingForm", "allow_abstract_root": False},
             "digital": _FORMS["digital"]}
    reg = _registry(_model(), forms)
    dr = reg.dispatch("record.new_work", {**_WORK, "type": "PaintingForm"}, ops)
    assert not dr.ok and dr.error["code"] == "not_in_enum"  # parent excluded
    assert reg.dispatch("record.new_work", {**_WORK, "type": "Watercolor"}, ops).ok


def test_fallback_to_suggested_when_no_model(ops):
    """No ontology (fresh sandbox before sync): type falls back to an unenforced
    suggested set, so entry still works with any value."""
    reg = _registry(None)
    wt = _type_schema(reg, "record.new_work")
    assert "enum" not in wt and "x-enum-suggested" in wt
    # a value outside the suggested set is accepted (not enforced)
    assert reg.dispatch("record.new_work", {**_WORK, "type": "SomethingNovel"}, ops).ok
