"""A proposing stage refuses before the model is called.

`expect_stage` guarded the WRITES, which made a mis-ordered stage
all-or-nothing in the store. It did not guard the COST or the cache: running
`dts.py derive` on an already-derived entity paid for a second model call,
overwrote the cached proposals the curator would be shown, and only then was
refused — leaving one entity offering one set of concepts while its own
evidence record stated a different one. Found 2026-10-01 by comparing the two
files' mtimes after I ran `derive` twice on the Three Graces copy.

**The dashboard was never exposed.** `/dts/entity` routes by state — "one door
per entity rather than one per stage, so a stale link cannot run the wrong
step" — so an already-derived entity lands on its curation screen. The hole was
in the operator CLI, where the stage is named explicitly on the command line,
and that is what is tested here.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from rdflib import Graph, URIRef

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import dts as dts_cli  # noqa: E402

from cwva_dashboard.dts.state import write_stamp  # noqa: E402

W = "http://visualartsdna.org/work/"

ENTITY = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix the: <http://visualartsdna.org/thesaurus/> .
@prefix work: <http://visualartsdna.org/work/> .

work:e1 a the:AI ; rdfs:label "A criticism" ;
    skos:inScheme the:entities ;
    the:mdDocument <http://visualartsdna.org/documents/Doc.md> .
"""


class _Layout:
    def dir(self, key):
        return {"work_ttl": "ttl/data"}[key]


class _Dts:
    """Just enough pipeline for the guard: the entity file and the layout."""

    def __init__(self, turtle):
        self.layout = _Layout()
        self._turtle = turtle
        self.reads = 0

    def read_text(self, path):
        self.reads += 1
        return self._turtle

    # bound in `_dts` from the real DTS class, so the check under test is the
    # shipped one rather than a restatement of it.
    expect_stage = None


def _dts(stamps=()):
    g = Graph().parse(data=ENTITY, format="turtle")
    for stage in stamps:
        write_stamp(g, URIRef(W + "e1"), stage)
    turtle = g.serialize(format="turtle")

    from cwva_dashboard.dts.pipeline import DTS

    obj = _Dts(turtle)
    obj.expect_stage = DTS.expect_stage.__get__(obj, _Dts)
    return obj


# -- the guard ---------------------------------------------------------------


def test_a_FRESH_entity_passes_the_guard(capsys):
    """Queue 1: nothing stamped, so `derived` is next."""
    assert dts_cli._guard(_dts(), "e1", W + "e1", "derived") == 0
    assert capsys.readouterr().out == ""


def test_an_ALREADY_DERIVED_entity_is_refused(capsys):
    """The case that cost a model call: `derive` run twice."""
    rc = dts_cli._guard(_dts(["derived"]), "e1", W + "e1", "derived")

    assert rc == 1
    assert "cannot derived" in capsys.readouterr().out


def test_the_refusal_says_WHAT_IS_NEXT(capsys):
    """An operator who ran the wrong command needs the right one, not just a
    rejection."""
    dts_cli._guard(_dts(["derived"]), "e1", W + "e1", "derived")

    out = capsys.readouterr().out
    assert "waiting for derivationCurated" in out
    assert "Nothing was written" in out


def test_TAGGING_before_curation_is_refused(capsys):
    """The two-stamp flow: `tagged` is not next until a curator has closed
    derivation."""
    rc = dts_cli._guard(_dts(["derived"]), "e1", W + "e1", "tagged")

    assert rc == 1
    assert "waiting for derivationCurated" in capsys.readouterr().out


def test_TAGGING_after_curation_passes(capsys):
    assert dts_cli._guard(_dts(["derived", "derivationCurated"]),
                          "e1", W + "e1", "tagged") == 0


def test_SUMMARIZING_out_of_order_is_refused(capsys):
    rc = dts_cli._guard(_dts(["derived", "derivationCurated"]),
                        "e1", W + "e1", "summarized")

    assert rc == 1


def test_a_COMPLETE_entity_is_refused_for_every_stage(capsys):
    """And says "complete" rather than naming a stage it is waiting for."""
    done = ["derived", "derivationCurated", "tagged", "taggingCurated",
            "summarized", "summaryCurated"]

    for stage in ("derived", "tagged", "summarized"):
        assert dts_cli._guard(_dts(done), "e1", W + "e1", stage) == 1
        assert "complete" in capsys.readouterr().out


# -- and it is reached before anything is spent ------------------------------


def test_the_guard_reads_ONLY_the_entity_file():
    """Cheap by construction: one read, no model, no store traversal. A guard
    that cost anything would be one somebody moved back below the call."""
    d = _dts(["derived"])

    dts_cli._guard(d, "e1", W + "e1", "derived")

    assert d.reads == 1


def test_the_entity_path_is_the_LAYOUT_path():
    """Not a hardcoded `ttl/data/` — a deployment whose layout differs would
    have the guard read a file that does not exist and raise instead of
    refusing."""
    assert dts_cli._entity_path(_dts(), "abc") == "ttl/data/abc.ttl"


def test_every_PROPOSING_command_calls_the_guard():
    """The three that cost money. Derived from the source rather than listed,
    so a fourth proposing stage cannot be added without one."""
    import inspect

    for name in ("cmd_derive", "cmd_tag", "cmd_summarize"):
        src = inspect.getsource(getattr(dts_cli, name))
        # `if _guard(...)` and not merely a mention: the first cut asserted
        # the substring, and `if False and _guard(...)` passed it.
        assert "if _guard(" in src, f"{name} does not guard before the model call"
        assert "return 1" in src.split("if _guard(")[1][:60], (
            f"{name} calls the guard without acting on it")


def test_the_guard_runs_BEFORE_the_model_call_in_each_command():
    """Order is the whole point: below the call it guards nothing that costs."""
    import inspect

    for name, caller in (("cmd_derive", "derive("),
                         ("cmd_tag", "tag("),
                         ("cmd_summarize", "summarize(")):
        src = inspect.getsource(getattr(dts_cli, name))
        guard_at = src.index("if _guard(")
        call_at = src.index(f"res = {caller}")
        assert guard_at < call_at, f"{name} guards after the model call"
