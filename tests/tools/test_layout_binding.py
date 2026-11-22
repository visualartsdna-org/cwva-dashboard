"""B1 — layout is resolved from the ACTIVE TARGET, and readers and writers get
the *same* map.

The failure this guards: sync copies SOT relpaths verbatim, so a QA tree
mirroring the flat bucket keeps its model at ``ttl/model``. Anything still
reading the ``MIRROR_LAYOUT`` constant looks at ``metacontent/model``, finds
nothing, and silently degrades — with the correct data on disk. The writer half
is the same bug pointed the other way: records composed at ``content/ttl/data``
while synced content sits at ``ttl/data`` makes the mirror two trees.
"""

from __future__ import annotations

import pytest

from cwva_dashboard import config as cfgmod
from cwva_dashboard.promotion.layout import MIRROR_LAYOUT, Layout
from cwva_dashboard.tools.fileops_tools import build_default_registry

from conftest import TEST_DOMAIN

# The shadow bucket's flat layout — the first real target that differs.
FLAT = {
    "work_ttl": "ttl/data",
    "entity_ttl": "ttl/data",
    "digital_ttl": "ttl/data",
    "model_ttl": "ttl/model",
    "vocab_ttl": "ttl/vocab",
    "image": "images",
    "document": "documents",
}


def test_from_map_overlays_a_partial_target_map():
    """A target that relocates only the model need not restate the rest."""
    lay = Layout.from_map({"model_ttl": "ttl/model"})
    assert lay.dir("model_ttl") == "ttl/model"
    assert lay.dir("work_ttl") == MIRROR_LAYOUT["work_ttl"]  # default survives


def test_unknown_kind_raises_rather_than_guessing():
    with pytest.raises(KeyError, match="no placement for kind"):
        Layout.default().dir("nonesuch")


def test_active_layout_prefers_a_real_sot_over_the_shadow():
    """When a real `sot` block lands, QA mirrors production, not the shadow."""
    cfg = {"shadow_sot": {"mirror_layout": {"work_ttl": "shadow/data"}},
           "sot": {"mirror_layout": {"work_ttl": "prod/data"}}}
    assert cfgmod.active_layout(cfg).dir("work_ttl") == "prod/data"

    del cfg["sot"]
    assert cfgmod.active_layout(cfg).dir("work_ttl") == "shadow/data"

    assert cfgmod.active_layout({}).dir("work_ttl") == MIRROR_LAYOUT["work_ttl"]


def test_the_shipped_bucket_config_resolves_the_flat_layout():
    """A bucket target is flat — the case that forced B1. Since 2026-11-21 the
    shipped bucket config is the gcp example."""
    lay = cfgmod.active_layout(cfgmod.load_config(str(cfgmod.CONFIG_DIR / "examples" / "gcp.rson")))
    assert lay.dir("model_ttl") == "ttl/model"
    assert lay.dir("vocab_ttl") == "ttl/vocab"
    assert lay.dir("work_ttl") == "ttl/data"


def test_the_shipped_folder_config_is_cwva_pys_local_layout():
    lay = cfgmod.active_layout(cfgmod.load_config(str(cfgmod.CONFIG_DIR / "examples" / "folder.rson")))
    assert lay.dir("work_ttl") == "content/data"
    assert lay.dir("model_ttl") == "metacontent/model"
    assert lay.dir("image") == "content/images"


def _dest_default(schemas, tool_name, field="dest_dir"):
    schema = next(s for s in schemas if s["name"] == tool_name)
    return schema["inputSchema"]["properties"][field].get("default")


def test_writer_schema_defaults_follow_the_active_layout():
    """Record entry must default to where the QA tree actually keeps records."""
    flat = build_default_registry(domain=TEST_DOMAIN, layout=Layout.from_map(FLAT)).schemas()
    assert _dest_default(flat, "record.new_work") == "ttl/data"
    assert _dest_default(flat, "record.new_digital") == "ttl/data"
    assert _dest_default(flat, "record.new_entity") == "ttl/data"
    assert _dest_default(flat, "workflow.state", "content_dir") == "ttl/data"
    # `images_dir` is gone: identity is declared by the site, so no page image
    # is fetched and no SOT original is hashed. `data_dir` still binds — the
    # label index is read from wherever the QA tree keeps records.
    assert _dest_default(flat, "workflow.update_work_on_site", "data_dir") == "ttl/data"
    assert _dest_default(flat, "workflow.update_work_on_site") == "ttl/data"


def test_default_layout_is_unchanged_when_no_target_is_given():
    """Fixtures and the default target keep the disk layout they always had."""
    default = build_default_registry(domain=TEST_DOMAIN).schemas()
    assert _dest_default(default, "record.new_work") == MIRROR_LAYOUT["work_ttl"]
    assert _dest_default(default, "workflow.state", "content_dir") == MIRROR_LAYOUT["work_ttl"]


def test_readers_and_writers_agree_on_one_map():
    """The property that matters: for a given target, the dir a record is written
    to is the dir the workflow-state query counts. Two maps disagreeing is the
    whole bug class."""
    lay = Layout.from_map(FLAT)
    schemas = build_default_registry(domain=TEST_DOMAIN, layout=lay).schemas()
    assert (
        _dest_default(schemas, "record.new_work")
        == _dest_default(schemas, "workflow.state", "content_dir")
        == lay.dir("work_ttl")
    )
