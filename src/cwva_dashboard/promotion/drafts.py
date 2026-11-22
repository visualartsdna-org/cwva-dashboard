"""Drafts: the uncommitted records, as records rather than as a pile of files.

Everything a form writes lands in QA and stays there until a promotion converges
it. That is correct — QA is the working store — but it left the work in a state
with no name and no surface: files git had not seen, discoverable only by
reading a preview or the `Discard Work in Progress` page, which speaks in paths.
Rick, 2026-09-18: "we need to treat drafts as first-class citizens."

A DRAFT IS A RECORD. `<guid>.ttl` uncommitted, with a label, a kind, an age, the
files that belong to it, and a way back to the editor that made it. The pile of
paths is the implementation; the record is the thing the user has in mind, and
the only thing they can decide about.

**Two verbs, deliberately different** (and this is the distinction the UI has to
keep):

- **Discard changes**, on a review stop, undoes THIS SESSION — the episode's
  restore point (episode.py). A record that was already a draft stays one.
- **Discard draft**, here, undoes EVERYTHING uncommitted about that record: it
  goes back to its last distributed state, or ceases to exist if it never had
  one. No snapshot is needed for that, because HEAD *is* the answer.

Orchestrator machinery, never a registry tool: it reads git and deletes files
outside any single record's business.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from rdflib import Graph, URIRef

__all__ = ["Draft", "DraftIndex", "graph_diff_lines"]

_HAS_ARTWORK = URIRef("http://visualartsdna.org/model/hasArtwork")
_GUID = re.compile(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                   r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})")


@dataclass
class Draft:
    guid: str
    path: str
    label: str = ""
    kinds: list = field(default_factory=list)
    new: bool = True
    mtime: float = 0.0
    files: list = field(default_factory=list)
    subject: str = ""
    #: `[(predicate, target-uri)]` — every record this one points at. Collected
    #: while the file is parsed anyway, because the question "is this set of
    #: drafts connected the way I meant" is asked of the SET, and answering it
    #: by re-reading each record when the page is drawn would be the fourth
    #: re-read-per-file mistake in this project.
    refs: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"guid": self.guid, "path": self.path, "label": self.label,
                "kinds": list(self.kinds), "new": self.new, "mtime": self.mtime,
                "files": sorted(self.files), "subject": self.subject,
                "refs": list(self.refs)}


class DraftIndex:
    """What is uncommitted, grouped into records.

    Reads the tree directly, like the rest of the promotion tail. The label
    comes from the record's own `rdfs:label`, because a GUID names nothing a
    person recognises and "the draft you have three of" is exactly the problem
    being solved.
    """

    def __init__(self, qa, layout=None, pointers=None, work_ns: str = ""):
        from .layout import Layout

        self.qa = qa
        self.layout = layout or Layout.default()
        self.pointers = pointers
        # `work:` is the DEPLOYER'S namespace, so it cannot be a constant here
        # the way `vad:` and `schema:` can (CE_DESIGN §13.4a). Without it every
        # subject in the diff prints as a full URI, which is most of the width
        # of the line and none of the meaning.
        self.work_ns = work_ns

    # -- reading -------------------------------------------------------------
    def list(self) -> list:
        record_dirs = [self.layout.dir(k).strip("/") for k in
                       ("work_ttl", "entity_ttl", "vocab_ttl", "model_ttl")]
        uncommitted = self.qa.uncommitted_paths()
        untracked = set(self.qa.untracked_paths())

        drafts: dict[str, Draft] = {}
        loose: list[str] = []
        for rel in sorted(uncommitted):
            in_records = any(rel.startswith(d + "/") for d in record_dirs)
            if in_records and rel.endswith(".ttl"):
                guid = Path(rel).stem
                d = Draft(guid=guid, path=rel, new=rel in untracked,
                          files=[rel])
                self._describe(d)
                drafts[guid] = d
            else:
                loose.append(rel)

        # Attachments: a QR, an ingested image, a sidecar. Matched by the GUID in
        # the name — `qrc_<guid>.jpg` — and otherwise left as their own item,
        # because a file we cannot attribute is exactly the kind of thing that
        # should not disappear into somebody's record silently.
        orphans = []
        for rel in loose:
            hit = _GUID.search(Path(rel).name)
            if hit and hit.group(1) in drafts:
                drafts[hit.group(1)].files.append(rel)
            else:
                orphans.append(rel)

        self._attach_provenance(drafts, orphans)
        out = sorted(drafts.values(), key=lambda d: -d.mtime)
        return [d.to_dict() for d in out], sorted(orphans)

    def _attach_provenance(self, drafts: dict, orphans: list) -> None:
        """A provenance record belongs to its work's draft, or stands alone.

        It carries its own guid, so the name match above cannot find its work.
        Left loose, discarding a draft would leave a provenance citing an artwork
        that no longer exists; and a provenance for a work already distributed
        would be listed nowhere you could act on it.
        """
        folder = self.layout.dir("provenance_ttl").strip("/") + "/"
        for rel in [r for r in orphans if r.startswith(folder) and r.endswith(".ttl")]:
            full = Path(self.qa.root) / rel
            if not full.is_file():
                continue  # a deletion: nothing to read, and it stays listed as loose
            orphans.remove(rel)
            g = Graph()
            try:
                g.parse(str(full), format="turtle")
                artwork = next(g.objects(None, _HAS_ARTWORK), None)
            except Exception:
                artwork = None
            owner = drafts.get(str(artwork).rsplit("/", 1)[-1]) if artwork else None
            if owner is not None:
                owner.files.append(rel)
                continue
            guid = Path(rel).stem
            d = Draft(guid=guid, path=rel, new=rel in set(self.qa.untracked_paths()),
                      files=[rel])
            self._describe(d)
            drafts[guid] = d

    def count(self) -> int:
        try:
            drafts, _ = self.list()
        except Exception:
            return 0
        return len(drafts)

    def _describe(self, d: Draft) -> None:
        from rdflib import Graph
        from rdflib.namespace import RDF, RDFS

        full = Path(self.qa.root) / d.path
        try:
            d.mtime = full.stat().st_mtime
        except OSError:
            pass
        try:
            g = Graph().parse(data=full.read_text(), format="turtle")
        except Exception:
            d.label = Path(d.path).name
            return
        subjects = [s for s in set(g.subjects()) if not str(s).startswith("N")]
        named = [s for s in subjects if hasattr(s, "n3") and not s.n3().startswith("_:")]
        if len(named) != 1:
            d.label = f"{Path(d.path).name} ({len(named)} subjects)"
            return
        subj = named[0]
        d.subject = str(subj)
        label = g.value(subj, RDFS.label)
        d.label = str(label) if label else Path(d.path).name
        d.kinds = sorted(str(t).rsplit("/", 1)[-1].rsplit("#", 1)[-1]
                         for t in g.objects(subj, RDF.type))
        if self.work_ns:
            d.refs = sorted(
                (str(pred), str(obj))
                for pred, obj in g.predicate_objects(subj)
                if isinstance(obj, URIRef) and str(obj).startswith(self.work_ns)
                and str(obj) != d.subject
            )

    # -- one draft, in detail ------------------------------------------------
    def detail(self, guid: str) -> dict:
        """One draft's triples, and what they change.

        The drafts list answers "what have I got"; this answers "what does it
        SAY", which is the question you have to answer before discarding
        something. The record is shown as written — the text is the only thing
        that says whether the triples are right, same reasoning as the review
        stop's Generated RDF — and beside it the difference from the last
        distributed version.

        **Isomorphic, never textual.** Two serializations of one graph differ in
        blank-node labels and statement order and are the same graph; a text
        diff would report a change that is not there, and the project has one
        rule about this.
        """
        drafts, _orphans = self.list()
        found = next((d for d in drafts if d["guid"] == guid), None)
        if found is None:
            return {}

        full = Path(self.qa.root) / found["path"]
        try:
            text = full.read_text(encoding="utf-8")
        except OSError as exc:
            return {**found, "error": f"{type(exc).__name__}: {exc}"}

        old_text = self.qa.file_at("HEAD", found["path"])
        out = {**found, "text": text, "distributed": old_text is not None,
               "added": [], "removed": [], "error": "",
               **self._connections(found, drafts)}
        try:
            out.update(self._diff(found["path"], old_text, text))
        except Exception as exc:  # noqa: BLE001 - a broken draft must still show
            out["error"] = (f"{type(exc).__name__}: {exc} — the text above is "
                            "what is on disk; the comparison could not be made.")
        return out

    def _connections(self, draft: dict, drafts: list) -> dict:
        """What this record points at, and what points at it — **by name**.

        The question a batch of related records has to answer is "is this
        connected the way I meant", and a bare `work:a1b2c3…` cannot answer it:
        matching four records by GUID across four pages is work the dashboard
        should be doing (Rick, 2026-09-27).

        Incoming references are computed from the OTHER DRAFTS, which is the
        right scope and the cheap one — they are parsed already, and "what in
        this batch points here" is the question. Finding every distributed
        record that points here would mean reading the whole store to draw one
        page.
        """
        by_subject = {d["subject"]: d for d in drafts if d.get("subject")}

        def describe(uri: str) -> dict:
            known = by_subject.get(uri)
            if known:
                return {"uri": uri, "label": known["label"], "draft": True,
                        "guid": known["guid"]}
            # Not in this batch: try the record's own file, which is the naming
            # convention everything this dashboard writes obeys. A grandfathered
            # record living inside an aggregate has none, and then the GUID is
            # the honest answer rather than a guess.
            guid = uri.rstrip("/").rsplit("/", 1)[-1]
            label = ""
            try:
                from rdflib import Graph
                from rdflib.namespace import RDFS

                text = (Path(self.qa.root) / f"{Path(draft['path']).parent}"
                        / f"{guid}.ttl").read_text()
                g = Graph().parse(data=text, format="turtle")
                found = g.value(URIRef(uri), RDFS.label)
                label = str(found) if found else ""
            except Exception:
                pass
            return {"uri": uri, "label": label, "draft": False, "guid": guid}

        points_at = [{"predicate": pred, **describe(uri)}
                     for pred, uri in draft.get("refs") or []]
        pointed_by = [
            {"predicate": pred, "label": other["label"], "guid": other["guid"],
             "uri": other["subject"], "draft": True}
            for other in drafts if other["guid"] != draft["guid"]
            for pred, uri in other.get("refs") or []
            if uri == draft.get("subject")
        ]
        return {"points_at": points_at, "pointed_by": pointed_by}

    def _diff(self, path: str, old_text, text: str) -> dict:
        from rdflib import Graph

        from .gates import rdf_format

        fmt = rdf_format(path) or "turtle"
        # The SAME resolvable base for both sides, so a relative IRI in the
        # record resolves identically and does not read as a change. `.invalid`
        # is reserved (RFC 2606) and can never name a real resource.
        pid = f"http://qa.invalid/{path}"
        before, after = Graph(), Graph()
        if old_text:
            before.parse(data=old_text, format=fmt, publicID=pid)
        after.parse(data=text, format=fmt, publicID=pid)

        added, removed = graph_diff_lines(before, after, work_ns=self.work_ns)
        return {"added": added, "removed": removed, "triples": len(after)}

    # -- discarding ----------------------------------------------------------
    def discard(self, guids) -> dict:
        """Undo everything uncommitted about these records.

        Restore-to-HEAD for what git tracks, delete for what it does not, then
        reconcile binaries — the same three steps in the same order as an
        abandoned session, against a different question: not "where did this
        session start" but "what did the SOT last agree to".
        """
        wanted = set(guids or ())
        drafts, _ = self.list()
        targets = [d for d in drafts if d["guid"] in wanted]
        if not targets:
            return {"discarded": False, "reason": "no such draft", "records": []}

        # Which paths git has an INDEX ENTRY for. A record that has been through
        # a preview is staged, because building a manifest stages the tree.
        staged = set(self.qa.uncommitted_paths()) - set(self.qa.untracked_paths())

        restored, removed, forgotten = [], [], []
        for d in targets:
            for rel in d["files"]:
                full = Path(self.qa.root) / rel
                if self.qa.file_at("HEAD", rel) is None:
                    # It has never been distributed: "back to the last agreed
                    # state" is not existing.
                    try:
                        full.unlink()
                        removed.append(rel)
                    except OSError:
                        pass
                    # AND GIT HAS TO FORGET IT. Deleting the file alone left the
                    # staged addition behind, so `git status` read `AD` and the
                    # draft index — which is derived from git status — went on
                    # listing a record whose file was gone. The discard looked
                    # like it had not worked, and opening the draft it still
                    # offered produced a FileNotFoundError over an empty husk
                    # that invited you to discard it again (Rick, 2026-10-05).
                    if rel in staged:
                        try:
                            self.qa.untrack([rel])
                            forgotten.append(rel)
                        except Exception:
                            pass
                else:
                    self.qa.restore_path("HEAD", rel)
                    restored.append(rel)

        binaries = (self.pointers.reconcile(Path(self.qa.root))
                    if self.pointers is not None else {})
        return {
            "discarded": True,
            "records": [d["label"] for d in targets],
            "removed": sorted(removed),
            "forgotten": sorted(forgotten),
            "restored": sorted(restored),
            "binaries_restored": binaries.get("restored", []),
            "binaries_removed": binaries.get("removed", []),
        }


_PREFIXES = (
    ("vad:", "http://visualartsdna.org/model/"),
    ("ops:", "http://visualartsdna.org/operations/"),
    ("the:", "http://visualartsdna.org/thesaurus/"),
    ("schema:", "https://schema.org/"),
    ("rdfs:", "http://www.w3.org/2000/01/rdf-schema#"),
    ("rdf:", "http://www.w3.org/1999/02/22-rdf-syntax-ns#"),
    ("skos:", "http://www.w3.org/2004/02/skos/core#"),
    ("xsd:", "http://www.w3.org/2001/XMLSchema#"),
)


def _term(x, prefixes=None) -> str:
    """One term, short enough to read in a list.

    A blank node prints as `[ ]` rather than its label: the label is invented by
    the parser and differs between two readings of the same file, so showing it
    would be showing noise and inviting someone to think it meant something.
    """
    from rdflib import BNode, Literal, URIRef

    if isinstance(x, BNode):
        return "[ ]"
    if isinstance(x, Literal):
        dt = f"^^{_term(x.datatype, prefixes)}" if x.datatype else ""
        return f'"{x}"{dt}'
    if isinstance(x, URIRef):
        s = str(x)
        for pre, ns in (prefixes or _PREFIXES):
            if s.startswith(ns):
                return pre + s[len(ns):]
        return f"<{s}>"
    return str(x)


def _triple(t, prefixes=None) -> str:
    return " ".join(_term(x, prefixes) for x in t)


def _sort_key(t):
    return tuple(str(x) for x in t)


# -- pairing blank nodes ------------------------------------------------------
#
# `rdflib.compare.graph_diff` labels a blank node by canonicalising the WHOLE
# graph, so every label in a connected component depends on every triple in it.
# Add one `ops:field` to a profile's template and the template node, all twelve
# existing field nodes and every triple touching them are re-labelled: the
# component comes back twice, 18 removed and 22 added, for a one-field change
# (Rick, 2026-09-19 — "is this the raw rdflib diff?"). It is correct and it is
# unreadable.
#
# A blank node in this data is not anonymous, it is POSITIONAL: it is the
# measurement system of that profile, or the field carrying `schema:video`. So
# it is identified by where it sits — its path from a named subject, plus a
# discriminator among its siblings — and identity then survives a change to a
# sibling. Unchanged structure cancels, and what is left is the edit.
#
# This is also a stronger isomorphism guarantee than it replaces, not a weaker
# one: a file merely re-serialized has the same paths and the same
# discriminators, so it still diffs to nothing.

_MAX_DEPTH = 12


def _content_key(g, node, iris_only: bool = False) -> str:
    """A blank node's own statements, as a string.

    Nested blank nodes are deliberately NOT consulted: including them would make
    a node's identity depend on its children again, which is the problem being
    solved.
    """
    from rdflib import BNode, URIRef

    parts = []
    for pred, obj in sorted(g.predicate_objects(node), key=lambda x: (str(x[0]), str(x[1]))):
        if isinstance(obj, BNode):
            continue
        if iris_only and not isinstance(obj, URIRef):
            continue
        parts.append(f"{pred}={obj}")
    return "|".join(parts)


def _discriminate(g, children) -> dict:
    """How to tell a set of sibling blank nodes apart — with the LEAST content
    that does it.

    This is the part that decides whether an edit reads as an edit. A template
    field's identity is its `ops:property`; if the key included its `ops:order`
    as well, changing one field's position would read as one field removed and
    a different one added. So: the IRI-valued statements first, since those are
    what name a thing, and only fall back to everything when that is not enough
    to tell two siblings apart.
    """
    if len(children) == 1:
        # One child under this predicate: its PATH already identifies it, and
        # any content in the key would be content that cannot then change.
        return {children[0]: ""}
    for iris_only in (True, False):
        keys = {c: _content_key(g, c, iris_only=iris_only) for c in children}
        if len(set(keys.values())) == len(children):
            return keys
    # Genuinely indistinguishable: a stable index over a stable sort.
    ordered = sorted(children, key=lambda c: _content_key(g, c))
    return {c: f"{_content_key(g, c)}#{i}" for i, c in enumerate(ordered)}


def _place_bnodes(g):
    """Every blank node's positional id, and a readable name for it.

    Breadth-first from the named subjects, so a node's id is its PATH: the
    predicate that reaches it, the id of whatever reaches it, and a
    discriminator among the siblings that share both. Siblings that cannot be
    told apart fall back to their position in a sorted order, which is stable
    because the sort key is their own content.
    """
    from rdflib import BNode, URIRef

    ids, names = {}, {}
    frontier = [(s, str(s), 0) for s in sorted(
        {s for s in g.subjects() if isinstance(s, URIRef)}, key=str)]
    seen = set()
    while frontier:
        subject, subject_id, depth = frontier.pop(0)
        if depth > _MAX_DEPTH:
            continue
        by_pred = {}
        for pred, obj in g.predicate_objects(subject):
            if isinstance(obj, BNode):
                by_pred.setdefault(str(pred), []).append(obj)
        for pred, children in by_pred.items():
            local = pred.rsplit("/", 1)[-1].rsplit("#", 1)[-1]
            keys = _discriminate(g, children)
            for child in sorted(children, key=lambda c: keys[c]):
                if child in ids:
                    continue
                ids[child] = f"_:{subject_id}|{pred}|{keys[child]}"
                names[ids[child]] = _bnode_name(g, child, local)
                if child not in seen:
                    seen.add(child)
                    frontier.append((child, ids[child], depth + 1))
    # A blank node no named subject reaches has no position to be known by.
    for node in {s for s in g.subjects() if isinstance(s, BNode)} | {
            o for o in g.objects() if isinstance(o, BNode)}:
        if node not in ids:
            ids[node] = f"_:loose|{_content_key(g, node)}"
            names[ids[node]] = "[ ]"
    return ids, names


def _bnode_name(g, node, path_local: str) -> str:
    """How a blank node reads on the page: what it IS, and which one.

    `[field schema:video]` rather than `[ ]`. The point of the diff is to be
    read, and an anonymous node rendered anonymously tells the reader only that
    something changed somewhere.
    """
    from rdflib import URIRef

    for pred in sorted(g.predicates(node), key=str):
        obj = g.value(node, pred)
        if isinstance(obj, URIRef):
            return f"[{path_local} {_term(obj)}]"
    return f"[{path_local}]"


def _ground(triple, ids):
    return tuple(ids.get(x, x) for x in triple)


def _grounded_line(triple, prefixes, names) -> str:
    return " ".join(
        names.get(x, x) if isinstance(x, str) and x.startswith("_:")
        else _term(x, prefixes)
        for x in triple
    )


def graph_diff_lines(before, after, work_ns: str = "") -> tuple:
    """``(added, removed)`` as readable lines, blank nodes paired by POSITION.

    Public because two callers need the same answer: the per-draft review page,
    and the operator scripts that compare one sandbox against another (which no
    page can do, since a dashboard only knows its own). A second renderer would
    be a second opinion about what changed.
    """
    b_ids, b_desc = _place_bnodes(before)
    a_ids, a_desc = _place_bnodes(after)
    b_set = {_ground(t, b_ids) for t in before}
    a_set = {_ground(t, a_ids) for t in after}
    pre = ((("work:", work_ns),) if work_ns else ()) + _PREFIXES
    names = {**b_desc, **a_desc}
    return (
        [_grounded_line(t, pre, names) for t in sorted(a_set - b_set, key=_sort_key)],
        [_grounded_line(t, pre, names) for t in sorted(b_set - a_set, key=_sort_key)],
    )
