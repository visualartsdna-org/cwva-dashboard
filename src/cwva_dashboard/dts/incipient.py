"""Queue 0: the entity a criticism document implies, derived from the document.

Rick, 2026-10-01: "since you know how to create that entity for an AI Criticism
document, add an option to generate the incipient entity. From the markdown you
can differentiate Digital Sculpture vs Watercolor. The document can then be
reviewed and edited as needed."

So this proposes an entity and writes nothing. **Incipient** is the word for
what it makes: everything a criticism entity needs, derived and attributed, for
a person to correct before it becomes a record. Edit Record opens entities now
(§14.11), which is what makes "generate then review" a real workflow rather
than a promise.

**Derived from the thesaurus, not from a keyword list.** The material is
decided by counting which topic's own vocabulary the document actually uses —
and only the DISCRIMINATING terms, those belonging to one topic's schemes and
not the other's, because "surface" and "composition" are in both and vote for
nothing. That list maintains itself as the thesaurus grows, which a hardcoded
set of words would not.

**No model call.** Everything here is counting and string matching over data
the dashboard already holds. A stage that proposes concepts needs a model; one
that reads a title and counts vocabulary does not, and paying for it would make
queue 0 the only step with a cooldown.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..concepts.matcher import normalize, score
from .documents import CRITIC, USER, clean_text, first_prompt, turns

__all__ = ["Incipient", "propose_entity", "detect_material", "detect_source",
           "match_work", "relabel_for_work", "CRITICISM_TOPIC", "WORK_MATCH_THRESHOLD"]

#: Every criticism carries it: 60 of the 60 topic-bearing AI entities in the
#: real store do. The material topic is what has to be worked out.
CRITICISM_TOPIC = "the:Criticism"

#: How close a work's label must be to something the document names before it
#: is offered as the work being criticised. Below the dedup threshold on
#: purpose — "Prestress: The Three Graces" in a title against `Prestress Three
#: Graces` in the store is the case to catch, and it is not an exact match.
WORK_MATCH_THRESHOLD = 0.75

#: The export conventions, which say which assistant wrote the criticism more
#: reliably than a filename does — a file can be renamed, and the drop folder's
#: names are the user's own.
_SOURCE_BY_HEADING = {"prompt": "chatGpt", "response": "chatGpt",
                      "user": "claude", "assistant": "claude"}
_HEADING = re.compile(r"^#{1,6}\s*([A-Za-z]+)\s*:?\s*$", re.M)


@dataclass
class Incipient:
    """A criticism entity as the document implies it. Nothing is written."""

    document: str
    label: str = ""
    definition: str = ""
    topics: list = field(default_factory=list)
    source: str = ""
    material: str = ""
    work_uri: str = ""
    work_label: str = ""
    work_score: float = 0.0
    #: Why each guess was made, for the review that follows. A proposal nobody
    #: can account for is one nobody can correct with confidence.
    evidence: list = field(default_factory=list)

    @property
    def ready(self) -> bool:
        """Enough to make a record. The material and the work are guesses a
        person may have to supply; a definition is not — without a human turn
        there is nothing to describe the document with."""
        return bool(self.label and self.definition)


def _discriminating(table: dict, label_index: dict, prefixes: dict) -> dict:
    """`{topic: {labels}}` holding only the labels unique to that topic.

    A concept in `the:visualArtTerms` belongs to every material and votes for
    none, so it is dropped. What is left is the vocabulary that tells the
    materials apart.
    """
    from .thesaurus import read_scoped

    by_topic: dict[str, set] = {}
    for topic, spec in (table.get("schemes_by_topic") or {}).items():
        labels = set()
        for concept in read_scoped(label_index, spec.get("context") or [],
                                   prefixes=prefixes):
            labels.add(concept.label)
            labels.update(concept.alt_labels)
        by_topic[topic] = {l for l in labels if len(l) > 3}
    shared = set()
    topics = list(by_topic)
    for i, a in enumerate(topics):
        for b in topics[i + 1:]:
            shared |= by_topic[a] & by_topic[b]
    return {t: labels - shared for t, labels in by_topic.items()}


def detect_material(text: str, graph, table: dict, prefixes: dict) -> tuple:
    """Which material this criticism is about, and the evidence for it.

    **The artist's own words come first.** They say what the work is when they
    ask for the criticism — "Write an art criticism of this digital sculpture
    viewed in <modelviewer>", "Provide an art criticism of this watercolor
    Fairy Pool, 15x11 on 300 lb cold press" — and that is better evidence than
    any amount of counting. Vocabulary frequency is the fallback for a document
    whose prompt does not say.

    Counting alone got it wrong on the first real pair: the chatGPT criticism
    scored 7 digital against 6 watercolour, because several watercolour-scheme
    labels are common English words (`Balance`, `Overlap`, `nature`, `value`)
    that are discriminating by scheme membership and not by meaning.

    Returns `(topic_curie, [(topic, hits, sample)])`. Empty when nothing
    decides it — better to leave the material for a person than to file a
    criticism under one on a coincidence.
    """
    asked = normalize(first_prompt(text, limit=600))
    named = []
    for topic in (table.get("schemes_by_topic") or {}):
        word = normalize(topic.split(":", 1)[-1])
        if word and re.search(rf"\b{re.escape(word)}\b", asked):
            named.append(topic)
    if len(named) == 1:
        return named[0], [("the artist's own words", 1,
                           [f"the prompt says {named[0].split(':')[-1]!r}"])]

    haystack = normalize(str(text))
    scores = []
    for topic, labels in _discriminating(table, graph, prefixes).items():
        hit = sorted({l for l in labels
                      if re.search(rf"\b{re.escape(normalize(l))}\b", haystack)})
        scores.append((topic, len(hit), hit[:6]))
    scores.sort(key=lambda row: -row[1])
    if not scores or scores[0][1] == 0:
        return "", scores
    # A clear winner only. Two materials neck and neck is a document a person
    # should look at, not a coin to flip.
    if len(scores) > 1 and scores[1][1] and scores[0][1] < scores[1][1] * 2:
        return "", scores
    return scores[0][0], scores


def detect_source(text: str, filename: str = "") -> str:
    """Which assistant wrote it, from the export's own headings."""
    for match in _HEADING.finditer(str(text)):
        found = _SOURCE_BY_HEADING.get(match.group(1).strip().lower())
        if found:
            return found
    low = str(filename).lower()
    for name in ("chatgpt", "claude", "gemini", "copilot"):
        if name in low:
            return "chatGpt" if name == "chatgpt" else name
    return ""


def match_work(text: str, works, *, threshold: float = WORK_MATCH_THRESHOLD) -> tuple:
    """The work this criticism is about, matched by label against the document.

    Matched on the TITLE and the first human turn rather than the whole
    document: a criticism mentions other works in passing, and the thing it is
    about is named where the artist named it.
    """
    # EVERY heading, not just the title. A criticism names its subject in a
    # heading — `## Art Criticism - *Prestress: The Three Graces*` — while the
    # document's own title is often generic ("Art criticism sculpture") and the
    # first prompt says "this digital sculpture" without naming it. Searching
    # the whole body instead would match works mentioned in passing.
    headings = " ".join(line.lstrip("# ").strip()
                        for line in str(text).splitlines()
                        if line.startswith("#"))
    where = f"{headings} {first_prompt(text, limit=400)}"
    best = ("", "", 0.0)
    for uri, label in (works or {}).items():
        if not label:
            continue
        # Against the whole phrase and against its own window, because a title
        # is a fragment of the sentence that contains it.
        sc = max(score(label, where),
                 max((score(label, chunk) for chunk in _windows(where, label)),
                     default=0.0))
        if sc > best[2]:
            best = (str(uri), str(label), round(sc, 4))
    # Below the threshold, NOTHING is named. Naming the nearest looked
    # helpful and was not: on a criticism whose headings name no work, the
    # nearest label was `Thistle` at 0.73 — the matcher sits around 0.59 for
    # unrelated strings, so a sub-threshold best is noise wearing a number,
    # and putting it on the screen invites a reviewer to accept it.
    return best if best[2] >= threshold else ("", "", best[2])


def _windows(text: str, label: str):
    """Sliding word windows the length of the label, so a title inside a
    sentence scores as a title rather than as a fraction of a paragraph."""
    words = str(text).split()
    width = max(len(str(label).split()), 1)
    for i in range(0, max(len(words) - width + 1, 1)):
        yield " ".join(words[i:i + width])


def propose_entity(*, document: str, text: str, graph, works: dict,
                   table: dict, prefixes: dict) -> Incipient:
    """Everything a criticism entity needs, derived and accounted for."""
    out = Incipient(document=document)
    out.definition = first_prompt(text)
    if not out.definition:
        out.evidence.append(("definition", 0,
                             ["no human turn found; the document cannot "
                              "describe itself"]))

    out.source = detect_source(text, document)
    if out.source:
        out.evidence.append(("source", 1, [f"from the export's headings: "
                                           f"{out.source}"]))

    out.material, material_evidence = detect_material(text, graph, table, prefixes)
    out.evidence.extend(material_evidence)

    out.topics = [CRITICISM_TOPIC]
    # The real store's own pattern: a watercolour criticism carries
    # [Criticism, Watercolor]; a digital sculpture carries
    # [Criticism, Digital, Sculpture]. Read off the records rather than
    # invented — 46 and 17/18 of them respectively.
    if out.material == "the:Digital":
        out.topics += ["the:Digital", "the:Sculpture"]
    elif out.material:
        out.topics.append(out.material)

    out.work_uri, out.work_label, out.work_score = match_work(text, works)
    if out.work_uri:
        out.evidence.append(("work", 1, [f"{out.work_label} at "
                                         f"{out.work_score:.2f}"]))
    else:
        out.evidence.append(("work", 0, [
            f"no work matched above {WORK_MATCH_THRESHOLD} — the document may "
            "name its subject nowhere a heading can be read. Name the work on "
            "the generate card; the editor cannot add a predicate the record "
            "does not already have."]))

    out.label = clean_text(_label_for(out, text))
    return out





def relabel_for_work(out: Incipient, work_label: str, text: str) -> Incipient:
    """The person named the work: the label follows it, not the matcher."""
    out.work_label = str(work_label)
    out.label = clean_text(_label_for(out, text))
    return out


def _label_for(out: Incipient, text: str) -> str:
    """`<work> Criticism <source>`, which is the store's own shape.

    Falls back to the document's title when no work matched, because a label
    that names the wrong work is worse than one that names none.
    """
    subject = out.work_label
    if not subject:
        for line in str(text).splitlines():
            if line.startswith("# "):
                subject = line[2:].strip()
                break
    subject = re.sub(r"\b(art\s+)?criticism\b|\bcritique\b", "", subject,
                     flags=re.I).strip(" -–—:")
    parts = [p for p in (subject, "Criticism", out.source) if p]
    return " ".join(parts)
