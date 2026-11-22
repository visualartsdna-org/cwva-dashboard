"""SOT layout & placement map (CE_DESIGN §3.6).

**SOT layout = QA mirror layout.** Kind-routing — which artifact goes to which
folder — happens *here*, at promotion-unit composition, and **never in the
transports** (they are kind-blind and converge whatever relative paths the
manifest names). The Groovy push's sorting (`distributeData`/`distributeMetadata`)
is reference material for this map, **not code to port**.

Workflows compose in a **scratch working area outside the mirror**
(:data:`SCRATCH`); finishing a workflow moves each artifact to its final address
under the mirror via this map. A branded image landing in the images folder
picks up its `.ptr` sidecar automatically through fileops.

**There is no single standard layout** — it is per-target config. cwvaServer-py
holds the authoritative mapping in ``config/serverCwva.rson`` (kind → path), and
the targets differ: the local disk uses ``content/ttl/data``, ``content/ttl/tags``,
``metacontent/{model,vocab}``, ``content/{images,documents,thumbnails}``, while
the GCP bucket nests differently (``ttl/{data,model,provenance,tags,tko,topics,
vocab,archive}``, plus top-level ``documents/``, ``images/``, ``stats/``). The QA
mirror mirrors whichever SOT it converges to.

**Config-adjacent, hoisted.** The values below are the cwvaServer-py *disk*
layout as a working default; they should move to the dashboard SOT/transport
config (RSON) — the placement map is the indirection, actual paths are config.
Convergence stays kind-blind regardless (§3.6).

**Translation is reader-side, and this object is where it lives** (settled
2026-08-22, forced by the shadow target). Sync copies SOT relpaths **verbatim**,
so the QA tree adopts whatever layout its target uses — the shadow bucket is
flat (``ttl/data``, ``ttl/model``), not ``content/ttl/data``. Everything that
addresses mirror content therefore resolves through the **active target's**
:class:`Layout`: readers (the ontology and vocabulary loaders behind the
affordance layer) and writers (promotion-unit composition) alike. Both sides
must use the same object, or new records land at ``content/ttl/data`` while
synced content sits at ``ttl/data`` and the mirror is two trees pretending to be
one. :data:`MIRROR_LAYOUT` is demoted to *the default target's* map — a fallback,
no longer the truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

__all__ = ["MIRROR_LAYOUT", "SCRATCH", "Layout", "mirror_path"]

# Scratch composition area inside the sandbox, outside the mirrored tree.
SCRATCH = "stage"

# kind -> mirror-relative folder. Default = cwvaServer-py disk layout
# (config/serverCwva.rson); move to config per target.
MIRROR_LAYOUT: dict[str, str] = {
    "work_ttl": "content/ttl/data",
    "entity_ttl": "content/ttl/data",
    "digital_ttl": "content/ttl/data",
    "proof_ttl": "content/ttl/data",
    "provenance_ttl": "content/ttl/provenance",
    "tags_ttl": "content/ttl/tags",
    "model_ttl": "metacontent/model",
    "vocab_ttl": "metacontent/vocab",
    "image": "content/images",
    "thumbnail": "content/thumbnails",
    "document": "content/documents",
}


@dataclass(frozen=True)
class Layout:
    """A target's placement map, bound at runtime rather than imported.

    The whole point is that there is exactly **one** of these in play for a given
    QA tree, shared by readers and writers, so the two cannot disagree about
    where a kind lives. Unknown kinds raise rather than defaulting: a silent
    fallback would place an artifact somewhere plausible-but-wrong, which is the
    failure mode this class exists to prevent.
    """

    kinds: Mapping[str, str]

    @classmethod
    def default(cls) -> "Layout":
        """The default target's map (cwvaServer-py's disk layout)."""
        return cls(dict(MIRROR_LAYOUT))

    @classmethod
    def from_map(cls, mapping: Mapping[str, str] | None) -> "Layout":
        """A target's map, overlaid on the default so a partial config is legal —
        a target that only relocates ``model_ttl`` need not restate the rest."""
        return cls(dict(MIRROR_LAYOUT) | dict(mapping or {}))

    def dir(self, kind: str) -> str:
        try:
            return self.kinds[kind]
        except KeyError:
            raise KeyError(
                f"no placement for kind {kind!r}; known: {sorted(self.kinds)}"
            ) from None

    def path(self, kind: str, filename: str) -> str:
        """Final sandbox-relative address for an artifact of ``kind``."""
        return f"{self.dir(kind)}/{filename}"

    def as_dict(self) -> dict[str, str]:
        return dict(self.kinds)


def mirror_path(kind: str, filename: str) -> str:
    """Final sandbox-relative address under the **default** layout.

    Retained for call sites that legitimately have no target in hand (tests,
    fixtures). Anything reading or writing a real QA tree should take a
    :class:`Layout` instead — see the module docstring.
    """
    folder = MIRROR_LAYOUT[kind]
    return f"{folder}/{filename}"
