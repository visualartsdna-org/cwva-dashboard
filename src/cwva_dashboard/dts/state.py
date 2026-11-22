"""DTS state: one status node per entity, carrying stamps and provenance.

**The shape is Rick's** (Workflows2_REVIEW §2): the detail lives in a blank node
under ``ops:status`` rather than spraying predicates across the entity, and a
computed ``rdfs:label`` names the current state so a person reading the record
sees "tagged" instead of reconstructing it.

    work:g1 a the:AI ;
        ops:status [
            rdfs:label "tagged" ;
            ops:derived           [ ops:at "…"^^xsd:dateTime ;
                                    prov:wasAttributedTo ops:claude-sonnet-5 ] ;
            ops:derivationCurated [ ops:at "…"^^xsd:dateTime ;
                                    prov:wasAttributedTo ops:user ] ;
            ops:tagged            [ … ] ;
        ] .

**The status node is `ops:`, not `the:`** (Rick, 2026-10-01). It was `the:` for
one sitting, inherited from the review sketch and from the predicate it retires
— `the:conceptsExtracted` — and that was continuity with a mistake rather than
a reason. `the:` is the THESAURUS, where every other member is a `skos:Concept`
in a scheme; a stamp is not a concept, it is the dashboard's record of what it
did to a record. The same argument already moved the agents out of `…/agent/`:
a namespace with no ontology behind it, where nothing said what the terms were.
Eight terms moved — `status`, the six stages, and `at` — and the grounding
vocabulary deliberately did NOT: a grounding is about a concept, so `the:phrase`
and `the:concept` stay in the thesaurus and are declared there (`entity.ttl`).

Four things about this are load-bearing.

**The queue rules key off the STAMPS, never the label.** The label is a
denormalisation — the same fact in two places, able to disagree — so a drifted
label would silently empty or fill a queue. Testing a stamp costs one triple
pattern and cannot be wrong. The label stays because it is what a reader wants,
and because one writer composes the whole node at once.

**Six stamps, and no `entityCreated`** (Rick, round 6). The entity's existence
is the evidence, so stamping it would record what the record already says. An
entity with no status node is therefore queue 1, and — because every triple in
the node is something DTS put there — reset has a one-line definition.

**State and provenance are one structure** (Rick, round 4). Each stamp is
itself a node carrying *when* and *by whom*, so "what happened, when, and who
did it" is never spread across three places. Law 9 wants model identity on
anything a model drafted; a curation stamp names the curator by the same
mechanism. Attribution is an IRI to a `prov:SoftwareAgent` declared in the operations
ontology — and deliberately **never** the user's email address, because these
records converge to a published catalogue.

**The stamp carries an `xsd:dateTime`, where the review sketched `xsd:date`.**
A deliberate deviation, flagged: all six stages of one document are normally
done in a single sitting, so a date cannot order them, and the provenance half
of the same node wants the moment anyway. Nothing depends on the ordering today
— the stage sequence is fixed — which is precisely why it is cheap to record
properly now.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, RDFS, XSD

__all__ = [
    "STAGES", "QUEUES", "Stamp", "THE", "OPS", "PROV",
    "status_node", "read_stamps", "write_stamp", "clear_status",
    "state_of", "queue_of", "label_for", "COMPLETE_LABEL",
    "agent_iri", "curator_iri",
]

THE = Namespace("http://visualartsdna.org/thesaurus/")
PROV = Namespace("http://www.w3.org/ns/prov#")
#: Agents and roles live in the OPERATIONS ontology, which is where the rest
#: of the UI-and-service vocabulary lives (Rick, 2026-09-30). A `…/agent/`
#: namespace existed — `update_work_on_site.py` minted one — but it was a
#: namespace with no ontology behind it: nothing said what an agent was, what
#: roles there are, or which models this deployment uses. `ops:` has all
#: three, so the attribution resolves to something rather than merely
#: parsing.
#:
#: A commons namespace, not a sovereign one: `vad:`, `the:` and `ops:` are
#: shared vocabulary, and only `work:` is per-deployment.
OPS = Namespace("http://visualartsdna.org/operations/")

#: The six stamps, in the order DTS writes them. A stage may not be stamped
#: until its predecessor is, which is what makes "stopped and resumed mid-way"
#: (Rick, decision C) a question about stamps rather than about sessions.
STAGES: tuple[str, ...] = (
    "derived",
    "derivationCurated",
    "tagged",
    "taggingCurated",
    "summarized",
    "summaryCurated",
)

#: What each state is CALLED in the queue surface, keyed by the stamp an entity
#: is waiting for. Queue 0 ("documents to process") is absent on purpose: it is
#: a folder count, not a rule about an entity, because nothing exists yet to
#: carry state (§2.6).
QUEUES: dict[str, str] = {
    "derived": "pending derivation",
    "derivationCurated": "pending derivation curation",
    "tagged": "pending tagging",
    "taggingCurated": "pending tagging curation",
    "summarized": "pending summarization",
    "summaryCurated": "pending summary curation",
}


@dataclass(frozen=True)
class Stamp:
    """One stage, recorded: when it happened and who did it."""

    stage: str
    at: str
    by: str = ""

    @property
    def when(self) -> datetime | None:
        try:
            return datetime.fromisoformat(self.at)
        except (TypeError, ValueError):
            return None


def agent_iri(model: str, domain: str = "") -> URIRef:
    """The `prov:SoftwareAgent` for a model: `ops:<model>`.

    ``domain`` is accepted and ignored — agents are commons vocabulary, not
    per-deployment identity — so callers that used to pass it keep working.
    """
    safe = "".join(c if c.isalnum() or c in "-._" else "-" for c in str(model))
    return OPS[safe]


def curator_iri(domain: str = "") -> URIRef:
    """The person who curated: `ops:user`, named by ROLE and never by identity.

    CE v1 is single-user, so a role identifies them exactly — and these records
    reach a published catalogue, where a name or an address would be a personal
    detail nobody asked to publish. Rick, 2026-09-30: no `ops:rick`, "don't
    want to introduce identity management to ops".
    """
    return OPS["user"]


def status_node(g: Graph, subject) -> BNode | None:
    """The entity's status node, or None if DTS has not touched it."""
    for o in g.objects(URIRef(str(subject)), OPS.status):
        if isinstance(o, BNode):
            return o
    return None


def read_stamps(g: Graph, subject) -> dict[str, Stamp]:
    """Every stamp on the entity, by stage name.

    Tolerant of a stamp written as a plain literal date rather than as a node,
    because that is the shape the design sketch showed and a hand-edited record
    may well carry it. Reading both costs three lines; refusing one of them
    would make a legible record unreadable.
    """
    node = status_node(g, subject)
    if node is None:
        return {}
    out: dict[str, Stamp] = {}
    for stage in STAGES:
        value = g.value(node, OPS[stage])
        if value is None:
            continue
        if isinstance(value, BNode):
            at = g.value(value, OPS.at)
            by = g.value(value, PROV.wasAttributedTo)
            out[stage] = Stamp(stage, str(at) if at is not None else "",
                               str(by) if by is not None else "")
        else:
            out[stage] = Stamp(stage, str(value))
    return out


#: What the status node says when every stage is stamped. A STATE, not the
#: last stage name: "summaryCurated" is the name of an act, and a reader of the
#: record wants to know the record is done rather than to infer it from which
#: act happened to be last (Rick, 2026-10-02).
COMPLETE_LABEL = "curation complete"


def label_for(stamps) -> str:
    """What last happened, for a person reading the record.

    Derived from the stamps every time it is written, never stored and updated
    — which is the only way the denormalisation stays honest. Safe to change
    for exactly that reason: the queue rules read the STAMPS, so no rule
    anywhere depends on the words here.
    """
    present = [s for s in STAGES if s in set(stamps)]
    if len(present) == len(STAGES):
        return COMPLETE_LABEL
    return present[-1] if present else "entity created"


def state_of(g: Graph, subject) -> str:
    """The stage this entity is WAITING FOR, or `"complete"`.

    The queue rule, expressed once. Every surface that asks "what is pending"
    asks this, so a queue cannot disagree with the record it lists.
    """
    stamps = read_stamps(g, subject)
    for stage in STAGES:
        if stage not in stamps:
            return stage
    return "complete"


def queue_of(g: Graph, subject) -> str:
    """The human name of the queue this entity sits in."""
    state = state_of(g, subject)
    return QUEUES.get(state, "complete")


def write_stamp(g: Graph, subject, stage: str, *, by: str = "",
                at: str | None = None) -> BNode:
    """Record that a stage finished, and recompute the label.

    **Refuses a stage out of order**, because DTS has no re-runs and no way to
    express "tagged but never derived": a record that claims one would put the
    entity in a queue whose work was never done. The check is against the
    stamps, so resuming a half-finished document days later is ordinary.

    Re-stamping a stage already stamped is refused for the same reason — the
    error path is `clear_status` and start again (Rick, round 5), not a quiet
    overwrite that loses when it first happened.
    """
    if stage not in STAGES:
        raise ValueError(f"unknown DTS stage {stage!r}; expected one of {STAGES}")
    subj = URIRef(str(subject))
    stamps = read_stamps(g, subj)
    if stage in stamps:
        raise ValueError(
            f"{stage} is already stamped ({stamps[stage].at}). DTS runs once per "
            "entity; to redo it, reset the entity's DTS state and start again."
        )
    expected = state_of(g, subj)
    if stage != expected:
        waiting = "complete" if expected == "complete" else f"waiting for {expected}"
        raise ValueError(
            f"cannot stamp {stage}: this entity is {waiting}. The stages run in "
            f"order ({' -> '.join(STAGES)})."
        )

    node = status_node(g, subj)
    if node is None:
        node = BNode()
        g.add((subj, OPS.status, node))

    moment = at or datetime.now(timezone.utc).isoformat()
    record = BNode()
    g.add((node, OPS[stage], record))
    g.add((record, OPS.at, Literal(moment, datatype=XSD.dateTime)))
    if by:
        g.add((record, PROV.wasAttributedTo, URIRef(str(by))))

    g.remove((node, RDFS.label, None))
    g.add((node, RDFS.label, Literal(label_for(read_stamps(g, subj)))))
    return node


def clear_status(g: Graph, subject) -> int:
    """Remove the whole status node. Returns the number of triples removed.

    **This is only part of a reset** (Rick, round 6: "all the way back to entity
    created"). What DTS also wrote — derived concepts in `vocab/`, the TCAP
    placements and their grounding, the summary, the proposal records in
    `evidence/` — lives elsewhere and is removed by the reset tool, which stages
    those deletions as a promotion unit because some of them may already be in
    the SOT. This function is the part that is purely local to the record.
    """
    subj = URIRef(str(subject))
    node = status_node(g, subj)
    if node is None:
        return 0
    removed = 0
    frontier, seen = [node], set()
    while frontier:
        cur = frontier.pop()
        if cur in seen:
            continue
        seen.add(cur)
        for p, o in list(g.predicate_objects(cur)):
            g.remove((cur, p, o))
            removed += 1
            if isinstance(o, BNode):
                frontier.append(o)
    g.remove((subj, OPS.status, node))
    return removed + 1
