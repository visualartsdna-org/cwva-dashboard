"""Stage 2 — tag the entity with concepts that already exist.

**The agent proposes concepts; the ontology decides the property** (Rick,
decision D). TCAP walks the model to the most specific property whose range
accepts the concept, and records a tie rather than guessing between equals. An
agent that proposed `vad:hasProcess the:FacetedSurface` directly would be
asserting an answer the ontology derives, and the two could disagree silently.

So this stage returns concept URIs and phrases, and `concept.annotate_work`
does the placing — the same tool the Annotate Work page uses, so a DTS-tagged
entity and a hand-annotated work are placed by one implementation.

**Placement and grounding are written together, from the curated list**, which
is the answer to §9.3.1: two writes in one act cannot disagree about which
concepts survived curation.

**Appending, not replacing.** `concept.annotate_work` defaults to replace,
because Annotate Work is an editor; here the curated list is the whole of what
was decided and there is nothing prior to preserve. Replace would bring its
scope rule with it — and scope is what stops a replacement discarding a
concept the picker never offered. Appending has no such hazard and no such
need.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .documents import USER, clean_text, speaker_of, verify_phrase
from .prompts import TAGGING_SYSTEM, tagging_message

__all__ = ["Tag", "TaggingResult", "parse_tags", "tag", "commit_tagging",
           "record_tagging", "derived_here", "reassess_tags"]


@dataclass
class Tag:
    """One concept the model says the criticism substantively discusses."""

    uri: str
    label: str = ""
    confidence: str = ""
    grounding_phrase: str = ""
    grounded: bool = False
    known: bool = True
    source_speaker: str = ""
    #: True when this concept was DERIVED from this very document, and so is
    #: discussed in it by construction.
    derived_here: bool = False
    status: str = ("proposed")   # proposed | derived_here | ungrounded |
                                 # unknown | user_sourced
    notes: list = field(default_factory=list)

    @property
    def include_by_default(self) -> bool:
        """An unknown URI is untickable — tagging chooses from what exists, and
        a concept nobody has is a reference to nothing that the gate has to
        catch. Everything else is offered, ungrounded included, because that is
        a judgement for a curator."""
        return self.known and self.status != "user_sourced"


@dataclass
class TaggingResult:
    entity: str
    document: str
    tags: list = field(default_factory=list)
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error

    def counts(self) -> dict:
        out = {"proposed": 0, "derived_here": 0, "ungrounded": 0,
               "unknown": 0, "user_sourced": 0}
        for t in self.tags:
            out[t.status] = out.get(t.status, 0) + 1
        return out


def derived_here(graph, entity_uri: str) -> list:
    """The concepts this entity's own derivation produced.

    **They should not have to compete for a tagging slot.** A concept derived
    from this document is discussed in it by construction — that is what
    derivation means — and under a tag limit the model ranked them against 250
    pre-existing terms and dropped most of them: `Load path`, `Carole
    (dance)`, `Convex mirror device` and `Line of action` were all derived
    from the Claude criticism and then not tagged on it (Rick, 2026-09-30:
    "The ones with an 'n' didn't even make it into the tagged set?!!").

    Found from the data rather than from a list: a derived concept carries a
    grounding node naming `the:srcEntity`, so the store itself says which
    document produced it. They carry that grounding phrase forward, so the tag
    is evidenced by the same words the concept was.
    """
    from rdflib import URIRef
    from rdflib.namespace import RDFS

    from .grounding import THE

    out = []
    subject = URIRef(str(entity_uri))
    for concept, node in graph.subject_objects(THE.grounding):
        if graph.value(node, THE.srcEntity) != subject:
            continue
        phrase = graph.value(node, THE.phrase)
        label = graph.value(concept, RDFS.label)
        out.append(Tag(uri=str(concept), label=str(label or concept),
                       confidence="high",
                       grounding_phrase=str(phrase) if phrase else "",
                       derived_here=True))
    return sorted(out, key=lambda t: t.label.lower())


def parse_tags(text: str) -> list:
    data = json.loads(re.sub(r"\n?```\s*$", "",
                             re.sub(r"^```(?:json)?\s*\n?", "", str(text).strip())))
    if not isinstance(data, list):
        raise ValueError(f"expected a JSON array of tags, got {type(data).__name__}")
    out = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"element {i} is {type(item).__name__}, not an object")
        uri = str(item.get("uri") or "").strip()
        if not uri:
            continue
        out.append(Tag(uri=uri, label=clean_text(item.get("label") or ""),
                       confidence=str(item.get("confidence") or "").strip().lower(),
                       grounding_phrase=clean_text(item.get("groundingPhrase") or "")))
    return out


def assess_tags(tags, *, document: str, known_uris) -> list:
    """Two checks, both the dashboard's: does the concept exist, and is the
    phrase really in the document."""
    known = set(known_uris or ())
    for t in tags:
        t.known = t.uri in known
        t.grounded = verify_phrase(document, t.grounding_phrase).verified
        t.source_speaker = speaker_of(document, t.grounding_phrase) if t.grounded else ""
        if not t.known:
            t.status = "unknown"
            t.notes.append("no such concept in the store")
        elif not t.grounding_phrase:
            t.status = "ungrounded"
            t.notes.append("the model quoted nothing")
        elif not t.grounded:
            t.status = "ungrounded"
            t.notes.append("the quoted phrase is not in the document")
        elif t.source_speaker == USER:
            t.status = "user_sourced"
            t.notes.append("grounded in the ARTIST's own words, not the critic's")
        elif t.derived_here:
            t.status = "derived_here"
            t.notes.append("derived from this very document, so discussed in it")
        else:
            t.status = "proposed"
    return tags


def tag(dts, *, entity_uri: str, document_name: str, document_text: str,
        existing_block: str, known_uris, limit: int = 0, thesaurus=None) -> TaggingResult:
    """Ask which existing concepts the criticism discusses. Writes nothing.

    The concepts this document's own derivation produced are added to the
    proposal set rather than left to compete for a slot — still curatable,
    like everything else here.
    """
    out = dts.ai.complete(
        "dts_tag",
        system=TAGGING_SYSTEM,
        messages=[{"role": "user", "content": tagging_message(
            f"[Document: {document_name}]\n{document_text}", existing_block,
            limit=limit)}],
    )
    base = TaggingResult(entity=entity_uri, document=document_name, model=out.model,
                         input_tokens=out.input_tokens, output_tokens=out.output_tokens)
    if not out.ok:
        base.error = out.error
        return base
    if out.all_thinking:
        # A distinct failure from a truncated answer, with a distinct remedy.
        base.error = (
            f"the model spent its whole output budget reasoning "
            f"({out.thinking_tokens} thinking tokens) and returned no answer. "
            f"Lower `thinking_budget` or raise `max_tokens` for this task in "
            f"ai_profiles.rson; nothing was written.")
        return base
    if out.truncated:
        base.error = (f"the reply was cut off at {out.output_tokens} output tokens; "
                      "nothing was written")
        return base
    try:
        proposed = parse_tags(out.text)
    except (ValueError, json.JSONDecodeError) as exc:
        base.error = f"the reply was not a usable tag array: {exc}"
        return base
    mine = derived_here(thesaurus, entity_uri) if thesaurus is not None else []
    seen = {t.uri for t in mine}
    merged = mine + [t for t in proposed if t.uri not in seen]
    base.tags = assess_tags(merged, document=document_text,
                            known_uris=set(known_uris) | seen)
    return base


def record_tagging(dts, result, *, entity_path: str,
                   evidence_dir: str = "evidence") -> dict:
    """Stage 2 proposed its tags and is waiting for a curator (queue 4)."""
    dts.expect_stage(entity_path, result.entity, "tagged")
    guid = result.entity.rstrip("/").rsplit("/", 1)[-1]
    agent = str(dts.agent(result.model))
    dts.call("dts.write_evidence", {
        "path": f"{evidence_dir.rstrip('/')}/dts/{guid}/tag.ttl",
        "turtle": tagging_evidence(result, kept=[], dropped=[],
                                   proposed=result.tags, agent=agent),
    })
    return dts.call("dts.stamp", {
        "path": entity_path, "subject": result.entity, "stage": "tagged",
        "by": agent, "by_label": f"{result.model} (DTS tagging)",
    })


def commit_tagging(dts, result, *, included, entity_path: str,
                   evidence_dir: str = "evidence") -> dict:
    """Place the curated tags through TCAP, ground them, record, stamp."""
    dts.expect_stage(entity_path, result.entity, "taggingCurated")
    kept = [t for t in result.tags if t.uri in included]
    dropped = [t for t in result.tags if t.uri not in included]
    if not kept:
        raise ValueError("no tags survived curation; nothing to place")

    placed = dts.call("concept.annotate_work", {
        "subject": result.entity,
        "concepts": [t.uri for t in kept],
        "subject_path": entity_path,
        "replace": False,
    })
    dts.call("dts.ground_entity", {
        "path": entity_path, "subject": result.entity,
        "groundings": [{"concept": t.uri, "phrase": t.grounding_phrase,
                        "verified": t.grounded} for t in kept],
    })
    guid = result.entity.rstrip("/").rsplit("/", 1)[-1]
    agent = str(dts.agent(result.model))
    dts.call("dts.write_evidence", {
        "path": f"{evidence_dir.rstrip('/')}/dts/{guid}/tag.ttl",
        "turtle": tagging_evidence(result, kept=kept, dropped=dropped, agent=agent),
    })
    stamped = dts.call("dts.stamp", {
        "path": entity_path, "subject": result.entity,
        "stage": "taggingCurated", "by": str(dts.curator()),
        "by_label": "the curator",
    })
    return {"kept": [t.label or t.uri for t in kept],
            "dropped": [t.label or t.uri for t in dropped],
            "placed": placed, "stamped": stamped}


def tagging_evidence(result, *, kept, dropped, agent: str, proposed=()) -> str:
    from datetime import datetime, timezone

    from rdflib import BNode, Graph, Literal, Namespace, URIRef
    from rdflib.namespace import RDF, RDFS, XSD

    THE_NS = Namespace("http://visualartsdna.org/thesaurus/")
    PROV_NS = Namespace("http://www.w3.org/ns/prov#")
    OPS = Namespace("http://visualartsdna.org/operations/")
    g = Graph()
    for prefix, ns in (("the", THE_NS), ("prov", PROV_NS), ("ops", OPS), ("rdfs", RDFS)):
        g.bind(prefix, ns)
    run = URIRef(f"{result.entity}#tag")
    g.add((run, RDF.type, OPS.TaggingRun))
    g.add((run, RDFS.label, Literal(f"DTS tagging of {result.document}")))
    g.add((run, OPS.entity, URIRef(result.entity)))
    g.add((run, OPS.document, Literal(result.document)))
    g.add((run, OPS.at, Literal(datetime.now(timezone.utc).isoformat(),
                                datatype=XSD.dateTime)))
    g.add((run, OPS.inputTokens, Literal(result.input_tokens)))
    g.add((run, OPS.outputTokens, Literal(result.output_tokens)))
    if agent:
        g.add((run, PROV_NS.wasAttributedTo, URIRef(agent)))
    for t, outcome in ([(x, "proposed") for x in proposed]
                       + [(x, "kept") for x in kept]
                       + [(x, "rejected") for x in dropped]):
        node = BNode()
        g.add((run, OPS.proposal, node))
        g.add((node, OPS.concept, URIRef(t.uri)))
        g.add((node, RDFS.label, Literal(t.label or t.uri)))
        g.add((node, OPS.outcome, Literal(outcome)))
        g.add((node, OPS.status, Literal(t.status)))
        g.add((node, OPS.grounded, Literal(t.grounded)))
        if t.confidence:
            g.add((node, OPS.confidence, Literal(t.confidence)))
        if t.grounding_phrase:
            g.add((node, THE_NS.phrase, Literal(t.grounding_phrase)))
        for note in t.notes:
            g.add((node, RDFS.comment, Literal(note)))
    return g.serialize(format="turtle")


def reassess_tags(tags, *, known_uris) -> list:
    """Does each concept still exist? Nothing else is recomputed.

    The counterpart of `derive.reassess`, and for the same reason: whether a
    phrase is in the document was settled when the document was readable, and
    re-deriving it against a file that may now be absent would replace a
    finding with a guess.
    """
    known = set(known_uris or ())
    for t in tags:
        t.known = t.uri in known
        if not t.known and t.status != "unknown":
            t.status = "unknown"
            t.notes = [n for n in t.notes if "no such concept" not in n]
            t.notes.append("no such concept in the store")
        elif t.known and t.status == "unknown":
            t.status = "derived_here" if t.derived_here else "proposed"
            t.notes = [n for n in t.notes if "no such concept" not in n]
    return tags
