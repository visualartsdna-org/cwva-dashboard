"""Recovering a grounding's context from what the store actually holds.

The grounding node stores the PHRASE and not the surrounding sentences, so
that a slice of every criticism document is not copied into every concept it
produced, where it would drift the moment the document was replaced. Rick
accepted that "as long as it is reasonably recoverable" (2026-09-29), so
recovery is a function with tests rather than an assumption.

**The chain is three hops and every link is already in the store.** A
grounding on a concept names `the:srcEntity`; that entity carries
`the:mdDocument`, an IRI under the documents base; the placement map turns the
documents base into a sandbox directory. A grounding on an entity is one hop
shorter, because the entity it hangs from IS the source.

**A document that has since changed is reported, not guessed at.** If the
phrase is no longer there the answer says so, which is the honest outcome and
the same signal a not-found grounding carries from the start — better than a
window of arbitrary text that looks like evidence.
"""

from __future__ import annotations

from dataclasses import dataclass

from rdflib import BNode, Graph, URIRef
from rdflib.namespace import RDFS

from .documents import context_around
from .grounding import THE
from .state import OPS

__all__ = ["Recovered", "recover_context", "source_document"]


@dataclass(frozen=True)
class Recovered:
    """A grounding, re-joined to the words it came from."""

    phrase: str
    concept: str = ""
    entity: str = ""
    document: str = ""
    context: str = ""
    found: bool = False
    reason: str = ""


def source_document(g: Graph, entity, *, docs_base: str, docs_dir: str) -> str:
    """The sandbox-relative path of an entity's markdown, or "".

    Derived from the record and the placement map rather than from a
    convention: a document IRI is `{documents base}{name}`, and where that
    lands in the tree is the active target's business (CE_DESIGN §3.6).
    """
    iri = g.value(URIRef(str(entity)), THE.mdDocument)
    if iri is None:
        return ""
    name = str(iri)
    base = str(docs_base)
    name = name[len(base):] if name.startswith(base) else name.rsplit("/", 1)[-1]
    return f"{str(docs_dir).rstrip('/')}/{name}"


def recover_context(g: Graph, node, read_text, *, docs_base: str, docs_dir: str,
                    chars: int = 240) -> Recovered:
    """Put one grounding node back in front of the sentences it came from.

    ``read_text`` is a callable taking a sandbox-relative path — `FileOps.
    read_text` in the dashboard, anything in a test. Passed in rather than
    reached for, so this stays a pure function of the store plus one reader.
    """
    phrase = g.value(node, THE.phrase)
    phrase = str(phrase) if phrase is not None else ""
    concept = g.value(node, THE.concept)
    src = g.value(node, THE.srcEntity)

    # Which end the node hangs from decides which hop is needed — the same
    # rule that composes it (`grounding.attach_grounding`), read backwards.
    owner = next((s for s in g.subjects(THE.grounding, node)), None)
    # ONE HOP FURTHER when the owner is a status node. Entity-side groundings
    # moved under `ops:status` (2026-10-02), so the thing holding them is a
    # blank node, and asking IT for a markdown document finds nothing — the
    # context would have gone quietly missing on every curation screen. Records
    # written before the move still hang them on the entity, so both shapes are
    # read.
    if isinstance(owner, BNode):
        owner = next((s for s in g.subjects(OPS.status, owner)), owner)
    entity = src if src is not None else owner
    concept = concept if concept is not None else owner

    if entity is None:
        return Recovered(phrase=phrase, concept=str(concept or ""),
                         reason="the grounding names no source entity")

    path = source_document(g, entity, docs_base=docs_base, docs_dir=docs_dir)
    if not path:
        return Recovered(phrase=phrase, concept=str(concept or ""),
                         entity=str(entity),
                         reason="the source entity cites no markdown document")
    try:
        text = read_text(path)
    except Exception as exc:
        return Recovered(phrase=phrase, concept=str(concept or ""),
                         entity=str(entity), document=path,
                         reason=f"the document could not be read ({exc})")

    context = context_around(text, phrase, chars=chars)
    if not context:
        # Said plainly rather than papered over. A grounding written as
        # verified whose phrase is now absent means the document changed
        # underneath it, and that is worth seeing.
        was = g.value(node, RDFS.label)
        return Recovered(phrase=phrase, concept=str(concept or ""),
                         entity=str(entity), document=path,
                         reason=("the phrase is not in the document as it now "
                                 "stands" + (" (it was recorded as "
                                             f"{str(was)!r})" if was else "")))
    return Recovered(phrase=phrase, concept=str(concept or ""),
                     entity=str(entity), document=path, context=context,
                     found=True)
