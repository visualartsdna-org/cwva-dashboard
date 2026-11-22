"""Stage 1 — derive concepts from a criticism document.

The division of labour is Workflows2_REVIEW §9.6, and it is what makes this
short: the model proposes, and everything that decides anything is the
dashboard's.

| the model does | the dashboard does |
|---|---|
| read the document, propose concepts with a quoted phrase | verify the phrase is really there |
| write definitions, alt labels, a broader term | decide what is a duplicate (one matcher, CE_DESIGN §6) |
| | compute the neighbourhood the curator reads |
| | compose the grounding node |
| | build the Turtle and write it through a tool |

**Nothing is written here.** The stage returns a proposal set; the curator
includes or excludes; only then does a tool write. That order is the whole
point of "a stage cannot be left until it is curated" (Rick, 2.1), and it is
also what keeps a failed call from leaving half a derivation in the store.

**A proposal with no broader term is an ORPHAN**, and orphans are a modelling
backlog rather than a defect (Rick, round 3). TCAP needs a concept to have
some effective type — its own `vad:` type or one inherited through
`skos:broader` — and 691 of the store's concepts have no `vad:` type of their
own, so a concept with neither can be derived and curated and then never
tagged. Marking it here is what stops that being discovered two stages later.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from dataclasses import dataclass, field

from rdflib import URIRef

from ..concepts.matcher import DEFAULT_THRESHOLD, score
from .documents import USER, clean_text, speaker_of, verify_phrase
from .grounding import Grounding, neighbours
from .pipeline import StageError
from .prompts import EXTRACTION_SYSTEM, extraction_message

__all__ = ["Proposal", "DerivationResult", "parse_proposals", "assess", "derive",
           "mint_uri", "commit_derivation", "evidence_turtle", "reassess"]

#: What the model may say about its own confidence. Recorded, never acted on:
#: the curator decides, and a model's self-report is not evidence (the same
#: reason competency is measured by replay and not by self-assessment).
_CONFIDENCE = ("high", "medium", "low")

_CATEGORIES = ("formal", "contextual", "production")


@dataclass
class Proposal:
    """One concept the model proposed, and everything the dashboard decided."""

    label: str
    definition: str = ""
    category: str = "formal"
    alt_labels: list = field(default_factory=list)
    broader_label: str = ""
    broader_uri: str = ""
    confidence: str = ""
    wikipedia_url: str = ""
    close_match_url: str = ""
    scope_note: str = ""
    grounding_phrase: str = ""

    # -- the dashboard's findings, not the model's ------------------------
    grounded: bool = False
    duplicate_of: str = ""
    duplicate_label: str = ""
    duplicate_score: float = 0.0
    near: list = field(default_factory=list)
    orphan: bool = False
    #: Does the authoritative reference look like it is ABOUT this concept?
    #: The prompt requires one — "if you cannot find a Wikipedia article for a
    #: concept, it is probably not an established term" — and nothing checked
    #: that the article was the concept's. Five of one real run's twelve cited
    #: a generic page: `Grace under tension` -> /Tensegrity, `Rotation as
    #: verification` -> /Kinetic_art. The rule was satisfied in letter and the
    #: signal it exists to give — "this is an established term" — was not.
    reference_fits: bool = True
    reference_title: str = ""
    #: Whose turn the grounding phrase came from. A criticism export is a
    #: conversation and the two sides are not interchangeable evidence.
    source_speaker: str = ""
    status: str = ("proposed")   # proposed | duplicate | ungrounded |
                                 # user_sourced | orphan
    notes: list = field(default_factory=list)

    @property
    def include_by_default(self) -> bool:
        """What the curation screen ticks before a person touches it.

        A duplicate is untickable — it would create a second concept for a
        thing the store already has. A concept grounded in the ARTIST's own
        turn is untickable by default for a different reason (Rick,
        2026-09-30: "Concepts originating from my text contributions I tend to
        leave out") — "tend to", so it can be pulled back in by naming it, but
        the default follows the practice. Everything else is offered, the
        ungrounded and the orphaned included, because those are judgements and
        a hidden proposal is one nobody can judge.
        """
        return self.status not in ("duplicate", "user_sourced")


@dataclass
class DerivationResult:
    """What one derivation run produced, before anyone curates it."""

    entity: str
    document: str
    proposals: list = field(default_factory=list)
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    scheme: dict = field(default_factory=dict)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error

    def counts(self) -> dict:
        out = {"proposed": 0, "duplicate": 0, "ungrounded": 0,
               "user_sourced": 0, "orphan": 0}
        for p in self.proposals:
            out[p.status] = out.get(p.status, 0) + 1
        return out


def _strip_fences(text: str) -> str:
    """Models still occasionally wrap JSON in a code fence despite being asked
    not to, and the agent stripped them for the same reason."""
    text = re.sub(r"^```(?:json)?\s*\n?", "", str(text).strip())
    return re.sub(r"\n?```\s*$", "", text)


def parse_proposals(text: str) -> list:
    """The model's JSON array, as typed proposals.

    Raises on anything that is not a list of objects — law 8 wants structure
    asserted, and a stage that silently accepted a string would report zero
    concepts rather than a broken reply.
    """
    data = json.loads(_strip_fences(text))
    if not isinstance(data, list):
        raise ValueError(f"expected a JSON array of concepts, got {type(data).__name__}")
    out = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"element {i} is {type(item).__name__}, not an object")
        label = clean_text(item.get("label") or "")
        if not label:
            continue  # a proposal with no label is not a proposal
        category = str(item.get("category") or "formal").strip().lower()
        out.append(Proposal(
            label=label,
            # Every literal that reaches a record is cleaned HERE, at the one
            # boundary where text from a document or a model becomes data.
            definition=clean_text(item.get("definition") or ""),
            category=category if category in _CATEGORIES else "formal",
            alt_labels=[c for c in (clean_text(a) for a in (item.get("altLabels") or [])) if c],
            broader_label=clean_text(item.get("broaderLabel") or ""),
            broader_uri=str(item.get("broaderURI") or "").strip(),
            confidence=(str(item.get("confidence") or "").strip().lower()
                        if str(item.get("confidence") or "").strip().lower() in _CONFIDENCE
                        else ""),
            wikipedia_url=str(item.get("wikipediaUrl") or "").strip(),
            close_match_url=str(item.get("closeMatchUrl") or "").strip(),
            scope_note=clean_text(item.get("scopeNote") or ""),
            grounding_phrase=clean_text(item.get("groundingPhrase") or ""),
        ))
    return out


#: How close the reference's title must be to the label to count as being
#: about it. Well below the dedup threshold on purpose: "Gesture in art" for
#: "Gestural differentiation" is the citation working, and an exact match is
#: not what a real encyclopaedia article title looks like.
REFERENCE_THRESHOLD = 0.45


def _reference_check(p) -> tuple:
    """Is the cited article plausibly about the proposed concept?

    A lexical check on the URL's own title, not a fetch: the confined worker
    could not fetch it, the trusted side should not fetch 12 pages per
    derivation, and the failure this catches is visible without leaving the
    room — a concept named `Grace under tension` citing `/wiki/Tensegrity`.

    Reported, never a rejection. A curator who knows the term is established
    keeps it; this only stops the citation being mistaken for evidence.
    """
    url = p.wikipedia_url or p.close_match_url
    if not url:
        return "", True  # nothing cited is a different finding, and not this one
    tail = str(url).rstrip("/").rsplit("/", 1)[-1]
    title = tail.replace("_", " ").split("#")[0].strip()
    if not title:
        return "", True
    # A parenthetical disambiguator is the encyclopaedia's, not the concept's.
    bare = re.sub(r"\s*\([^)]*\)\s*$", "", title)
    best = max(score(p.label, bare), score(p.label, title),
               *(score(a, bare) for a in p.alt_labels or [""]))
    return title, best >= REFERENCE_THRESHOLD


def assess(proposals, *, document: str, label_index: dict,
           threshold: float = DEFAULT_THRESHOLD, thesaurus=None) -> list:
    """Everything the dashboard decides about a proposal. Pure.

    Order matters. A duplicate is settled first, because a concept the store
    already has needs no grounding judgement and no orphan warning — showing
    a curator three findings about a proposal they cannot accept is noise.
    """
    for p in proposals:
        best_uri, best_label, best = "", "", 0.0
        for uri, names in (label_index or {}).items():
            for name in names:
                s = score(p.label, name)
                if s > best:
                    best_uri, best_label, best = uri, name, s
        # An alt label the model proposed can collide too, and a concept whose
        # SYNONYM already exists is the same concept under another name.
        for alt in p.alt_labels:
            for uri, names in (label_index or {}).items():
                for name in names:
                    s = score(alt, name)
                    if s > best:
                        best_uri, best_label, best = uri, name, s

        if best >= threshold:
            p.status = "duplicate"
            p.duplicate_of, p.duplicate_label, p.duplicate_score = (
                best_uri, best_label, round(best, 4))
            p.notes.append(
                f"the store already has {best_label!r} at {best:.2f}")
            continue

        p.near = neighbours(p.label, label_index)
        p.grounded = verify_phrase(document, p.grounding_phrase).verified
        p.source_speaker = speaker_of(document, p.grounding_phrase) if p.grounded else ""
        # ORPHAN means "TCAP cannot place it", which is a question about
        # whether the parent RESOLVES, not about whether one was named. A
        # broader term the model invented reads as a parent and behaves as
        # none: the concept gets no `skos:broader`, inherits no type, and is
        # discovered to be untaggable two stages later. Checked here when the
        # thesaurus is available, which is every real run.
        p.orphan = not (p.broader_uri or p.broader_label)
        if not p.orphan and thesaurus is not None:
            from .thesaurus import resolve_broader

            if not resolve_broader(thesaurus, p.broader_uri, p.broader_label):
                p.orphan = True
                p.notes.append(
                    f"its broader term {p.broader_label or p.broader_uri!r} is "
                    "not in the thesaurus")

        p.reference_title, p.reference_fits = _reference_check(p)
        if not p.reference_fits:
            p.notes.append(
                f"its reference is {p.reference_title!r}, which is not this "
                "concept — the citation does not show the term is established")

        if not p.grounding_phrase:
            p.status = "ungrounded"
            p.notes.append("the model quoted nothing")
        elif not p.grounded:
            p.status = "ungrounded"
            p.notes.append("the quoted phrase is not in the document")
        elif p.source_speaker == USER:
            p.status = "user_sourced"
            p.notes.append(
                "grounded in the ARTIST's own words, not the critic's — the "
                "critic picked the association up rather than making it")
        elif p.orphan:
            p.status = "orphan"
            p.notes.append(
                "no broader term, so TCAP cannot place it — a modelling task, "
                "not a defect")
        else:
            p.status = "proposed"
    return proposals


def derive(dts, *, entity_uri: str, document_name: str, document_text: str,
           existing_block: str, scheme: dict, label_index: dict,
           scope: str = "all", limit: int = 0, thesaurus=None) -> DerivationResult:
    """Ask for concepts, then decide about them. Writes nothing."""
    scope_instruction = (
        "Extract concepts in ALL categories: formal analysis, contextual "
        "analysis, and production terms."
        if scope == "all" else
        f"Extract concepts in the {scope} category ONLY."
    )
    out = dts.ai.complete(
        "dts_derive",
        system=EXTRACTION_SYSTEM,
        messages=[{"role": "user", "content": extraction_message(
            f"[Document: {document_name}]\n{document_text}",
            existing_block, scope_instruction=scope_instruction, limit=limit)}],
    )
    base = DerivationResult(entity=entity_uri, document=document_name,
                            model=out.model, scheme=scheme,
                            input_tokens=out.input_tokens,
                            output_tokens=out.output_tokens)
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
        # Said as what it is. A truncated reply is broken JSON, and a parser
        # reporting "not a usable concept array" sends a person to look at the
        # prompt when the remedy is the cap or a `limit`.
        base.error = (
            f"the reply was cut off at {out.output_tokens} output tokens "
            f"(max_tokens for this task). Raise the cap in ai_profiles.rson or "
            f"pass a limit; nothing was written."
        )
        return base
    try:
        proposals = parse_proposals(out.text)
    except (ValueError, json.JSONDecodeError) as exc:
        base.error = f"the reply was not a usable concept array: {exc}"
        return base
    base.proposals = assess(proposals, document=document_text,
                            label_index=label_index, thesaurus=thesaurus)
    return base


def mint_uri(label: str, *, namespace: str) -> str:
    """A concept URI from its label, PascalCase, as the store already does.

    Deterministic on purpose: the same label proposed twice mints the same
    URI, so a second derivation that re-proposes a concept collides with the
    first rather than creating a twin nobody notices. "Selective focus"
    becomes `the:SelectiveFocus`, matching the convention across the 921
    concepts already there.
    """
    # Split on every non-alphanumeric run, so each word capitalises before
    # the punctuation is dropped. The agent split on whitespace and hyphens
    # only and stripped punctuation afterwards, which turned "Line of action
    # (mechanics)" into `LineOfActionmechanics`.
    #
    # A parenthetical qualifier is FOLDED IN rather than dropped. The store
    # does both by hand — `Cable (Tension Member)` is `Cable`, `Masking
    # (digital)` is `maskingDigital` — and dropping is the one a machine must
    # not choose: it is exactly how "Line of action (mechanics)" would land on
    # top of an existing `LineOfAction` that means something else.
    #
    # An initial capital is FORCED, never `capitalize()`, which lowercases the
    # rest and would turn `GLB` into `Glb`.
    words = [w for w in re.split(r"[^A-Za-z0-9]+", str(label)) if w]
    pascal = "".join(w[:1].upper() + w[1:] for w in words)
    if not pascal:
        raise ValueError(f"{label!r} yields no usable local name")
    return f"{str(namespace).rstrip('/')}/{pascal}"


def record_derivation(dts, result, *, entity_path: str,
                      evidence_dir: str = "evidence") -> dict:
    """Stage 1 is DONE: the proposals exist and are waiting for a curator.

    **Two stamps per stage, because there are two stopping points** (Rick,
    2.1). Writing the concepts and stamping `derived` in one act would collapse
    queues 1 and 3 and leave "pending derivation curation" permanently empty —
    which is what the state machine caught the first time tagging ran.

    So derivation writes the PROPOSAL RECORD and stamps `derived`; nothing
    reaches the vocabulary until a curator has decided. The entity is now in
    queue 2, visible as work someone has to look at, and that is true whether
    the curator arrives in a minute or next week.
    """
    dts.expect_stage(entity_path, result.entity, "derived")
    guid = result.entity.rstrip("/").rsplit("/", 1)[-1]
    agent = str(dts.agent(result.model))
    dts.call("dts.write_evidence", {
        "path": f"{evidence_dir.rstrip('/')}/dts/{guid}/derive.ttl",
        "turtle": evidence_turtle(result, kept=[], dropped=[],
                                  proposed=result.proposals, concepts=[],
                                  agent=agent),
    })
    return dts.call("dts.stamp", {
        "path": entity_path, "subject": result.entity, "stage": "derived",
        "by": agent, "by_label": f"{result.model} (DTS derivation)",
    })


def commit_derivation(dts, result, *, included, entity_path: str, vocab_dir: str,
                      thesaurus, scheme_table: dict, prefixes: dict,
                      namespace: str, evidence_dir: str = "evidence",
                      vocab_name: str = "") -> dict:
    """Write what the curator kept, record what they saw, and stamp the stage.

    Three writes and one stamp, in that order, all through registry tools —
    and NOTHING is written before this, which is what makes an abandoned
    curation leave no trace.

    ``included`` is the set of labels the curator kept. Everything proposed is
    recorded in the evidence, kept or not, with the reason: a rejection that
    leaves nothing behind cannot be reconstructed, and the next run would
    re-propose it (Rick, 10.7).
    """
    from .thesaurus import scheme_for_concept

    dts.expect_stage(entity_path, result.entity, "derivationCurated")
    kept, dropped = [], []
    for p in result.proposals:
        (kept if p.label in included else dropped).append(p)

    concepts = []
    for p in kept:
        minted = mint_uri(p.label, namespace=namespace)
        if (URIRef(minted), None, None) in thesaurus:
            # The URI is deterministic, so this means the store already holds
            # a concept this label would mint onto — a duplicate dedup did not
            # score at the threshold, e.g. a different label with the same
            # PascalCase. Refused rather than merged: silently adding triples
            # to somebody else's concept is the worst available outcome.
            raise StageError(
                f"{p.label!r} mints {minted}, which already exists. Exclude it, "
                f"or give it a label that does not collide.")
        scheme, how = scheme_for_concept(
            thesaurus, broader_uri=p.broader_uri, broader_label=p.broader_label,
            fallback=(scheme_table or {}).get(p.category, ""), prefixes=prefixes)
        from .thesaurus import resolve_broader

        broader = resolve_broader(thesaurus, p.broader_uri, p.broader_label)
        concepts.append({
            "uri": minted,
            "label": p.label,
            "alt_labels": p.alt_labels,
            "definition": p.definition,
            "scope_note": p.scope_note,
            "broader": broader,
            "scheme": scheme,
            "exact_match": p.wikipedia_url,
            "close_match": p.close_match_url,
            "grounding": {
                "phrase": p.grounding_phrase,
                "verified": p.grounded,
                "near": [{"uri": n.uri, "label": n.label, "distance": n.distance,
                          "match_type": n.match_type} for n in p.near],
            },
            "_scheme_rule": how,
        })

    guid = result.entity.rstrip("/").rsplit("/", 1)[-1]
    agent = str(dts.agent(result.model))
    written = {}
    if concepts:
        written = dts.call("dts.write_concepts", {
            "concepts": [{k: v for k, v in c.items() if not k.startswith("_")}
                         for c in concepts],
            "dest": f"{vocab_dir.rstrip('/')}/{vocab_name or f'dts-{guid}.ttl'}",
            "src_entity": result.entity,
            "agent": agent,
            "agent_label": f"{result.model} (DTS derivation)",
        })

    # The evidence is REWRITTEN with the outcomes, replacing the record
    # derivation left. One file per run per stage: what was proposed and what
    # became of it is one account, not two that have to be read together.
    dts.call("dts.write_evidence", {
        "path": f"{evidence_dir.rstrip('/')}/dts/{guid}/derive.ttl",
        "turtle": evidence_turtle(result, kept=kept, dropped=dropped,
                                  concepts=concepts, agent=agent),
    })
    # Attributed to the CURATOR, not the model: this stamp records a human
    # decision, and law 9 wants the identity of whoever did the thing.
    stamped = dts.call("dts.stamp", {
        "path": entity_path, "subject": result.entity,
        "stage": "derivationCurated", "by": str(dts.curator()),
        "by_label": "the curator",
    })
    return {"kept": [p.label for p in kept], "dropped": [p.label for p in dropped],
            "written": written, "stamped": stamped, "concepts": concepts}


def evidence_turtle(result, *, kept, dropped, concepts, agent: str,
                    proposed=()) -> str:
    """What was proposed and what became of it — the curator's record.

    **Rejections are recorded as rejections** (Rick, 10.7), not left as an
    absence. Three things follow from that: a later run can be told not to
    re-propose them, the record shows that a person considered them, and the
    reasoning survives a question asked six months later. None of it is
    reconstructable afterwards, which is why it is written on the first run
    rather than added when someone wants it.

    It lives in `evidence/`, committed to the QA git and excluded from every
    manifest, so it has history and never reaches the published catalogue.
    """
    from rdflib import BNode, Graph, Literal, Namespace
    from rdflib.namespace import RDF, RDFS, XSD

    THE_NS = Namespace("http://visualartsdna.org/thesaurus/")
    PROV_NS = Namespace("http://www.w3.org/ns/prov#")
    OPS = Namespace("http://visualartsdna.org/operations/")

    g = Graph()
    g.bind("the", THE_NS)
    g.bind("prov", PROV_NS)
    g.bind("ops", OPS)
    g.bind("rdfs", RDFS)

    run = URIRef(f"{result.entity}#derive")
    g.add((run, RDF.type, OPS.DerivationRun))
    g.add((run, RDFS.label, Literal(f"DTS derivation of {result.document}")))
    g.add((run, OPS.entity, URIRef(result.entity)))
    g.add((run, OPS.document, Literal(result.document)))
    g.add((run, OPS.at, Literal(datetime.now(timezone.utc).isoformat(),
                                datatype=XSD.dateTime)))
    if agent:
        g.add((run, PROV_NS.wasAttributedTo, URIRef(agent)))
    g.add((run, OPS.inputTokens, Literal(result.input_tokens)))
    g.add((run, OPS.outputTokens, Literal(result.output_tokens)))

    minted = {c["label"]: c for c in concepts}
    # Before curation every proposal is simply "proposed"; afterwards each is
    # kept or rejected. The same file, rewritten, so the history of one run is
    # one account rather than two a reader has to reconcile.
    for proposal, outcome in ([(p, "proposed") for p in proposed]
                              + [(p, "kept") for p in kept]
                              + [(p, "rejected") for p in dropped]):
        node = BNode()
        g.add((run, OPS.proposal, node))
        g.add((node, RDFS.label, Literal(proposal.label)))
        g.add((node, OPS.outcome, Literal(outcome)))
        g.add((node, OPS.status, Literal(proposal.status)))
        if proposal.definition:
            g.add((node, OPS.definition, Literal(proposal.definition)))
        if proposal.grounding_phrase:
            g.add((node, THE_NS.phrase, Literal(proposal.grounding_phrase)))
        g.add((node, OPS.grounded, Literal(proposal.grounded)))
        # The broader term the agent WANTED, which is the whole value of an
        # orphan entry to the thesaurus-modelling task it feeds (§9.5).
        if proposal.broader_label:
            g.add((node, OPS.broaderWanted, Literal(proposal.broader_label)))
        if proposal.duplicate_of:
            g.add((node, OPS.duplicateOf, URIRef(proposal.duplicate_of)))
            g.add((node, OPS.distance, Literal(proposal.duplicate_score,
                                               datatype=XSD.float)))
        for note in proposal.notes:
            g.add((node, RDFS.comment, Literal(note)))
        spec = minted.get(proposal.label)
        if spec:
            g.add((node, OPS.minted, URIRef(spec["uri"])))
            if spec.get("scheme"):
                g.add((node, OPS.scheme, URIRef(spec["scheme"])))
            g.add((node, OPS.schemeRule, Literal(spec.get("_scheme_rule", ""))))
    return g.serialize(format="turtle")


def reassess(proposals, *, label_index: dict, thesaurus=None,
             threshold: float = DEFAULT_THRESHOLD) -> list:
    """Update only what depends on the STORE, leaving the document findings be.

    Curating a batch moves the store underneath the proposals: Rick curated one
    Three Graces criticism, which minted `the:ThreeGraces`, and the other
    document's proposal for the same concept was still marked `proposed` from
    derive time — so the submit hit the mint-collision guard (2026-10-01).

    **Deliberately NOT a full re-assessment.** `assess` also recomputes
    grounding and speaker, which depend on the DOCUMENT, and a document can be
    absent by the time a curator arrives — so re-deriving those would turn a
    verified proposal into an unverified one on the strength of a missing file.
    Those findings were made when the document was definitely readable, and
    they are kept. What the store can change is what gets recomputed: whether
    something is now a duplicate, what it sits near, and whether its parent
    resolves.
    """
    from .thesaurus import resolve_broader

    for p in proposals:
        # A finding about the DOCUMENT stands. Only a store-derived status is
        # recomputed, so "the model quoted nothing" is not quietly replaced by
        # "this is fine" because the store moved.
        document_finding = p.status in ("ungrounded", "user_sourced")
        kept_notes = [n for n in p.notes
                      if "store already has" not in n and "broader term" not in n]

        best_uri, best_label, best = "", "", 0.0
        for candidate in [p.label, *p.alt_labels]:
            for uri, names in (label_index or {}).items():
                for name in names:
                    sc = score(candidate, name)
                    if sc > best:
                        best_uri, best_label, best = uri, name, sc
        p.duplicate_of, p.duplicate_label, p.duplicate_score = "", "", 0.0
        p.notes = kept_notes
        if best >= threshold:
            p.status = "duplicate"
            p.duplicate_of, p.duplicate_label = best_uri, best_label
            p.duplicate_score = round(best, 4)
            p.notes = kept_notes + [f"the store already has {best_label!r} at {best:.2f}"]
            continue

        p.near = neighbours(p.label, label_index)
        p.orphan = not (p.broader_uri or p.broader_label)
        if not p.orphan and thesaurus is not None and not resolve_broader(
                thesaurus, p.broader_uri, p.broader_label):
            p.orphan = True
            p.notes = kept_notes + [
                f"its broader term {p.broader_label or p.broader_uri!r} is not "
                "in the thesaurus"]
        if document_finding:
            continue  # the document had the last word on this one
        p.status = "orphan" if p.orphan else "proposed"
    return proposals
