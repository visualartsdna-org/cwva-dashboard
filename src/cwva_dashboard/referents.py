"""What a reference must satisfy — the ONE definition the picker and the gate
both read.

"What the form OFFERS is what the system ENFORCES" is the wired-form contract,
and until now the two halves of it lived in two places: ``_VOCABULARY`` in
``ux/affordance.py`` (what the picker queries) and ``_VOCABULARY_REQUIREMENTS``
in ``promotion/gates.py`` (what the gate checks), kept equal by a comment saying
they must be. That is a promise, not a mechanism. The collision-check bug on
2026-09-06 was exactly this shape — a hand-maintained list that fell behind the
one beside it — so the conditions are defined here once and imported by both.
Picker and gate cannot disagree because there is nothing to keep in agreement.

Each referent names:

- ``property`` — the predicate whose object it constrains.
- ``conditions`` — ``(predicate, object)`` pairs the referent must ALL carry.
  These serve twice: as the picker's query (offer subjects that satisfy them)
  and as the gate's requirement (refuse objects that do not).
- ``source`` — WHERE the referent is declared, which decides what has to be
  loaded to check it. ``vocabulary`` is metacontent (the thesaurus, synced into
  the QA tree); ``content`` is the record store itself, because some referents
  are ordinary records rather than concepts.
"""

from __future__ import annotations

from dataclasses import dataclass

from rdflib import URIRef
from rdflib.namespace import RDF, SKOS

VAD = "http://visualartsdna.org/model/"
THE = "http://visualartsdna.org/thesaurus/"

VOCABULARY = "vocabulary"
CONTENT = "content"


@dataclass(frozen=True)
class Referent:
    name: str
    property: URIRef
    conditions: tuple[tuple[URIRef, URIRef], ...]
    source: str

    def satisfied_by(self, graph, subject) -> bool:
        return all((subject, p, o) in graph for p, o in self.conditions)

    def unmet(self, graph, subject):
        """The first condition ``subject`` fails, or None. Returned rather than
        a bool so the gate can say WHY a reference is dangling."""
        for p, o in self.conditions:
            if (subject, p, o) not in graph:
                return (p, o)
        return None


REFERENTS: dict[str, Referent] = {
    # vad:hasPaper → the picker's own class, deliberately tighter than the
    # skos:Concept superclass (Q5).
    "papers": Referent(
        "papers", URIRef(VAD + "hasPaper"),
        ((RDF.type, URIRef(VAD + "WatercolorPaper")),),
        VOCABULARY,
    ),
    # the:topic (new_entity media) → a concept, and in the topic scheme.
    "topics": Referent(
        "topics", URIRef(THE + "topic"),
        ((RDF.type, SKOS.Concept), (SKOS.inScheme, URIRef(THE + "TopicScheme"))),
        VOCABULARY,
    ),
    # vad:background → a background image. NOT a concept: it is an ordinary
    # entity record (`a the:Image` with `the:topic the:Background`) living in
    # the content store, independent of any work and reusable across many. So
    # its referents are loaded from content, not from the thesaurus — the reason
    # `source` exists at all.
    #
    # The gate previously skipped vad:background as "a work: cross-reference
    # whose integrity is a heavier check, deferred". It was deferred for being
    # undefined, not for being expensive; now that a background has a definite
    # shape, the check is the same two-condition test as any other referent.
    "backgrounds": Referent(
        "backgrounds", URIRef(VAD + "background"),
        ((RDF.type, URIRef(THE + "Image")), (URIRef(THE + "topic"), URIRef(THE + "Background"))),
        CONTENT,
    ),
}

# property → conditions, the gate's view of the same table.
REQUIREMENTS = {r.property: list(r.conditions) for r in REFERENTS.values()}


def by_property(prop: URIRef) -> Referent | None:
    for r in REFERENTS.values():
        if r.property == prop:
            return r
    return None


def names_for(source: str) -> list[str]:
    return sorted(n for n, r in REFERENTS.items() if r.source == source)
