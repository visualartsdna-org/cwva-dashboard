"""Paths held deliberately ahead of production.

The shadow is normally a copy of production, and both tools around it assume so.
This marking is what tells them otherwise, and it protects a workflow that would
otherwise lose work silently: an ontology change tried in QA first would be
overwritten by the next metacontent re-seed, with nothing attic'd on the bucket
side to recover from.
"""

from __future__ import annotations

import pytest

from cwva_dashboard.sot_sync import qa_only


class TestIsProtected:
    def test_an_exact_path_matches_only_itself(self):
        marks = ("ttl/model/schemaSupplement.ttl",)
        assert qa_only.is_protected("ttl/model/schemaSupplement.ttl", marks)
        assert not qa_only.is_protected("ttl/model/cwva.ttl", marks)

    def test_a_trailing_slash_protects_the_subtree(self):
        """So a whole vocabulary can be held ahead without listing every file."""
        marks = ("ttl/vocab/",)
        assert qa_only.is_protected("ttl/vocab/papers.ttl", marks)
        assert qa_only.is_protected("ttl/vocab/nested/deep.ttl", marks)
        assert not qa_only.is_protected("ttl/model/cwva.ttl", marks)

    def test_a_prefix_without_a_slash_is_NOT_a_prefix(self):
        """`ttl/mod` must not protect `ttl/model/...`. Entries are exact paths or
        explicit subtrees — never accidental prefixes."""
        assert not qa_only.is_protected("ttl/model/cwva.ttl", ("ttl/mod",))

    def test_globs_are_not_supported_and_do_not_silently_match(self):
        """Deliberate: a pattern that quietly stops matching is how protection
        fails open. A literal '*' entry protects nothing but itself."""
        assert not qa_only.is_protected("ttl/model/cwva.ttl", ("ttl/model/*.ttl",))

    def test_leading_slashes_do_not_defeat_it(self):
        assert qa_only.is_protected("/ttl/model/x.ttl", ("ttl/model/x.ttl",))
        assert qa_only.is_protected("ttl/model/x.ttl", ("/ttl/model/x.ttl",))

    def test_nothing_is_protected_when_the_list_is_empty(self):
        for empty in ((), None, []):
            assert not qa_only.is_protected("ttl/model/x.ttl", empty)


class TestPartition:
    def test_splits_and_sorts(self):
        protected, plain = qa_only.partition(
            ["ttl/data/b.ttl", "ttl/vocab/z.ttl", "ttl/data/a.ttl"], ("ttl/vocab/",)
        )
        assert protected == ["ttl/vocab/z.ttl"]
        assert plain == ["ttl/data/a.ttl", "ttl/data/b.ttl"]


class TestLoad:
    def test_reads_the_target_block_in_order(self):
        cfg = {"qa_only": ["b.ttl", "a.ttl"]}
        assert qa_only.load(cfg) == ("b.ttl", "a.ttl")

    def test_absent_or_empty_is_no_protection(self):
        assert qa_only.load({}) == ()
        assert qa_only.load(None) == ()
        assert qa_only.load({"qa_only": []}) == ()


class TestSeedFilter:
    """The guard as the seed script applies it: prefix filter AND protection."""

    @staticmethod
    def _include(prefixes, protected, force):
        import importlib.util
        import pathlib

        spec = importlib.util.spec_from_file_location(
            "seedmod", pathlib.Path(__file__).resolve().parents[2] / "scripts" / "seed_shadow_sot.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod._make_include(prefixes, protected, force)

    def test_a_protected_path_is_skipped(self):
        inc = self._include(["ttl/"], ("ttl/model/schemaSupplement.ttl",), False)
        assert inc("ttl/model/cwva.ttl") is True
        assert inc("ttl/model/schemaSupplement.ttl") is False

    def test_force_overwrites_it(self):
        inc = self._include(["ttl/"], ("ttl/model/schemaSupplement.ttl",), True)
        assert inc("ttl/model/schemaSupplement.ttl") is True

    def test_the_prefix_filter_still_applies(self):
        inc = self._include(["ttl/model/"], (), False)
        assert inc("ttl/model/cwva.ttl") is True
        assert inc("documents/note.md") is False

    def test_no_prefix_means_everything_except_protected(self):
        inc = self._include(None, ("ttl/vocab/",), False)
        assert inc("documents/note.md") is True
        assert inc("ttl/vocab/papers.ttl") is False
