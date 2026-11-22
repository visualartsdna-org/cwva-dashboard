"""Lexical matcher — normalized Levenshtein (CE_DESIGN §6).

Score = ``max(rapidfuzz.ratio, token_sort_ratio)`` after normalization
(lowercase, strip hyphens and possessives), in [0, 1]. Threshold **0.9**,
user-overridable. This is the **single shared matcher**: concept dedup (§6),
the annotation-time remedy, and updateWorkOnSite title matching (§7.2) all use
it, so calibration never drifts between them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Iterable

from rapidfuzz import fuzz

__all__ = ["normalize", "score", "best_match", "Match", "DEFAULT_THRESHOLD"]

DEFAULT_THRESHOLD = 0.9

_POSSESSIVE = re.compile(r"'s\b|'")
_HYPHEN = re.compile(r"-")
_WS = re.compile(r"\s+")


def normalize(s: str) -> str:
    s = s.lower()
    s = _POSSESSIVE.sub("", s)  # strip possessives ("artist's" -> "artist")
    s = _HYPHEN.sub(" ", s)  # strip hyphens ("tonal-mass" -> "tonal mass")
    return _WS.sub(" ", s).strip()


def score(a: str, b: str) -> float:
    """Similarity of two strings in [0, 1] (1.0 exact, ~0.59 unrelated —
    preserving the Groovy Levenshtein calibration)."""
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    return max(fuzz.ratio(na, nb), fuzz.token_sort_ratio(na, nb)) / 100.0


@dataclass(frozen=True)
class Match:
    item: object
    score: float


def best_match(
    query: str,
    candidates: Iterable,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    key: Callable[[object], str] | None = None,
) -> Match | None:
    """Best candidate at/above ``threshold``, or None. ``key`` extracts the
    comparable label from each candidate (identity by default). When candidates
    carry several labels (prefLabel ∪ altLabel ∪ rdfs:label), pass each label as
    a separate candidate keyed back to its subject."""
    best: Match | None = None
    for c in candidates:
        label = key(c) if key else c
        s = score(query, label)
        if best is None or s > best.score:
            best = Match(item=c, score=s)
    if best is not None and best.score >= threshold:
        return best
    return None
