"""Bridging the pointer layer to convergence (CE_DESIGN §3.4).

The QA git manifest is expressed in *tracked* files: for a pointer-managed
binary that means its ``.ptr`` sidecar, not the binary (which git ignores).
But SOT wants the real binary, never the QA-internal sidecar. This module maps
a git manifest to the **content manifest** that transports actually converge:
each changed ``<x>.ptr`` becomes ``<x>`` (the real binary), everything else
passes through, and no ``.ptr`` is ever pushed to SOT.

Because ``fileops`` keeps a managed binary and its sidecar in lockstep, a
changed ``.ptr`` exactly tracks a changed binary, so this translation is sound.
"""

from __future__ import annotations

from ..sandbox.pointers import (
    DEFAULT_GIT_CONTENT_EXTENSIONS,
    POINTER_SUFFIX,
    is_managed_binary,
)
from .unit import ChangeManifest

__all__ = ["content_manifest"]


def content_manifest(
    manifest: ChangeManifest, managed: frozenset[str] = DEFAULT_GIT_CONTENT_EXTENSIONS
) -> ChangeManifest:
    """Map a QA git manifest to the manifest converged to SOT: ``<x>.ptr`` for
    a managed binary -> ``<x>``; ``.ptr`` sidecars are never sent to SOT."""

    def tx(paths: list[str]) -> list[str]:
        out: list[str] = []
        for p in paths:
            if p.endswith(POINTER_SUFFIX):
                binary = p[: -len(POINTER_SUFFIX)]
                if is_managed_binary(binary, managed):
                    out.append(binary)  # push the real binary, drop the sidecar
                # a .ptr for a non-managed file is anomalous; drop it from SOT
            else:
                out.append(p)
        return sorted(set(out))

    return ChangeManifest(
        adds=tx(manifest.adds), modifies=tx(manifest.modifies), deletes=tx(manifest.deletes)
    )
