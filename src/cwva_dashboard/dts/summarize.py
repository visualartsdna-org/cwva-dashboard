"""Stage 3 — one paragraph a reader can decide from.

**Its curation is a different act from the other two** (Rick, 2.1a). There is
nothing to include or exclude in a single paragraph, so the screen is accept
or send it back — which is also the natural home for the one exception the
no-re-runs rule anticipates, re-asking at a higher cost tier after a cheap
first pass.

The prompt carries two rules that are the accumulated tuning and must not be
lost. The **recency rule**: a criticism session evolves, the artist may revise
the work mid-document and ask for a re-review, and physical descriptions from
before the last update signal are obsolete. The **grounding rule**: the model
has not seen the artwork, so every claim must be traceable to what the critic
wrote — "an eloquent summary containing invented imagery is worthless".

The dashboard's own check is length, because the prompt states a hard limit
and a summary that overruns it was not written to the brief.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .documents import clean_text
from .prompts import SUMMARY_SYSTEM, summary_message

__all__ = ["SummaryResult", "summarize", "record_summary", "commit_summary",
           "MAX_WORDS"]

#: What the prompt asks for: "EXACTLY ONE paragraph, NO MORE THAN 150 WORDS".
#: Checked rather than trusted — not to reject, but so a curator reading it
#: knows before they read whether it answered the brief.
MAX_WORDS = 150


@dataclass
class SummaryResult:
    entity: str
    document: str
    summary: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    error: str = ""
    notes: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.error

    @property
    def words(self) -> int:
        return len(self.summary.split())

    @property
    def paragraphs(self) -> int:
        return len([p for p in self.summary.split("\n\n") if p.strip()])


def summarize(dts, *, entity_uri: str, document_name: str,
              document_text: str) -> SummaryResult:
    out = dts.ai.complete(
        "dts_summarize",
        system=SUMMARY_SYSTEM,
        messages=[{"role": "user", "content": summary_message(
            f"[Document: {document_name}]\n{document_text}")}],
    )
    res = SummaryResult(entity=entity_uri, document=document_name, model=out.model,
                        input_tokens=out.input_tokens, output_tokens=out.output_tokens)
    if not out.ok:
        res.error = out.error
        return res
    if out.all_thinking:
        # A distinct failure from a truncated answer, with a distinct remedy.
        res.error = (
            f"the model spent its whole output budget reasoning "
            f"({out.thinking_tokens} thinking tokens) and returned no answer. "
            f"Lower `thinking_budget` or raise `max_tokens` for this task in "
            f"ai_profiles.rson; nothing was written.")
        return res
    if out.truncated:
        res.error = (f"the reply was cut off at {out.output_tokens} output tokens; "
                     "nothing was written")
        return res
    res.summary = clean_text(out.text)
    if not res.summary:
        res.error = "the model returned nothing"
        return res
    # Reported, never rejected: the curator decides, and a 160-word paragraph
    # that reads well is not a failure — it just did not answer the brief, and
    # they should know that before they read it rather than after.
    if res.words > MAX_WORDS:
        res.notes.append(f"{res.words} words, over the {MAX_WORDS}-word brief")
    if res.paragraphs > 1:
        res.notes.append(f"{res.paragraphs} paragraphs; the brief asks for one")
    for marker in ("##", "**", "- ", "This criticism"):
        if marker in res.summary:
            res.notes.append(f"contains {marker!r}; the brief asks for plain prose "
                             "with no markdown and no preamble")
            break
    return res


def record_summary(dts, result, *, entity_path: str,
                   evidence_dir: str = "evidence") -> dict:
    """Stage 3 proposed a summary and is waiting for a reader (queue 6).

    The summary itself is NOT written to the entity yet, for the same reason
    concepts are not: the stage's two stopping points are the whole of the
    state model, and a summary on the record before anyone read it is a
    published summary.
    """
    dts.expect_stage(entity_path, result.entity, "summarized")
    guid = result.entity.rstrip("/").rsplit("/", 1)[-1]
    agent = str(dts.agent(result.model))
    dts.call("dts.write_evidence", {
        "path": f"{evidence_dir.rstrip('/')}/dts/{guid}/summarize.ttl",
        "turtle": summary_evidence(result, outcome="proposed", agent=agent),
    })
    return dts.call("dts.stamp", {
        "path": entity_path, "subject": result.entity, "stage": "summarized",
        "by": agent, "by_label": f"{result.model} (DTS summarization)",
    })


def commit_summary(dts, result, *, entity_path: str,
                   evidence_dir: str = "evidence") -> dict:
    """Accepted: the summary goes on the record and the stage closes."""
    dts.expect_stage(entity_path, result.entity, "summaryCurated")
    written = dts.call("dts.set_summary", {
        "path": entity_path, "subject": result.entity, "summary": result.summary,
    })
    guid = result.entity.rstrip("/").rsplit("/", 1)[-1]
    dts.call("dts.write_evidence", {
        "path": f"{evidence_dir.rstrip('/')}/dts/{guid}/summarize.ttl",
        "turtle": summary_evidence(result, outcome="accepted",
                                   agent=str(dts.agent(result.model))),
    })
    stamped = dts.call("dts.stamp", {
        "path": entity_path, "subject": result.entity,
        "stage": "summaryCurated", "by": str(dts.curator()),
        "by_label": "the curator",
    })
    return {"written": written, "stamped": stamped}


def summary_evidence(result, *, outcome: str, agent: str) -> str:
    """The summary as proposed, kept whether or not it was accepted.

    A rejected summary is the only record of what the cheap pass produced, and
    it is what a higher-tier retry would be compared against.
    """
    from datetime import datetime, timezone

    from rdflib import Graph, Literal, Namespace, URIRef
    from rdflib.namespace import RDF, RDFS, XSD

    PROV_NS = Namespace("http://www.w3.org/ns/prov#")
    OPS = Namespace("http://visualartsdna.org/operations/")
    g = Graph()
    g.bind("prov", PROV_NS)
    g.bind("ops", OPS)
    g.bind("rdfs", RDFS)
    run = URIRef(f"{result.entity}#summarize")
    g.add((run, RDF.type, OPS.SummaryRun))
    g.add((run, RDFS.label, Literal(f"DTS summarization of {result.document}")))
    g.add((run, OPS.entity, URIRef(result.entity)))
    g.add((run, OPS.document, Literal(result.document)))
    g.add((run, OPS.at, Literal(datetime.now(timezone.utc).isoformat(),
                                datatype=XSD.dateTime)))
    g.add((run, OPS.outcome, Literal(outcome)))
    g.add((run, OPS.summary, Literal(result.summary)))
    g.add((run, OPS.words, Literal(result.words)))
    g.add((run, OPS.inputTokens, Literal(result.input_tokens)))
    g.add((run, OPS.outputTokens, Literal(result.output_tokens)))
    if agent:
        g.add((run, PROV_NS.wasAttributedTo, URIRef(agent)))
    for note in result.notes:
        g.add((run, RDFS.comment, Literal(note)))
    return g.serialize(format="turtle")
