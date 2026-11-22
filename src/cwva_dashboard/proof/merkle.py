"""The Merkle arithmetic a proof rests on, and the packed form it is stored in.

This is the durable half of the proof workflow (`PROOF_WORKFLOW.md`): it does
not care whether the path arrived from a scraped certificate or the OriginStamp
API, and it is what makes either source trustworthy. An extractor that gets a
sibling wrong cannot produce the right root, so a wrong path announces itself
rather than being written into a record that claims to be evidence.

**The combining rule is the one thing nobody can guess, so it is stated here
once and used everywhere.** OriginStamp hashes the ASCII HEX STRINGS,
concatenated -- not the 32 raw bytes, which is what Bitcoin's own block tree
does. A reader who assumes the familiar construction gets nonsense and may
conclude a sound proof is invalid. Verified against a real certificate across
all eleven levels on 2026-10-31.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

__all__ = ["Step", "combine", "fold", "verify", "pack", "unpack", "reconstruct",
           "PackedPathError", "normalise"]

_HEX64 = re.compile(r"\b[0-9a-f]{64}\b")
#: A packed token: the sibling's SIDE, then its hash.
_TOKEN = re.compile(r"^([LR]):([0-9a-f]{64})$")


class PackedPathError(ValueError):
    """A packed path that cannot be read. Never raised for a path that is
    merely *wrong* -- that is `verify`'s answer, and the difference matters:
    unreadable is a defect in the record, wrong is a defect in the evidence."""


def normalise(h: str) -> str:
    """A hash as this module handles it: lowercase hex, no ``0x``.

    The RDF carries ``0x``-prefixed values because that is how OriginStamp
    reports them and `ONTOLOGY_PLAN.md` §14 keeps an external system's facts in
    that system's terms. The prefix is presentation; it must not reach the hash
    function or nothing matches.
    """
    return (h or "").strip().lower().removeprefix("0x")


@dataclass(frozen=True)
class Step:
    """One level of the climb: the sibling, and which operand it is.

    ``side == "L"`` means the sibling goes FIRST -- ``sha256(sibling + current)``.
    ``side == "R"`` means it goes second. Stating which of the two the letter
    describes is not pedantry: both readings are plausible and only one works.
    """

    side: str
    sibling: str

    def __post_init__(self) -> None:
        if self.side not in ("L", "R"):
            raise PackedPathError(f"side must be L or R, not {self.side!r}")
        if not re.fullmatch(r"[0-9a-f]{64}", self.sibling):
            raise PackedPathError(f"not a sha256: {self.sibling!r}")


def combine(left_hex: str, right_hex: str) -> str:
    """One parent from two children. The rule in the module docstring."""
    return hashlib.sha256((normalise(left_hex) + normalise(right_hex)).encode()).hexdigest()


def fold(leaf: str, steps) -> str:
    """Climb from ``leaf`` through ``steps`` and return the value reached."""
    cur = normalise(leaf)
    for s in steps:
        cur = combine(s.sibling, cur) if s.side == "L" else combine(cur, s.sibling)
    return cur


def verify(leaf: str, steps, root: str) -> bool:
    """Does this leaf, by this path, reach this root? The whole gate."""
    return fold(leaf, steps) == normalise(root)


# -- the packed literal ----------------------------------------------------
#
# One RDF literal rather than a list of blank nodes, chosen 2026-11-01. A path
# is ordered and every element carries a side, which in RDF wants either an
# `rdf:List` or a blank node per level -- and nested blank nodes are the
# structure Edit Record twice failed to preserve (CE_DESIGN: "preserving
# verbatim means the WHOLE structure, however deep"). A packed literal is one
# value: nothing to walk, nothing to pair by position, nothing to lose.
#
# The cost is that RDF cannot see inside it. That is acceptable because nothing
# queries a Merkle path -- it is verified as a unit or not at all.

def pack(steps) -> str:
    """``L:<hash> R:<hash> …``, leaf-first, space separated.

    Leaf-first because that is the order verification walks, so the literal
    reads in the direction it is used. Fixed-width tokens, one separator, no
    characters that need escaping in a Turtle literal.
    """
    return " ".join(f"{s.side}:{s.sibling}" for s in steps)


def unpack(packed: str) -> list[Step]:
    """Read a packed path. Raises `PackedPathError` on anything malformed."""
    out: list[Step] = []
    for tok in (packed or "").split():
        m = _TOKEN.match(tok)
        if not m:
            raise PackedPathError(f"bad token {tok!r}; expected L:<64 hex> or R:<64 hex>")
        out.append(Step(m.group(1), m.group(2)))
    if not out:
        raise PackedPathError("empty path")
    return out


# -- recovering a path without being told the structure --------------------

def reconstruct(leaf: str, root: str, hashes, max_depth: int = 64):
    """Find the path from ``leaf`` to ``root`` using only a BAG of hashes.

    The robust extraction route (`PROOF_WORKFLOW.md` §5). Given every hash that
    appears in a certificate -- in any order, with no structure -- climb by
    trying each candidate as a left and a right sibling and keeping whichever
    produces another hash in the bag. It cannot go wrong undetected: a wrong
    sibling yields a value nothing else contains, and the search simply fails.

    This is what makes a layout change at OriginStamp a degradation rather than
    a corruption. Returns the steps, or None if no path exists.
    """
    bag = {normalise(h) for h in hashes}
    leaf, root = normalise(leaf), normalise(root)
    if leaf not in bag or root not in bag:
        return None
    cur, steps, seen = leaf, [], {leaf}
    while cur != root and len(steps) < max_depth:
        nxt = None
        for sib in bag:
            for side, parent in (("L", combine(sib, cur)), ("R", combine(cur, sib))):
                if parent in bag and parent not in seen:
                    nxt = (Step(side, sib), parent)
                    break
            if nxt:
                break
        if nxt is None:
            return None
        step, parent = nxt
        steps.append(step)
        seen.add(parent)
        cur = parent
    return steps if cur == root else None
