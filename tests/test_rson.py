"""RSON loader — JSON + # comments, matching cwva_core's util/rson.py, and the
real config files parse."""

from __future__ import annotations

import pytest

from cwva_dashboard import rson
from cwva_dashboard.config import load_config, sandbox_root
from cwva_dashboard.workflow_state.definitions import load_standing_queries


def test_whole_line_and_inline_comments():
    text = """
    {
        # a whole-line comment
        "a": 1,  # inline comment after a value
        "b": [2, 3],
        "c": {"d": true}
    }
    """
    assert rson.loads(text) == {"a": 1, "b": [2, 3], "c": {"d": True}}


def test_loads_plain_json():
    assert rson.loads('{"x": "y"}') == {"x": "y"}


def test_the_shipped_base_and_examples_parse(tmp_path):
    for path in ("config/base.rson", "config/examples/folder.rson",
                 "config/examples/git.rson", "config/examples/gcp.rson",
                 "config/examples/sample.rson"):
        cfg = load_config(path)
        assert cfg["sandbox"]["stage_root"], path
        assert cfg["quotas"]["max_file_bytes"] == 52428800, path
    # sandbox_root expands ~ and creates the dir
    cfg = load_config("config/base.rson")
    cfg["sandbox"]["stage_root"] = str(tmp_path / "sb")
    assert sandbox_root(cfg).is_dir()


def test_standing_queries_rson_loads_query_from_sparql_file():
    defs = load_standing_queries("config/standing_queries.rson")
    ids = {d.id for d in defs}
    assert {"concept_queue", "works_without_workonsite", "concepts_extracted_false"} <= ids
    # SPARQL is loaded from the referenced .sparql file (RSON can't inline it).
    wq = next(d for d in defs if d.id == "works_without_workonsite")
    assert "SELECT ?item ?label" in wq.query
    assert "rdf-schema#" in wq.query  # the '#' that RSON could not carry inline


def test_missing_file_falls_back_to_defaults():
    defs = load_standing_queries("config/does_not_exist.rson")
    assert len(defs) >= 4  # shipped Python defaults
