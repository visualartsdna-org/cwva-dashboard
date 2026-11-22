"""DTS writers — the registry tools the stages compose (law 10).

Every stage of DTS thinks trusted-side and writes here. The division is the
same one the ffprobe probe and the site scrape already use: the effect that
needs the network or the drop folder happens in the orchestrator, and the pure
result is handed to a tool that does the writing under confinement, with the
audit entry and the path chokepoint that come with it.

**These tools write what they are given and decide nothing.** Which concepts
survived curation, which scheme each joins, whether a phrase was verified —
all of that is settled before the call. A tool that re-derived any of it would
be a second opinion able to disagree with the one the curator saw.
"""

from __future__ import annotations

from datetime import datetime, timezone

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, RDFS, SKOS, XSD

from ..dts.grounding import Grounding, Neighbour, attach_grounding
from ..dts.state import (THE, clear_status, read_stamps, status_node,
                         write_stamp)
from .record_tools import bind_standard
from .base import Tool, ToolError

__all__ = ["build_dts_tools"]

PROV = Namespace("http://www.w3.org/ns/prov#")
_VAD = Namespace("http://visualartsdna.org/model/")


def _load(fileops, path: str) -> Graph:
    g = Graph()
    g.parse(data=fileops.read_text(path), format="turtle")
    return g


def _save(fileops, path: str, g: Graph) -> dict:
    # Declare the deployment's prefixes before writing. A record that gained a
    # `vad:` property after it was created has nothing binding the prefix, and
    # rdflib names the namespace itself — `ns1:hasTensegrityPrinciple`, which
    # is valid RDF and unreadable to anyone who knows the vocabulary.
    bind_standard(g)
    res = fileops.write_text(path, g.serialize(format="turtle"), make_parents=True)
    return {"path": res.path, "triples": len(g)}


def _grounding_from(spec: dict) -> Grounding:
    """A grounding as the stage decided it, never as this tool guesses it."""
    return Grounding(
        phrase=str(spec.get("phrase") or ""),
        verified=bool(spec.get("verified")),
        concept_uri=str(spec.get("concept") or ""),
        src_entity=str(spec.get("src_entity") or ""),
        neighbours=[
            Neighbour(uri=str(n["uri"]), label=str(n.get("label") or ""),
                      distance=float(n.get("distance") or 0.0),
                      match_type=str(n.get("match_type") or "fuzzy"))
            for n in (spec.get("near") or [])
        ],
    )


def _write_concepts(fileops, concepts=None, dest=None, src_entity="", agent="",
                    agent_label=""):
    """Stage 1's output: one TTL holding every concept the curator kept.

    One file per derivation run rather than one per concept, because the run
    is what a person reviewed and what a reset has to remove. The filename is
    the entity's guid, so "which concepts came from this document" is a path
    rather than a search.
    """
    if not concepts:
        raise ToolError("nothing_to_write", "no concepts survived curation")
    if not dest:
        raise ToolError("missing_required", "dest (the vocab file path) is required")

    # MERGED into the session's file when one is already there. Writing one
    # file per entity inflates the vocab folder by a file per document
    # forever; a session is what a person means by "a run of DTS" and is the
    # granule they would look for later.
    g = Graph()
    existing = ""
    try:
        existing = fileops.read_text(dest)
    except Exception:
        existing = ""
    if existing:
        g.parse(data=existing, format="turtle")
    before = len(g)
    written = []
    for spec in concepts:
        uri = str(spec.get("uri") or "")
        if not uri:
            raise ToolError("missing_required", f"a concept has no uri: {spec}")
        s = URIRef(uri)
        g.add((s, RDF.type, SKOS.Concept))
        g.add((s, RDFS.label, Literal(str(spec.get("label") or ""))))
        for alt in spec.get("alt_labels") or []:
            g.add((s, SKOS.altLabel, Literal(str(alt))))
        if spec.get("definition"):
            g.add((s, SKOS.definition, Literal(str(spec["definition"]))))
        if spec.get("scope_note"):
            g.add((s, SKOS.scopeNote, Literal(str(spec["scope_note"]))))
        if spec.get("broader"):
            g.add((s, SKOS.broader, URIRef(str(spec["broader"]))))
        if spec.get("scheme"):
            g.add((s, SKOS.inScheme, URIRef(str(spec["scheme"]))))
        # An authoritative reference is `exactMatch` when it is the concept
        # itself and `closeMatch` when it is merely about it — the prompt
        # already draws that line, so the writer honours it rather than
        # flattening both into one predicate.
        if spec.get("exact_match"):
            g.add((s, SKOS.exactMatch, URIRef(str(spec["exact_match"]))))
        if spec.get("close_match"):
            g.add((s, SKOS.closeMatch, URIRef(str(spec["close_match"]))))
        if spec.get("grounding"):
            attach_grounding(g, s, _grounding_from(
                {**spec["grounding"], "src_entity": src_entity}))
        # Law 9: an AI-drafted record says so, and says by what.
        if agent:
            g.add((s, PROV.wasAttributedTo, URIRef(str(agent))))
        written.append(uri)

    # NO INLINE AGENT DECLARATION. The record cites `ops:...` and the
    # operations ontology declares it — the same way a record cites
    # `the:Prestress` without inlining its definition. Inlining was a
    # workaround for an ontology that did not exist; it has existed in both
    # deployments since 2026-10-01.
    #
    # It did three kinds of harm. It made the record a FOUR-SUBJECT file, which
    # fails the one-named-subject rule, so Edit Record would not open a
    # DTS-processed entity and the Drafts page listed it as
    # "<guid>.ttl (4 subjects)" with no way back in (Rick, 2026-10-02: "I don't
    # see either of the Three Graces Criticism entities"). And it typed
    # `ops:user` as a `prov:SoftwareAgent`, while the ontology says
    # `prov:Agent, prov:Person` — so the record asserted that the curator is a
    # piece of software, and under RDFS both held.

    out = _save(fileops, dest, g)
    return {**out, "concepts": written, "count": len(written),
            "merged_into": bool(existing), "added_triples": len(g) - before}


def _ground_entity(fileops, path=None, subject=None, groundings=None):
    """Write one grounding node per tagged concept, on the ENTITY.

    Separate from the TCAP placement (`concept.annotate_work`) but written in
    the same breath by the stage, which is the answer to §9.3.1: placement and
    grounding both come from the curated list, in one act, so the two cannot
    disagree about which concepts survived.

    The node names `the:concept` and not `the:srcEntity`, because the entity
    it hangs from IS the source — the one shape, read from the end it is
    attached to (`dts/grounding.py`).
    """
    if not (path and subject):
        raise ToolError("missing_required", "path and subject are required")
    g = _load(fileops, path)
    subj = URIRef(str(subject))
    # UNDER THE STATUS NODE, not on the entity (Rick, 2026-10-02: "The
    # grounding is meaningless here. Can the grounding be moved under
    # status?"). Twelve `ground verified` nodes hung off the subject put twelve
    # rows of nothing at the top of the criticism page, above the concepts they
    # are evidence for.
    #
    # It is also where they belong: a grounding on the ENTITY is this DTS run's
    # account of why it tagged what it tagged, and `ops:status` is the record
    # of what the run did. A grounding on a CONCEPT is different and stays
    # where it is — that one is about the concept, which is why the vocabulary
    # stayed in `the:` (2026-10-01).
    #
    # It falls out that `clear_status` now takes the groundings with it, so a
    # reset has one less thing to remember.
    owner = status_node(g, subj)
    if owner is None:
        raise ToolError(
            "no_status",
            "this entity has no DTS status node, so there is no run for a "
            "grounding to belong to. Tagging stamps one before curation "
            "writes grounding, so this means the stages ran out of order.")
    # Replace wholesale: this runs once per entity, after curation, and a
    # second set of grounding nodes beside the first would be two answers to
    # "why was this tagged". Both parents are swept, so a record written before
    # the move is corrected by its next curation rather than ending up with a
    # set in each place.
    for parent in (owner, subj):
        for node in list(g.objects(parent, THE.grounding)):
            if isinstance(node, BNode):
                for p2, o2 in list(g.predicate_objects(node)):
                    g.remove((node, p2, o2))
            g.remove((parent, THE.grounding, node))
    for spec in groundings or []:
        attach_grounding(g, owner, _grounding_from(spec))
    out = _save(fileops, path, g)
    return {**out, "groundings": len(groundings or [])}


def _set_summary(fileops, path=None, subject=None, summary=None):
    """Write `the:summary` on the entity, replacing any previous one.

    Replacing rather than adding: RDF is a set, two summaries are two answers
    to one question, and the record carries no way to say which is current.
    Under no-re-runs there is normally nothing to replace — this matters for
    the one case there is, a summary sent back and re-asked at a higher tier.
    """
    if not (path and subject and summary):
        raise ToolError("missing_required", "path, subject and summary are required")
    text = str(summary).strip()
    if not text:
        raise ToolError("empty_summary", "refusing to write an empty summary")
    g = _load(fileops, path)
    subj = URIRef(str(subject))
    g.remove((subj, THE.summary, None))
    g.add((subj, THE.summary, Literal(text)))
    out = _save(fileops, path, g)
    return {**out, "words": len(text.split())}


def _stamp(fileops, path=None, subject=None, stage=None, by="", by_label=""):
    """Record that a DTS stage finished, on the entity's own file."""
    if not (path and subject and stage):
        raise ToolError("missing_required", "path, subject and stage are required")
    g = _load(fileops, path)
    try:
        write_stamp(g, subject, stage, by=by)
    except ValueError as exc:
        raise ToolError("out_of_order", str(exc)) from None
    # NO INLINE AGENT DECLARATION. The record cites `ops:...` and the
    # operations ontology declares it — the same way a record cites
    # `the:Prestress` without inlining its definition. Inlining was a
    # workaround for an ontology that did not exist; it has existed in both
    # deployments since 2026-10-01.
    #
    # It did three kinds of harm. It made the record a FOUR-SUBJECT file, which
    # fails the one-named-subject rule, so Edit Record would not open a
    # DTS-processed entity and the Drafts page listed it as
    # "<guid>.ttl (4 subjects)" with no way back in (Rick, 2026-10-02: "I don't
    # see either of the Three Graces Criticism entities"). And it typed
    # `ops:user` as a `prov:SoftwareAgent`, while the ontology says
    # `prov:Agent, prov:Person` — so the record asserted that the curator is a
    # piece of software, and under RDFS both held.
    out = _save(fileops, path, g)
    return {**out, "stage": stage,
            "stamps": sorted(read_stamps(g, subject))}


def _write_evidence(fileops, path=None, turtle=None):
    """The curator's working record: what was proposed, and what became of it.

    `evidence/` is committed to the QA git and excluded from every manifest,
    so this has history and never reaches the SOT (`promotion/unit.py`). It is
    written as Turtle the caller composed, because what belongs in it differs
    per stage and a tool that imposed a shape would have to be changed for
    each one.
    """
    if not (path and turtle):
        raise ToolError("missing_required", "path and turtle are required")
    if not str(path).startswith("evidence/"):
        raise ToolError(
            "not_evidence",
            f"{path!r} is not under evidence/. This tool writes the curator's "
            "working record, which never converges; a record that should reach "
            "the SOT belongs in a content directory.")
    Graph().parse(data=turtle, format="turtle")  # refuse what will not parse
    res = fileops.write_text(path, turtle, make_parents=True)
    return {"path": res.path}


#: The in-flight proposal caches, one per proposing stage. Under `.qa/`, which
#: is gitignored: they are not a record of anything until a curator has decided.
_STAGE_CACHES = ("derive", "tag", "summarize")


def _reset(fileops, path=None, subject=None, also=None):
    """Back to "entity created" (Rick, round 6).

    Removes the status node and everything DTS wrote on the entity — the
    tags it placed, its groundings, the summary. Files DTS created elsewhere
    (the derived concepts, the evidence) are named by the caller in ``also``
    and trashed, never hard-deleted: nothing hard-deletes what a person's work
    produced (CE_DESIGN §2.3).

    **The in-flight caches go too** (Rick, 2026-10-01). A reset used to leave
    `.qa/dts/<guid>/derive.json` behind, so the entity was back in queue 1 with
    the proposals of the run that was reset still sitting there — reachable
    again the moment the next derive was stamped, and only overwritten if that
    derive got as far as writing. A reset that leaves the previous run's answers
    where the curation screen reads them has not reset the entity.

    Trashed like everything else, not hard-deleted — `FileOps` has no delete,
    which is §2.3 enforced in code rather than asked for. The copy in
    `.qa/trash` costs nothing and is pruned after the next converged promotion.

    It is a promotion unit like any other writer, because some of what it
    removes may already be in the SOT — so the deletions are previewed at the
    review stop and converge only on approval. This is not a quiet cleanup.
    """
    if not (path and subject):
        raise ToolError("missing_required", "path and subject are required")
    g = _load(fileops, path)
    subj = URIRef(str(subject))
    removed = clear_status(g, subj)

    for pred in (THE.summary, THE.grounding):
        for o in list(g.objects(subj, pred)):
            if isinstance(o, BNode):
                for p2, o2 in list(g.predicate_objects(o)):
                    g.remove((o, p2, o2))
                    removed += 1
            g.remove((subj, pred, o))
            removed += 1
    # TCAP placements are `vad:` properties pointing at thesaurus concepts.
    for p, o in list(g.predicate_objects(subj)):
        if str(p).startswith(str(_VAD)) and isinstance(o, URIRef) \
                and str(o).startswith(str(THE)):
            g.remove((subj, p, o))
            removed += 1

    out = _save(fileops, path, g)
    trashed = []
    for rel in also or []:
        try:
            trashed.append(fileops.trash(rel))
        except Exception:  # already gone is the desired state
            continue

    # The guid is the entity file's own name, so the caches are found rather
    # than named by the caller: a reset that depended on being TOLD where they
    # are would miss them exactly when it was run by hand.
    guid = str(path).rsplit("/", 1)[-1].rsplit(".", 1)[0]
    cleared = []
    for stage in _STAGE_CACHES:
        rel = f".qa/dts/{guid}/{stage}.json"
        try:
            fileops.trash(rel)
        except Exception:  # already gone is the desired state
            continue
        cleared.append(rel)

    return {**out, "removed": removed, "trashed": trashed, "cleared": cleared}


def build_dts_tools(layout=None, domain: str = "") -> list:
    vocab_dir = layout.dir("vocab_ttl") if layout is not None else "metacontent/vocab"
    data_dir = layout.dir("work_ttl") if layout is not None else "content/ttl/data"

    return [
        Tool(
            name="dts.write_concepts",
            description=("Write the concepts a derivation produced and a curator "
                         "kept, with their grounding, into one vocabulary TTL."),
            input_schema={
                "type": "object",
                "properties": {
                    "concepts": {"type": "array",
                                 "description": "uri, label, definition, broader, "
                                                "scheme, grounding — as curated."},
                    "dest": {"type": "string",
                             "description": f"Vocabulary TTL path, under {vocab_dir}."},
                    "src_entity": {"type": "string",
                                   "description": "The criticism entity they came from."},
                    "agent": {"type": "string", "description": "prov:SoftwareAgent IRI."},
                    "agent_label": {"type": "string"},
                },
                "required": ["concepts", "dest"],
                "additionalProperties": False,
            },
            handler=_write_concepts,
        ),
        Tool(
            name="dts.ground_entity",
            description=("Write the grounding nodes for an entity's tags — the "
                         "phrase each tagged concept was read from."),
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "subject": {"type": "string"},
                    "groundings": {"type": "array",
                                   "description": "concept, phrase, verified."},
                },
                "required": ["path", "subject", "groundings"],
                "additionalProperties": False,
            },
            handler=_ground_entity,
        ),
        Tool(
            name="dts.set_summary",
            description="Write the entity's `the:summary`, replacing any previous one.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "subject": {"type": "string"},
                    "summary": {"type": "string"},
                },
                "required": ["path", "subject", "summary"],
                "additionalProperties": False,
            },
            handler=_set_summary,
        ),
        Tool(
            name="dts.stamp",
            description=("Record that a DTS stage finished on an entity, with when "
                         "and by whom. Refuses a stage out of order or twice."),
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string",
                             "description": f"The entity's TTL, under {data_dir}."},
                    "subject": {"type": "string", "description": "Entity URI."},
                    "stage": {"type": "string",
                              "enum": ["derived", "derivationCurated", "tagged",
                                       "taggingCurated", "summarized", "summaryCurated"]},
                    "by": {"type": "string", "description": "prov agent IRI."},
                    "by_label": {"type": "string"},
                },
                "required": ["path", "subject", "stage"],
                "additionalProperties": False,
            },
            handler=_stamp,
        ),
        Tool(
            name="dts.write_evidence",
            description=("Write the curator's working record under evidence/ — "
                         "committed to the QA git, never converged to the SOT."),
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Must start with evidence/."},
                    "turtle": {"type": "string"},
                },
                "required": ["path", "turtle"],
                "additionalProperties": False,
            },
            handler=_write_evidence,
        ),
        Tool(
            name="dts.reset",
            description=("Reset an entity's DTS state to 'entity created': remove the "
                         "status node, the placements, the groundings and the summary, "
                         "and trash the files the run produced."),
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "subject": {"type": "string"},
                    "also": {"type": "array",
                             "description": "Files DTS created elsewhere, to trash."},
                },
                "required": ["path", "subject"],
                "additionalProperties": False,
            },
            handler=_reset,
        ),
    ]
