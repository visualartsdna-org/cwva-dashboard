"""Orphan report — unreferenced binaries (CE_DESIGN §4).

Binaries accumulate: a work record is deleted or re-pointed and the image it
referenced is left behind. This report finds managed binaries present in the
content tree that no RDF term references, so the agent can offer their deletion
(which then promotes and converges like any other change).

v1 uses a **basename** heuristic: any RDF term (URI or literal) that ends in a
managed extension contributes its filename to the referenced set, and a present
binary is an orphan if its filename is not referenced. When the QA store lands
(Phase 7) this can sharpen to a real URI→content-path mapping via SPARQL; the
report shape stays the same.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from rdflib import Graph

from ..sandbox.pointers import DEFAULT_GIT_CONTENT_EXTENSIONS, POINTER_SUFFIX, is_managed_binary

__all__ = ["OrphanReport", "orphan_binaries"]


@dataclass
class OrphanReport:
    orphans: list[str] = field(default_factory=list)  # sandbox-relative paths
    referenced: int = 0
    present: int = 0

    def to_dict(self) -> dict:
        return {"orphans": self.orphans, "referenced": self.referenced, "present": self.present}


def _skip(p: Path) -> bool:
    parts = set(p.parts)
    return ".git" in parts or ".qa" in parts


def orphan_binaries(
    graph: Graph,
    content_root: str | Path,
    *,
    managed: frozenset[str] = DEFAULT_GIT_CONTENT_EXTENSIONS,
) -> OrphanReport:
    """Managed binaries under ``content_root`` not referenced by any term in
    ``graph`` (basename match)."""
    content_root = Path(content_root)

    referenced: set[str] = set()
    for s, p, o in graph:
        for term in (s, o):
            v = str(term)
            if is_managed_binary(v, managed):
                referenced.add(Path(v).name)

    present: dict[str, str] = {}  # basename -> relpath
    for f in content_root.rglob("*"):
        if not f.is_file() or _skip(f) or f.name.endswith(POINTER_SUFFIX):
            continue
        if is_managed_binary(f.name, managed):
            present[f.name] = f.relative_to(content_root).as_posix()

    orphans = sorted(rel for name, rel in present.items() if name not in referenced)
    return OrphanReport(orphans=orphans, referenced=len(referenced), present=len(present))
