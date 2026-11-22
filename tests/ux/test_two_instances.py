"""Two dashboards, side by side: QA on :8100 and PRODUCTION on :8102.

They render the same pages from the same code against the same `work:`
namespace, so nothing in a window says which SOT an Approve will write to — and
one of the two cannot be undone (Rick, 2026-09-26). Three things keep them
apart: a banner on every page, a config that inherits rather than duplicates,
and separate sandboxes.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import TEST_DOMAIN
from cwva_dashboard import config as cfgmod
from cwva_dashboard.main import create_app
from cwva_dashboard.ux.banner import COLOURS, banner_html

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"

# The developer's two instances (QA beside production). Their configs are
# this machine's own and not in the public repository (2026-11-21), so on a
# fresh clone there is nothing here to check: a CE installation runs one.
pytestmark = pytest.mark.skipif(
    not (CONFIG_DIR / "dashboard.rson").is_file()
    or not (CONFIG_DIR / "production.rson").is_file(),
    reason="the developer's QA + production configs are not present")


# -- the shipped configs ------------------------------------------------------


def test_production_INHERITS_the_deployment_and_overrides_three_things():
    """Copying the file to change three keys would be two files drifting from
    the day they were written."""
    qa = cfgmod.load_config(CONFIG_DIR / "dashboard.rson")
    prod = cfgmod.load_config(CONFIG_DIR / "production.rson")

    assert prod["domain"] == qa["domain"]
    assert prod["sites"] == qa["sites"]
    # A nested override keeps its siblings: only stage_root differs.
    assert prod["sandbox"]["trash_keep_days"] == qa["sandbox"]["trash_keep_days"]
    assert prod["sandbox"]["stage_root"] != qa["sandbox"]["stage_root"]


def test_the_two_instances_CANNOT_SHARE_A_SANDBOX():
    """A promotion unit is everything uncommitted in the QA tree (law 4), so a
    shared sandbox means approving in production converges QA's staged work to
    production. This is the one line of config that must never be equal."""
    qa = cfgmod.load_config(CONFIG_DIR / "dashboard.rson")
    prod = cfgmod.load_config(CONFIG_DIR / "production.rson")

    assert qa["sandbox"]["stage_root"] != prod["sandbox"]["stage_root"]


def test_production_targets_the_REAL_bucket_and_QA_does_not():
    qa = cfgmod.load_config(CONFIG_DIR / "dashboard.rson")
    prod = cfgmod.load_config(CONFIG_DIR / "production.rson")

    assert prod["sot"]["bucket_env"] == "GCP_BUCKET"
    assert "sot" not in qa, "QA must not acquire a writable production target"
    assert qa["shadow_sot"]["bucket_env"] == "GCP_TEST_BUCKET"


def test_BOTH_are_labelled(): 
    """If only production carried a banner, its absence would have to mean "this
    is QA" — and absence is exactly what a rendering fault produces."""
    qa = cfgmod.environment(cfgmod.load_config(CONFIG_DIR / "dashboard.rson"))
    prod = cfgmod.environment(cfgmod.load_config(CONFIG_DIR / "production.rson"))

    assert qa == {"label": "QA", "colour": "green"}
    assert prod == {"label": "PRODUCTION", "colour": "amber"}


def test_a_config_that_EXTENDS_ITSELF_is_refused(tmp_path):
    (tmp_path / "a.rson").write_text('{"extends": "b.rson", "x": 1}')
    (tmp_path / "b.rson").write_text('{"extends": "a.rson", "y": 2}')

    with pytest.raises(ValueError, match="extends itself"):
        cfgmod.load_config(tmp_path / "a.rson")


# -- the banner, on every page ------------------------------------------------


@pytest.fixture
def labelled(tmp_path):
    app = create_app(
        domain=TEST_DOMAIN, sandbox_root=tmp_path / "qa",
        enforce_landlock=False, audit_path=tmp_path / "audit.jsonl",
    )
    app.state.environment = {"label": "PRODUCTION", "colour": "amber"}
    from cwva_dashboard.ux.banner import EnvironmentBanner

    app.add_middleware(EnvironmentBanner, label="PRODUCTION", colour="amber")
    with TestClient(app) as c:
        yield c


def test_the_banner_is_on_the_hub(labelled):
    html = labelled.get("/").text

    assert "PRODUCTION" in html
    assert COLOURS["amber"] in html
    assert html.count('data-env-banner="1"') == 1


def test_the_banner_is_on_pages_that_are_NOT_the_hub(labelled):
    """Threaded through each renderer it would be missing from whichever page is
    written next — quietly, and only on the instance nobody tests."""
    # Pages that render without a promotion target; `/drafts` 503s here, which
    # is correct and is a JSON body, so it is not a banner case.
    for path in ("/edit", "/rdf/artist", "/rdf/entry", "/annotate"):
        html = labelled.get(path).text
        assert 'data-env-banner="1"' in html, path


def test_it_does_not_touch_JSON(labelled):
    r = labelled.get("/api/health")

    assert "data-env-banner" not in r.text
    assert r.json()["status"] == "ok" if "status" in r.json() else True


def test_the_body_still_parses_as_one_page(labelled):
    """The banner goes immediately after <body>, and content-length is
    re-derived — a stale length truncates the page in the browser rather than
    failing loudly."""
    r = labelled.get("/")

    assert r.text.count("<body>") == 1
    assert r.text.index("data-env-banner") > r.text.index("<body>")
    assert int(r.headers["content-length"]) == len(r.content)


def test_an_UNLABELLED_app_gets_no_banner(tmp_path):
    """The fixture path: tests pin a sandbox and load no config at all."""
    app = create_app(domain=TEST_DOMAIN, sandbox_root=tmp_path / "qa",
                     enforce_landlock=False, audit_path=tmp_path / "audit.jsonl")
    with TestClient(app) as c:
        assert "data-env-banner" not in c.get("/").text
    assert app.state.environment == {"label": "", "colour": ""}


def test_a_raw_CSS_COLOUR_is_obeyed_rather_than_ignored():
    assert "#b45309" in banner_html("PRODUCTION", "#b45309")
    assert COLOURS["green"] in banner_html("QA", "green")


def test_the_label_is_ESCAPED():
    assert "<script>" not in banner_html("<script>x</script>", "green")


# -- one audit log per instance ----------------------------------------------
# The log is hash-chained and its tail is read ONCE at construction, so two live
# writers each link onto the tail as it was when they started and `verify()`
# reports a broken link — correctly, since it cannot tell two honest writers
# from one dishonest one.


def test_each_sandbox_gets_its_OWN_audit_log():
    from cwva_dashboard.main import _default_audit_path

    qa = _default_audit_path("/x/cwva-dashboard/sandbox")
    prod = _default_audit_path("/x/cwva-dashboard/sandbox-prod")

    assert qa != prod
    assert qa.name == "audit-sandbox.jsonl"
    assert prod.name == "audit-sandbox-prod.jsonl"


def test_the_audit_log_is_OUTSIDE_the_sandbox():
    """The confined worker must not be able to rewrite the record of what it
    did."""
    from cwva_dashboard.main import _default_audit_path

    root = Path("/x/cwva-dashboard/sandbox")
    assert root not in _default_audit_path(root).parents


def test_the_shipped_configs_cannot_collide_on_it():
    from cwva_dashboard.main import _default_audit_path

    qa = cfgmod.sandbox_root(cfgmod.load_config(CONFIG_DIR / "dashboard.rson"),
                             create=False)
    prod = cfgmod.sandbox_root(cfgmod.load_config(CONFIG_DIR / "production.rson"),
                               create=False)

    assert _default_audit_path(qa) != _default_audit_path(prod)


def test_two_instances_write_SEPARATE_chains_that_both_verify(tmp_path):
    """The behaviour the split exists for: run both, and each log still
    verifies end to end."""
    from cwva_dashboard.audit import verify

    apps = []
    for name in ("sandbox", "sandbox-prod"):
        app = create_app(domain=TEST_DOMAIN, sandbox_root=tmp_path / name,
                         enforce_landlock=False)
        apps.append(app)
    clients = [TestClient(a) for a in apps]
    for c in clients:
        c.__enter__()
    try:
        for _ in range(3):
            for c in clients:
                c.get("/api/workflow-state")
    finally:
        for c in clients:
            c.__exit__(None, None, None)

    for name in ("sandbox", "sandbox-prod"):
        log = tmp_path / f"audit-{name}.jsonl"
        assert log.exists(), name
        assert verify(log).ok, name
