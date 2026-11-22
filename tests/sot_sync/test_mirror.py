"""The shadow MIRROR: make the shadow equal to production, deleting what
production does not have — and nothing it must keep."""

from __future__ import annotations

import pytest

from cwva_dashboard.promotion.transports import FilesTransport, ReadOnlySource
from cwva_dashboard.sot_sync.clone import mirror_source_to_target, plan_mirror

PROD = {"ttl/data/a.ttl": "1", "ttl/data/b.ttl": "2", "images/a.jpg": "3",
        "ttl/data/new.ttl": "9"}
SHADOW = {"ttl/data/a.ttl": "1", "ttl/data/b.ttl": "OLD", "images/a.jpg": "3",
          "ttl/data/junk.ttl": "x", "images/FairyPool52.jpg": "y",
          "operational/qa.bundle": "z", "ttl/model/trial.ttl": "q"}


def test_the_plan_copies_new_and_changed_and_deletes_shadow_only():
    plan = plan_mirror(PROD, SHADOW)
    assert plan.new == ["ttl/data/new.ttl"]
    plan.delete.remove("operational/qa.bundle")
    assert plan.changed == ["ttl/data/b.ttl"]
    assert plan.unchanged == 2
    assert plan.delete == ["images/FairyPool52.jpg", "ttl/data/junk.ttl",
                           "ttl/model/trial.ttl"]
    assert plan.refusal(max_fraction=1.0) is None


def test_nothing_of_qas_survives_not_even_its_backups():
    """Rick, 2026-11-19: prod is copied over QA in its entirety."""
    plan = plan_mirror(PROD, SHADOW)
    assert "operational/qa.bundle" in plan.delete
    prod = PROD | {"operational/qa.bundle": "PRODUCTION'S"}
    assert "operational/qa.bundle" in plan_mirror(prod, SHADOW).changed


def test_a_keep_rule_is_honoured_when_one_is_given():
    plan = plan_mirror(PROD, SHADOW, keep=lambda rel: rel.startswith("ttl/model/"))
    assert "ttl/model/trial.ttl" in plan.kept
    assert "ttl/model/trial.ttl" not in plan.delete


def test_a_prefix_filter_says_nothing_about_other_prefixes():
    plan = plan_mirror(PROD, SHADOW, include=lambda rel: rel.startswith("ttl/"))
    assert "images/FairyPool52.jpg" in plan.kept
    assert plan.delete == ["ttl/data/junk.ttl", "ttl/model/trial.ttl"]


def test_an_empty_production_listing_is_refused():
    assert "NO objects" in plan_mirror({}, SHADOW).refusal()


def test_deleting_most_of_the_shadow_is_refused():
    shadow = {f"ttl/data/{i}.ttl": "x" for i in range(10)} | {"ttl/data/a.ttl": "1"}
    assert "more than 25%" in plan_mirror({"ttl/data/a.ttl": "1"}, shadow).refusal()


def _tree(root, files):
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


def test_a_mirror_run_leaves_the_shadow_equal_to_production(tmp_path):
    prod_root, shadow_root = tmp_path / "prod", tmp_path / "shadow"
    _tree(prod_root, {"ttl/data/a.ttl": "a", "ttl/data/b.ttl": "b2",
                      "ttl/data/new.ttl": "n"})
    _tree(shadow_root, {"ttl/data/a.ttl": "a", "ttl/data/b.ttl": "b1",
                        "ttl/data/junk.ttl": "j", "operational/qa.bundle": "keep"})
    source = ReadOnlySource(FilesTransport(prod_root), label="prod")
    shadow = FilesTransport(shadow_root)

    plan = plan_mirror(source.snapshot(), shadow.snapshot())
    report = mirror_source_to_target(source, shadow, tmp_path / "staging", plan,
                                     max_fraction=1.0)

    assert report.objects == 2  # new + changed only; the unchanged one is not re-sent
    assert shadow.snapshot() == source.snapshot()
    assert not (shadow_root / "operational/qa.bundle").exists()
    assert not (shadow_root / "ttl/data/junk.ttl").exists()
    # production untouched
    assert not (prod_root / "ttl/data/junk.ttl").exists()


def test_a_refused_plan_writes_nothing(tmp_path):
    shadow_root = tmp_path / "shadow"
    _tree(shadow_root, {"ttl/data/a.ttl": "a"})
    (tmp_path / "prod").mkdir()
    source = ReadOnlySource(FilesTransport(tmp_path / "prod"), label="prod")
    shadow = FilesTransport(shadow_root)
    plan = plan_mirror(source.snapshot(), shadow.snapshot())
    with pytest.raises(ValueError, match="refused"):
        mirror_source_to_target(source, shadow, tmp_path / "staging", plan)
    assert (shadow_root / "ttl/data/a.ttl").exists()
