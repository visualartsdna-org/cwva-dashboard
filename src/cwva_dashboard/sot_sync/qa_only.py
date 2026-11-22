"""Paths the QA target holds DELIBERATELY AHEAD of production.

The shadow is normally a copy of production, and both tools around it assume so:
``seed_shadow_sot`` overwrites it from production, and ``verify_shadow`` reads a
difference as drift or a clone defect. Neither assumption survives the workflow
this exists for — trying an ontology change in QA *before* it goes to
production.

Without marking, that workflow loses work twice over:

- a metacontent re-seed silently overwrites the QA-only edit with production's
  older copy (adds-only convergence, so nothing is attic'd on the bucket side —
  the previous content is simply gone);
- ``verify_shadow --compare`` reports the edit as ``corrupt``, i.e. a clone
  defect, which is exactly backwards and trains the reader to ignore the check.

Marking a path here says "this difference is intended". The seed then refuses to
overwrite it without an explicit flag, and verification reports it as ahead of
production rather than broken — and can list what still needs reconciling.

Scope note: this whole apparatus is a **development-cycle** facility. A live CE
dashboard points at its own SOT and never syncs from a separate production
bucket, so none of this applies there.
"""

from __future__ import annotations

__all__ = ["load", "is_protected", "partition"]


def load(target_cfg: dict | None) -> tuple[str, ...]:
    """QA-only paths from a target's config block, in declaration order."""
    return tuple((target_cfg or {}).get("qa_only") or ())


def is_protected(rel: str, qa_only) -> bool:
    """Is ``rel`` marked QA-only?

    An entry ending in ``/`` protects a whole subtree, so a deployer can hold
    all of ``ttl/model/`` ahead of production without listing every file. Any
    other entry is an exact path — deliberately not a glob, because a pattern
    that quietly stops matching is how protection fails open.
    """
    rel = rel.lstrip("/")
    for entry in qa_only or ():
        e = str(entry).lstrip("/")
        if e.endswith("/"):
            if rel.startswith(e):
                return True
        elif rel == e:
            return True
    return False


def partition(paths, qa_only) -> tuple[list[str], list[str]]:
    """Split ``paths`` into (protected, unprotected), each sorted."""
    protected, plain = [], []
    for p in paths:
        (protected if is_protected(p, qa_only) else plain).append(p)
    return sorted(protected), sorted(plain)
