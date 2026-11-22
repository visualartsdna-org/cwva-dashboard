"""Shared lexical matcher (CE_DESIGN §6)."""

from __future__ import annotations

from cwva_dashboard.concepts.matcher import best_match, normalize, score


def test_normalize_strips_case_hyphens_possessives():
    assert normalize("Tonal-Mass") == "tonal mass"
    assert normalize("Artist's  Palette") == "artist palette"


def test_exact_match_scores_one():
    assert score("Sunrise", "sunrise") == 1.0


def test_near_match_above_threshold():
    # hyphen/possessive/case differences collapse under normalization
    assert score("tonal massing", "Tonal-Massing") == 1.0
    assert score("watercolour", "watercolor") >= 0.9


def test_unrelated_below_threshold():
    assert score("Sunrise", "Elephant") < 0.9


def test_token_sort_handles_word_order():
    assert score("mark saint", "Saint Mark") >= 0.9


def test_best_match_over_candidates_with_key():
    works = [("g1", "Sunrise"), ("g2", "Moonrise"), ("g3", "Dusk")]
    m = best_match("moonrise", works, key=lambda w: w[1])
    assert m is not None and m.item[0] == "g2" and m.score == 1.0


def test_best_match_returns_none_below_threshold():
    assert best_match("Nonexistent Thing", [("g1", "Sunrise")], key=lambda w: w[1]) is None
