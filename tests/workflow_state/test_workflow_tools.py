"""workflow.state / workflow.dismiss through the registry against real staged
content, and the dismiss→re-evaluate round-trip."""

from __future__ import annotations

import pytest

from cwva_dashboard.sandbox.fileops import FileOps
from cwva_dashboard.sandbox.paths import Sandbox
from cwva_dashboard.tools.fileops_tools import build_default_registry

from conftest import TEST_DOMAIN


@pytest.fixture
def env(tmp_path):
    sb = Sandbox.open(tmp_path / "stage", create=True)
    ops = FileOps(sb)
    reg = build_default_registry(domain=TEST_DOMAIN)
    # Stage QA content at the mirror address (§3.6): one unlinked work + one
    # pending entity + queue docs.
    ops.write_text(
        "content/ttl/data/w2.ttl",
        "@prefix schema: <https://schema.org/> . @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> ."
        " @prefix work: <http://visualartsdna.org/work/> ."
        " work:w2 schema:image <http://x/2.jpg> ; rdfs:label \"Unlinked\" .",
        make_parents=True,
    )
    ops.write_text(
        "content/ttl/data/e1.ttl",
        "@prefix the: <http://visualartsdna.org/thesaurus/> . @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> ."
        " @prefix work: <http://visualartsdna.org/work/> ."
        " work:e1 the:conceptsExtracted false ; rdfs:label \"Pending\" .",
        make_parents=True,
    )
    ops.write_text("conceptQueue/a.md", "# doc a", make_parents=True)
    ops.write_text("conceptQueue/b.md", "# doc b", make_parents=True)
    return reg, ops, sb


def _state(reg, ops):
    dr = reg.dispatch("workflow.state", {}, ops)
    assert dr.ok, dr.error
    return dr.result


def test_workflow_tools_registered(env):
    reg, _, _ = env
    assert {"workflow.state", "workflow.dismiss"} <= set(reg.names())


def test_state_reports_queues_and_obligations(env):
    reg, ops, _ = env
    st = _state(reg, ops)
    queues = {q["id"]: q["count"] for q in st["pipeline_queues"]}
    assert queues["concept_queue"] == 2
    defs = {o["definition_id"] for o in st["open_obligations"]}
    assert "works_without_workonsite" in defs
    assert "concepts_extracted_false" in defs
    assert "1 works with no site link" in st["summary"]


def test_dismiss_then_state_excludes_item(env):
    reg, ops, sb = env
    key = "http://visualartsdna.org/work/w2"
    d = reg.dispatch(
        "workflow.dismiss",
        {"definition_id": "works_without_workonsite", "item_key": key, "reason": "on no site by choice"},
        ops,
    )
    assert d.ok
    # the ledger persisted inside the sandbox (.qa, QA-internal)
    assert (sb.root / ".qa" / "hygiene_ledger.ttl").exists()

    st = _state(reg, ops)
    keys = [o["key"] for o in st["open_obligations"] if o["definition_id"] == "works_without_workonsite"]
    assert key not in keys


def test_state_on_empty_sandbox_is_nothing_pending(tmp_path):
    sb = Sandbox.open(tmp_path / "s2", create=True)
    st = _state(build_default_registry(domain=TEST_DOMAIN), FileOps(sb))
    assert st["summary"] == "nothing pending"


def test_recorded_tcap_tie_surfaces_as_panel_obligation(tmp_path):
    from cwva_dashboard.concepts.ledger import LEDGER_PATH, HygieneLedger

    sb = Sandbox.open(tmp_path / "s3", create=True)
    ops = FileOps(sb)
    # record a TCAP tie in the ledger (as annotate would)
    lg = HygieneLedger.from_ttl()
    lg.record_tie(
        "http://visualartsdna.org/work/w1",
        "http://visualartsdna.org/thesaurus/CrowdHingeBand",
        ["http://visualartsdna.org/model/hasComposition", "http://visualartsdna.org/model/hasCriticism"],
    )
    ops.write_text(LEDGER_PATH, lg.to_ttl(), make_parents=True)

    st = _state(build_default_registry(domain=TEST_DOMAIN), ops)
    ties = [o for o in st["open_obligations"] if o["definition_id"] == "tcap_ties"]
    assert len(ties) == 1
    assert "CrowdHingeBand" in ties[0]["label"]
    assert "TCAP ties to investigate" in st["summary"]
