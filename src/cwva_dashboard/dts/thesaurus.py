"""The thesaurus DTS works against — read from the QA store, not from a server.

**Decided in round 3, and it is the most consequential decision in the file.**
The agent read `http://localhost:8082/sparqlEndpoint`, which is why the old
workflow had the shape it did: "Distribute Metadata. Then refresh DB to make
concepts available for tagging." The step order was not stylistic — the agent
could not see a newly derived concept until it had been published and a
downstream server reloaded.

Reading the QA store instead makes DTS self-consistent inside the sandbox: a
concept derived at step 2 is visible to tagging at step 3 with nothing
distributed and nothing refreshed, and the whole of DTS can be done in one
sitting. It also means the vocabulary includes UNDISTRIBUTED concepts, so
dedup sees drafts — which is correct, and differs from every run the agent has
ever made.

Two label sets, deliberately different:

- what the MODEL is shown, scoped to the schemes for this material, because
  that is the "do not duplicate" list and a watercolor list in front of a
  sculpture criticism is worse than useless;
- what DEDUP compares against, which is every labelled concept in the store,
  because "do we already have this" is not a question about schemes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rdflib import Graph, URIRef
from rdflib.namespace import RDFS, SKOS

__all__ = ["ExistingConcept", "read_scoped", "read_label_index", "format_for_prompt",
           "schemes_for", "resolve_broader", "scheme_for_concept"]


@dataclass
class ExistingConcept:
    """One concept as the prompt needs it."""

    uri: str
    label: str
    alt_labels: list = field(default_factory=list)
    broader: str = ""
    broader_label: str = ""
    scheme: str = ""


def _expand(curie: str, prefixes: dict) -> str:
    head, sep, tail = str(curie).partition(":")
    return prefixes.get(head, "") + tail if sep and head in prefixes else str(curie)


def schemes_for(topics, table: dict, *, prefixes: dict) -> dict:
    """Which schemes this entity's material lives in.

    Derived from the record's `the:topic`, first declared match winning, with
    a general fallback. A topic table beats a flag: the entity already says
    what it is about, and a flag is a second place for that to be wrong.
    """
    by_topic = (table or {}).get("schemes_by_topic") or {}
    for topic in topics or []:
        for key, spec in by_topic.items():
            if _expand(key, prefixes) == _expand(topic, prefixes):
                return {"topic": key, **spec}
    return {"topic": "", **((table or {}).get("default") or {})}


def read_scoped(g: Graph, scheme_uris, *, prefixes: dict) -> list:
    """Every concept in the named schemes, as the prompt's "do not duplicate"
    list."""
    wanted = {_expand(s, prefixes) for s in (scheme_uris or [])}
    out: dict[str, ExistingConcept] = {}
    for scheme in sorted(wanted):
        for s in g.subjects(SKOS.inScheme, URIRef(scheme)):
            uri = str(s)
            if uri in out:
                continue
            label = g.value(s, RDFS.label) or g.value(s, SKOS.prefLabel)
            if label is None:
                continue
            broader = g.value(s, SKOS.broader)
            out[uri] = ExistingConcept(
                uri=uri, label=str(label),
                alt_labels=sorted(str(a) for a in g.objects(s, SKOS.altLabel)),
                broader=str(broader) if broader else "",
                broader_label=str(g.value(broader, RDFS.label) or "") if broader else "",
                scheme=scheme,
            )
    return sorted(out.values(), key=lambda c: (c.scheme, c.label.lower()))


def read_label_index(g: Graph) -> dict:
    """`{uri: {labels}}` for EVERY concept in the store, for dedup.

    The CE_DESIGN §6 label set — `skos:prefLabel ∪ skos:altLabel ∪ rdfs:label`
    — collected symmetrically. The Groovy compared its source against all
    three and its candidates against `rdfs:label` alone, so a concept named
    only in an altLabel could never be matched against.
    """
    index: dict[str, set] = {}
    for prop in (SKOS.prefLabel, SKOS.altLabel, RDFS.label):
        for s, _p, o in g.triples((None, prop, None)):
            uri = str(s)
            if "/thesaurus/" not in uri:
                continue
            index.setdefault(uri, set()).add(str(o))
    return index


def format_for_prompt(concepts) -> str:
    """The compact record the extraction prompt references.

    Kept in the agent's own format — `URI: … | Label: … | AltLabels: … |
    Broader: …` — because the prompt that reads it is the accumulated tuning
    and changing the shape of its input is changing the prompt.
    """
    if not concepts:
        return "(No existing concepts in the target scheme(s).)"
    lines = []
    for c in concepts:
        parts = [f"URI: {c.uri}", f"Label: {c.label}"]
        if c.alt_labels:
            parts.append(f"AltLabels: {', '.join(c.alt_labels)}")
        if c.broader:
            parts.append(f"Broader: {c.broader_label or c.broader} ({c.broader})")
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def resolve_broader(g: Graph, uri: str = "", label: str = "") -> str:
    """The broader concept the model named, by URI or — failing that — by label.

    The prompt asks for both and the model often supplies only the label
    ("Structural and Analytical Terms"), because it is copying from the list
    it was shown rather than from the URI column. Resolving by label is what
    turns that into a usable parent instead of an orphan.
    """
    if uri:
        u = URIRef(str(uri))
        if (u, None, None) in g:
            return str(u)
    if not label:
        return ""
    wanted = str(label).strip().casefold()
    for prop in (RDFS.label, SKOS.prefLabel, SKOS.altLabel):
        for s, _p, o in g.triples((None, prop, None)):
            if "/thesaurus/" in str(s) and str(o).strip().casefold() == wanted:
                return str(s)
    return ""


def scheme_for_concept(g: Graph, *, broader_uri: str = "", broader_label: str = "",
                       fallback: str = "", prefixes: dict | None = None) -> tuple:
    """Which scheme a NEW concept joins: **its broader term's**.

    Derived from the ontology rather than from a category table, and that is
    not a preference — it is what the store already does. Measured across the
    670 concepts that have both a scheme and a scheme-bearing parent, **523
    (78%) sit in a scheme their broader term is in**, and most of the
    remainder are scheme HEADS, whose parent naturally lives one level up in a
    more general scheme.

    It also fixes something a table cannot. These two criticisms are of a
    tensegrity sculpture, and the model placed "Load path" under `Structural
    and Analytical Terms` and "Golden apple motif" under `Iconographic
    program` — which live in `the:tensegrityTerms` and `the:digitalArtTerms`
    respectively. A per-category table would have filed all of them in one
    scheme and been wrong about half.

    The configured table remains the FALLBACK, for a concept whose parent is
    unknown, unplaced, or absent. Returns `(scheme_uri, how)` so the run can
    report which rule decided — a placement nobody can account for is one
    nobody will trust.
    """
    parent = resolve_broader(g, broader_uri, broader_label)
    if parent:
        schemes = sorted(str(x) for x in g.objects(URIRef(parent), SKOS.inScheme))
        if schemes:
            return schemes[0], "inherited from its broader term"
    return (_expand(fallback, prefixes or {}) if fallback else ""), "from the configured table"
