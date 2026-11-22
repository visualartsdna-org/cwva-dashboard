"""First end-to-end workflow (CE_DESIGN §3): entry → gates → preview → promote
→ refresh, round-tripped to a files SOT. Marked e2e.

Uses the real record.new_work tool for entry (through the registry) and the
run_promotion orchestrator for the rest, against a QA git + a disposable files
SOT — the shape of every workflow the dashboard will run.
"""

from __future__ import annotations

import shutil

import pytest
from rdflib import Graph

from cwva_dashboard.promotion.gates import Assertion
from cwva_dashboard.promotion.qa_git import QAGit
from cwva_dashboard.promotion.transports import FilesTransport
from cwva_dashboard.sandbox.fileops import FileOps
from cwva_dashboard.sandbox.paths import Sandbox
from cwva_dashboard.tools.fileops_tools import build_default_registry
from cwva_dashboard.workflows.promote import run_promotion

from conftest import TEST_DOMAIN

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(shutil.which("git") is None, reason="git not installed"),
]

MIRROR = "content/ttl/data"  # cwvaServer-py disk layout (promotion/layout.py)

# A work must carry a label — the semantic gate for entry.
WORK_HAS_LABEL = Assertion(
    name="record_without_label",
    query=(
        "PREFIX schema: <https://schema.org/> "
        "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> "
        "SELECT ?w WHERE { ?w schema:identifier ?id . FILTER NOT EXISTS { ?w rdfs:label ?l } }"
    ),
    expect="empty",
)

ENTRY = dict(
    type="Watercolor",
    label="Mysterious Creature",
    description="Through the trees lurks a creature.",
    height=9,
    width=12,
    units="inch",
    recorded_date="2026-07-18",
    completed_date="2026-07-17",
    has_paper="the:StrathmoreWatercolorColdPressBlock",
    has_artist_profile="work:817ca809",
    image="creature.jpg",
    dest_dir=MIRROR,
)


@pytest.fixture
def env(tmp_path):
    root = tmp_path / "qa"
    root.mkdir()
    qa = QAGit.init(root)
    ops = FileOps(Sandbox.open(root))
    reg = build_default_registry(domain=TEST_DOMAIN)
    sot = FilesTransport(tmp_path / "sot")
    return qa, ops, reg, sot


def _entry(reg, ops, **overrides):
    dr = reg.dispatch("record.new_work", {**ENTRY, **overrides}, ops)
    assert dr.ok, dr.error
    return dr.result


def test_entry_gates_preview_promote_refresh_round_trip(env):
    qa, ops, reg, sot = env
    base = qa.head()
    baseline = sot.current_stamp()

    rec = _entry(reg, ops)  # entry: stage the record in the QA content mirror
    seen = {}

    res = run_promotion(
        qa, sot,
        workflow="entry",
        base_commit=base,
        description="add one work",
        provenance={"actor": "ux"},
        assertions=[WORK_HAS_LABEL],
        expected_stamp=baseline,
        on_preview=lambda p: seen.setdefault("preview", p) or True,  # review gate: approve
    )

    assert res.ok and res.status == "converged"
    # gates ran and passed (parse + the label assertion)
    assert [g.name for g in res.unit.gates] == ["parse", "sparql"]
    assert res.unit.gates_passed()
    # preview saw the new work
    # The SET of types, not one arbitrary member: a work is dual-typed with its
    # leaf class and vad:CreativeWork, and `types[0]` was reporting whichever
    # rdflib yielded first.
    assert res.preview.added_by_type == {"CreativeWork+Watercolor": 1}
    assert seen["preview"] is res.preview
    # promoted: SOT now holds the record at its mirror address
    sot_file = sot.target / MIRROR / f"{rec['guid']}.ttl"
    assert sot_file.exists()
    # round-trip: SOT content == QA content (isomorphic)
    qa_g = Graph().parse(qa.root / rec["path"], format="turtle")
    sot_g = Graph().parse(sot_file, format="turtle")
    from rdflib.compare import isomorphic
    assert isomorphic(qa_g, sot_g)
    # QA history advanced; refresh left QA clean and consistent with SOT
    assert qa.head() != base
    assert res.applied.sot_stamp == sot.current_stamp()
    assert res.refreshed is not None and res.refreshed.clean


def test_gates_failure_blocks_promotion(env):
    qa, ops, reg, sot = env
    base = qa.head()
    # A malformed TTL staged in the mirror — the parse gate must stop everything.
    ops.write_text(f"{MIRROR}/broken.ttl", '@prefix ex: <http://x/> .\nex:a ex:b "oops .\n', make_parents=True)

    res = run_promotion(qa, sot, workflow="entry", base_commit=base, expected_stamp=sot.current_stamp())

    assert res.status == "gates_failed" and not res.ok
    assert not res.unit.gates_passed()
    # nothing converged, nothing committed to QA
    assert list(sot.target.rglob("*.ttl")) == []
    assert qa.head() == base


def test_preview_rejection_blocks_promotion(env):
    qa, ops, reg, sot = env
    base = qa.head()
    _entry(reg, ops)

    res = run_promotion(
        qa, sot,
        workflow="entry",
        base_commit=base,
        assertions=[WORK_HAS_LABEL],
        expected_stamp=sot.current_stamp(),
        on_preview=lambda p: False,  # user rejects at the review gate
    )

    assert res.status == "rejected" and not res.ok
    assert res.preview is not None  # preview was produced for review
    assert list(sot.target.rglob("*.ttl")) == []  # no SOT write
    assert qa.head() == base
