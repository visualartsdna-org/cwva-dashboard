"""Change preview — the review gate before the browser lands (CE_DESIGN §3.2).

Two layers, matching §3.4:

- **File level** — the git manifest (adds / modifies / **deletes**), so the
  user sees the blast radius: "touches these files, nothing else."
- **Semantic level** — an **isomorphic** RDF graph diff (never a text diff of
  serialized RDF; CLAUDE.md law). We load the affected RDF at the pre-work
  commit and at the working tree and compare the graphs, so blank-node churn
  and triple reordering do not show up as spurious changes; only real triple
  additions/removals do.

The result is a structured :class:`ChangePreview` plus a deterministic summary
("adds 1 Work, 1 Criticism; modifies 2 subject(s)"). The AI narration layer
(later) can prettify it; the structure is what the review gate and the audit
log consume. Its purpose is to catch the "agent did more than asked" class of
error before anything converges to SOT.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from rdflib import RDF, Graph, URIRef
from rdflib.compare import graph_diff

from .gates import rdf_format
from .qa_git import QAGit
from .unit import ChangeManifest

__all__ = ["ChangePreview", "build_preview"]


@dataclass
class ChangePreview:
    manifest: ChangeManifest
    rdf_files: list[str] = field(default_factory=list)
    nonrdf_files: list[str] = field(default_factory=list)
    triples_added: int = 0
    triples_removed: int = 0
    subjects_added: list[str] = field(default_factory=list)
    subjects_removed: list[str] = field(default_factory=list)
    subjects_modified: list[str] = field(default_factory=list)
    added_by_type: dict[str, int] = field(default_factory=dict)
    removed_by_type: dict[str, int] = field(default_factory=dict)

    def summary(self) -> str:
        """A one-line, human-readable change summary."""
        parts: list[str] = []
        c = self.manifest.counts
        parts.append(f"files {self.manifest.summary()} ({c['adds']+c['modifies']+c['deletes']} touched)")

        if self.added_by_type:
            parts.append("adds " + ", ".join(f"{n} {t}" for t, n in sorted(self.added_by_type.items())))
        elif self.subjects_added:
            parts.append(f"adds {len(self.subjects_added)} subject(s)")
        if self.subjects_modified:
            parts.append(f"modifies {len(self.subjects_modified)} subject(s)")
        if self.removed_by_type:
            parts.append("removes " + ", ".join(f"{n} {t}" for t, n in sorted(self.removed_by_type.items())))
        elif self.subjects_removed:
            parts.append(f"removes {len(self.subjects_removed)} subject(s)")

        if self.rdf_files:
            parts.append(f"±triples +{self.triples_added}/-{self.triples_removed}")
        if self.nonrdf_files:
            parts.append(f"non-RDF: {', '.join(sorted(self.nonrdf_files))}")
        return "; ".join(parts)

    def to_dict(self) -> dict:
        return {
            "manifest": self.manifest.to_dict(),
            "rdf_files": sorted(self.rdf_files),
            "nonrdf_files": sorted(self.nonrdf_files),
            "triples_added": self.triples_added,
            "triples_removed": self.triples_removed,
            "subjects_added": sorted(self.subjects_added),
            "subjects_removed": sorted(self.subjects_removed),
            "subjects_modified": sorted(self.subjects_modified),
            "added_by_type": self.added_by_type,
            "removed_by_type": self.removed_by_type,
            "summary": self.summary(),
        }


def _localname(uri) -> str:
    s = str(uri)
    for sep in ("#", "/"):
        if sep in s:
            tail = s.rsplit(sep, 1)[1]
            if tail:
                return tail
    return s


def _uri_subjects(g: Graph) -> set:
    return {s for s in g.subjects() if isinstance(s, URIRef)}


def _type_counter(subjects, g: Graph) -> dict[str, int]:
    """Count the subjects by the SET of types each carries, not by one of them.

    This used to take ``types[0]``, which is whichever one rdflib happened to
    yield — arbitrary for any multi-typed subject, and most of the store is
    multi-typed: a work carries its leaf class AND ``vad:CreativeWork``
    (`record_tools._new_work`), and sixteen legacy records carry a nine-deep
    materialized ancestor chain. So the review stop's one-line summary of what
    is about to reach the SOT could report ``CreativeWork`` for a watercolour,
    or ``rdfs:Resource`` for one of the sixteen, with nothing to say it had
    chosen.

    Reporting the set is deterministic and loses nothing. Naming the LEAF alone
    would read better — ``adds 1 Watercolor`` — but it needs subsumption, which
    needs the ontology, and the preview deliberately sees only the files in the
    manifest. Threading a model graph in through `PromotionDriver` is the
    change that would buy it.
    """
    counter: Counter[str] = Counter()
    for s in subjects:
        names = sorted({_localname(t) for t in g.objects(s, RDF.type)})
        counter["+".join(names) if names else "(untyped)"] += 1
    return dict(counter)


def build_preview(
    qa: QAGit, manifest: ChangeManifest, base_commit: str, *, content_root=None
) -> ChangePreview:
    """Compute a :class:`ChangePreview` for ``manifest`` between ``base_commit``
    and the current working tree. RDF files are diffed isomorphically; anything
    else is reported at the file level only."""
    content_root = Path(content_root) if content_root is not None else qa.root

    all_paths = manifest.all_paths()
    rdf_files = [p for p in all_paths if rdf_format(p)]
    nonrdf_files = [p for p in all_paths if not rdf_format(p)]

    preview = ChangePreview(
        manifest=manifest, rdf_files=sorted(rdf_files), nonrdf_files=sorted(nonrdf_files)
    )
    if not rdf_files:
        return preview

    before = Graph()
    after = Graph()
    for p in rdf_files:
        fmt = rdf_format(p)
        # A stable base, so a relative IRI resolves to the SAME thing in the
        # before and after graphs and does not read as a change. It must also be
        # RESOLVABLE: `urn:qa:<path>` was neither — rdflib refuses a URN as a
        # base ("has no slash after colon"), so one record carrying a relative
        # IRI made every preview raise, which reached Rick as a server error
        # with no failing gate to explain it. `.invalid` is reserved by RFC 2606
        # and can never name a real resource, so this resolves deterministically
        # without pretending the address exists.
        pid = f"http://qa.invalid/{p}"
        old = qa.file_at(base_commit, p)
        if old:
            before.parse(data=old, format=fmt, publicID=pid)
        fp = content_root / p
        if fp.exists():
            after.parse(data=fp.read_text(encoding="utf-8"), format=fmt, publicID=pid)

    # Isomorphic diff: only_before = removed triples, only_after = added.
    _both, only_before, only_after = graph_diff(before, after)
    preview.triples_added = len(only_after)
    preview.triples_removed = len(only_before)

    before_subj = _uri_subjects(before)
    after_subj = _uri_subjects(after)
    changed = {s for s in only_before.subjects() if isinstance(s, URIRef)} | {
        s for s in only_after.subjects() if isinstance(s, URIRef)
    }

    added = after_subj - before_subj
    removed = before_subj - after_subj
    modified = changed & before_subj & after_subj

    preview.subjects_added = sorted(str(s) for s in added)
    preview.subjects_removed = sorted(str(s) for s in removed)
    preview.subjects_modified = sorted(str(s) for s in modified)
    preview.added_by_type = _type_counter(added, after)
    preview.removed_by_type = _type_counter(removed, before)
    return preview
