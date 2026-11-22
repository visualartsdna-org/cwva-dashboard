"""Declare the DTS vocabulary, and move the status half of it into `ops:`.

    python scripts/migrate_dts_vocabulary.py --dry-run
    python scripts/migrate_dts_vocabulary.py
    python scripts/migrate_dts_vocabulary.py --config config/production.rson

DTS minted sixteen predicates and declared none of them. They all went into
`the:` — the thesaurus namespace — because the shape came from the review
sketch and because `the:conceptsExtracted`, the flag the stamps retire, was
already there. That was continuity with a mistake rather than a reason: `the:`
is where `skos:Concept`s in schemes live, and a stamp is not a concept.

Rick, 2026-10-01, asked the question that found it: "what was the reasoning for
placing the properties in the thesaurus namespace as opposed to the operations
namespace?" There was none. The same argument had already moved the agents out
of `…/agent/` a day earlier (`migrate_agent_iris.py`) and was simply never
applied to the node containing them, so the attribution inside a stamp resolved
to `ops:` while the stamp around it resolved to nothing.

**The split is deliberate and it is not "all of DTS".**

*The status half moves.* `status`, the six stage stamps and `at` are the
dashboard's record of what it did to a record — machinery, and `ops:` is where
the machinery vocabulary lives. Eight terms, rewritten in place.

*The grounding half stays in `the:`* (Rick: "I definitely want to keep grounding
terms in the:"). A grounding is **about a concept** — the phrase that warrants
it and the thesaurus labels near it — so it is thesaurus vocabulary that was
merely undeclared, not misplaced. Eight terms, declared where they already are.

So this script does three things, and all three are idempotent:

1. **Adds section 3 to `operations.ttl`** — `ops:Status`, `ops:Stamp`, the six
   stage properties and `ops:at`. Skipped when `ops:Status` is already there.
2. **Adds the grounding block to `entity.ttl`** — `the:Grounding`, `the:Match`,
   and the eight properties, beside the `the:topic` / `the:summary` cluster the
   grounding hangs next to. Skipped when `the:Grounding` is already there.
3. **Rewrites `the:status` and its stamps to `ops:`** across the data, leaving
   every other `the:` predicate alone.

Two domains are deliberately **omitted** rather than guessed, because a wrong
`rdfs:domain` is an inference a reasoner will make and nothing will flag.
`the:grounding` hangs on an entity when it names the concept and on a concept
when it names the entity, and `the:concept` appears on both a grounding and a
match — so naming one domain for either would have a reasoner conclude the
other. The comment says so in the ontology, where the next reader is.

Files are **re-serialized**, not patched, so prefixes are rebound on the way
out (a record that gained a `vad:` property after it was written has nothing
binding `vad:` and serializes as `ns1:`). A file whose graph did not actually
change is skipped, because re-serialization reorders blank nodes and that is a
large diff with no change in it for the review stop to read past.

Written through `FileOps` and left **uncommitted**: review it at Preview Staged
and distribute it through the ordinary gated exit.
"""

from __future__ import annotations

import re
import os
import sys
from pathlib import Path

from rdflib import Graph, URIRef
from rdflib.compare import isomorphic

from cwva_dashboard import config as cfgmod
from cwva_dashboard.dts.state import STAGES
from cwva_dashboard.sandbox.fileops import FileOps
from cwva_dashboard.sandbox.paths import Sandbox
from cwva_dashboard.tools.record_tools import bind_standard

_CONFIG = Path(__file__).resolve().parents[1] / "config" / "dashboard.rson"

THE = "http://visualartsdna.org/thesaurus/"
OPS = "http://visualartsdna.org/operations/"

#: The eight status terms, and the eight that stay put. Named here rather than
#: derived so the split is reviewable in one place — and so a term added to the
#: grounding vocabulary later is not swept into `ops:` by a pattern that
#: happened to match it.
MOVED: tuple[str, ...] = ("status", "at") + STAGES
STAYS: tuple[str, ...] = ("grounding", "phrase", "srcEntity", "concept",
                          "match", "unique", "distance", "matchType")

STATUS_SECTION = '''

################################################################
# SECTION 3 - Workflow state
################################################################
#
# What a workflow did to a record, when, and who did it. One status node per
# record, carrying a stamp per completed stage and an rdfs:label naming the
# state a reader would call it.
#
# These are OPERATIONS terms, which cost one migration to learn: they were
# `the:` for a sitting, inherited from the deprecated `the:conceptsExtracted`
# flag they retire. `the:` is the thesaurus, where every other member is a
# skos:Concept in a scheme. A stamp is not a concept - it is what the dashboard
# did to a record, which is this ontology's subject.

ops:Status a owl:Class ;
  rdfs:label "Status" ;
  rdfs:isDefinedBy <http://visualartsdna.org/operations/> ;
  rdfs:comment "The workflow state of one record: which stages have completed, when, and by whom. One per record, replacing a boolean flag per stage." ;
.

ops:Stamp a owl:Class ;
  rdfs:label "Stamp" ;
  rdfs:isDefinedBy <http://visualartsdna.org/operations/> ;
  rdfs:comment "One completed stage, recorded. Carries the moment and the agent together, so what happened, when, and who did it is never spread across three places." ;
.

ops:status
  rdf:type owl:ObjectProperty ;
  rdfs:range ops:Status ;
  rdfs:label "status" ;
  rdfs:isDefinedBy <http://visualartsdna.org/operations/> ;
  rdfs:comment "The workflow state of this record. No domain: any record a workflow touches may carry one, and naming a class here would have a reasoner type every other kind of record that acquires state." ;
.

ops:at
  rdf:type owl:DatatypeProperty ;
  rdfs:domain ops:Stamp ;
  rdfs:range xsd:dateTime ;
  rdfs:label "at" ;
  rdfs:isDefinedBy <http://visualartsdna.org/operations/> ;
  rdfs:comment "When the stage completed. A dateTime and not a date: all six stages of one document are normally done in a single sitting, so a date cannot order them." ;
.

# THE SIX STAGES, in the order they run. A stage may not be stamped until its
# predecessor is, which is what makes "stopped and resumed mid-way" a question
# about stamps rather than about sessions. The queue rules read these and never
# the rdfs:label, which is a denormalisation able to disagree with them.

ops:derived
  rdf:type owl:ObjectProperty ;
  rdfs:domain ops:Status ;
  rdfs:range ops:Stamp ;
  rdfs:label "derived" ;
  rdfs:isDefinedBy <http://visualartsdna.org/operations/> ;
  rdfs:comment "Concepts were proposed from the record's source document. Proposed only - nothing is published by this stage." ;
.

ops:derivationCurated
  rdf:type owl:ObjectProperty ;
  rdfs:domain ops:Status ;
  rdfs:range ops:Stamp ;
  rdfs:label "derivation curated" ;
  rdfs:isDefinedBy <http://visualartsdna.org/operations/> ;
  rdfs:comment "A person decided which proposed concepts are kept, and the kept ones were minted into the thesaurus." ;
.

ops:tagged
  rdf:type owl:ObjectProperty ;
  rdfs:domain ops:Status ;
  rdfs:range ops:Stamp ;
  rdfs:label "tagged" ;
  rdfs:isDefinedBy <http://visualartsdna.org/operations/> ;
  rdfs:comment "Concepts the record uses were proposed as placements on it, by the most specific property the ontology allows." ;
.

ops:taggingCurated
  rdf:type owl:ObjectProperty ;
  rdfs:domain ops:Status ;
  rdfs:range ops:Stamp ;
  rdfs:label "tagging curated" ;
  rdfs:isDefinedBy <http://visualartsdna.org/operations/> ;
  rdfs:comment "A person decided which proposed placements are kept, and the kept ones were written to the record." ;
.

ops:summarized
  rdf:type owl:ObjectProperty ;
  rdfs:domain ops:Status ;
  rdfs:range ops:Stamp ;
  rdfs:label "summarized" ;
  rdfs:isDefinedBy <http://visualartsdna.org/operations/> ;
  rdfs:comment "A summary of the source document was drafted." ;
.

ops:summaryCurated
  rdf:type owl:ObjectProperty ;
  rdfs:domain ops:Status ;
  rdfs:range ops:Stamp ;
  rdfs:label "summary curated" ;
  rdfs:isDefinedBy <http://visualartsdna.org/operations/> ;
  rdfs:comment "A person accepted or rewrote the drafted summary, which completes the workflow for this record." ;
.
'''

GROUNDING_SECTION = '''

#
# GROUNDING - the evidence for a concept.
#
# Thesaurus vocabulary, deliberately: a grounding is about a concept - the
# phrase that warrants it and the labels near it - which is why these stayed in
# `the:` when the workflow stamps moved to `ops:`. They were undeclared, not
# misplaced.
#
# Two domains are OMITTED rather than guessed. A wrong rdfs:domain is an
# inference a reasoner will make and nothing will flag, and each of these two
# properties genuinely has two homes.

the:Grounding
		a owl:Class ;
        rdfs:label         "Grounding" ;
        rdfs:comment    "The evidence for a concept: the phrase in a source document that warrants it, and whatever the dashboard found near it in the thesaurus." ;
		.

the:Match
		a owl:Class ;
        rdfs:label         "Match" ;
        rdfs:comment    "One thesaurus label close enough to a proposed concept's to be worth a look, with how close it is. Reported, never acted on: a duplicate is offered to a person, not resolved by a threshold." ;
		.

the:grounding
  rdf:type owl:ObjectProperty ;
  rdfs:range the:Grounding ;
  rdfs:label "grounding" ;
  rdfs:comment "The evidence for this concept. No domain: the node hangs on the entity when it names the concept and on the concept when it names the entity, so whichever end is not already named is the one stated." ;
.
the:phrase
  rdf:type owl:DatatypeProperty ;
  rdfs:domain the:Grounding ;
  rdfs:range xsd:string ;
  rdfs:label "phrase" ;
  rdfs:comment "The words in the source document that warrant the concept, verified to occur there before the grounding was written." ;
.
the:srcEntity
  rdf:type owl:ObjectProperty ;
  rdfs:domain the:Grounding ;
  rdfs:range the:Entity ;
  rdfs:label "source entity" ;
  rdfs:comment "The entity whose document the phrase was read from." ;
.
the:concept
  rdf:type owl:ObjectProperty ;
  rdfs:range skos:Concept ;
  rdfs:label "concept" ;
  rdfs:comment "The concept being grounded, or the one a match found. No domain: it appears on both a grounding and a match, and naming either class would have a reasoner conclude the other." ;
.
the:match
  rdf:type owl:ObjectProperty ;
  rdfs:domain the:Grounding ;
  rdfs:range the:Match ;
  rdfs:label "match" ;
  rdfs:comment "A thesaurus label near this concept's, offered so a near-duplicate can be seen before the concept is published." ;
.
the:unique
  a the:Match ;
  rdfs:label "unique" ;
  rdfs:comment "The empty neighbourhood said out loud. An absent the:match would be indistinguishable from a search nobody ran." ;
.
the:distance
  rdf:type owl:DatatypeProperty ;
  rdfs:domain the:Match ;
  rdfs:range xsd:float ;
  rdfs:label "distance" ;
  rdfs:comment "How close the two labels are, 0 to 1, from max(ratio, token_sort_ratio) after normalisation. 1.0 is identical after normalising." ;
.
the:matchType
  rdf:type owl:DatatypeProperty ;
  rdfs:domain the:Match ;
  rdfs:range xsd:string ;
  rdfs:label "match type" ;
  rdfs:comment "Which comparison produced the distance, so a token-order match is not read as a character-level one." ;
.
'''


#: A cheap pre-filter, and it needs the word boundary: `the:at` is a prefix of
#: `the:attunement`, a real concept in `vocab2.ttl`, so a substring test would
#: parse and re-serialize that file only to report it "unchanged (skipped)" —
#: a line in the report with nothing behind it.
_MENTIONS = re.compile(
    r"(?:the:|" + re.escape(THE) + r")(?:" + "|".join(MOVED) + r")(?![A-Za-z0-9_-])")


def target_iri(old: str) -> URIRef:
    """`the:X` as `ops:X`, for the eight status terms only."""
    local = str(old)[len(THE):]
    return URIRef(OPS + local) if local in MOVED else URIRef(old)


def rewrite(graph: Graph) -> int:
    """Move the status predicates into `ops:`. Returns the triples touched.

    Predicate position only, which is the whole of it: every one of the eight
    is a predicate, and `the:unique` — the one status-adjacent term that
    appears as an OBJECT — is grounding vocabulary and stays.
    """
    touched = 0
    for s, p, o in list(graph):
        if not str(p).startswith(THE):
            continue
        new_p = target_iri(p)
        if new_p == p:
            continue
        graph.remove((s, p, o))
        graph.add((s, new_p, o))
        touched += 1
    return touched


def add_status(text: str) -> str:
    """Section 3, appended to `operations.ttl`. Idempotent."""
    if "ops:Status" in text:
        return text
    return text + STATUS_SECTION


def add_grounding(text: str) -> str:
    """The grounding block, appended to `entity.ttl`. Idempotent."""
    if "the:Grounding" in text:
        return text
    return text + GROUNDING_SECTION


def _section(ops, rel: str, apply, label: str, *, dry_run: bool) -> None:
    """Add one ontology block, reporting what it added and refusing what will
    not parse."""
    try:
        before = ops.read_text(rel)
    except Exception:
        print(f"\n{rel}: ABSENT — run migrate_agent_iris.py --ontology-from first"
              if rel.endswith("operations.ttl") else f"\n{rel}: ABSENT")
        return
    after = apply(before)
    if after == before:
        print(f"\n{rel}: {label} already present")
        return
    parsed = Graph()
    parsed.parse(data=after, format="turtle")  # refuse what will not parse
    added = len(parsed) - len(Graph().parse(data=before, format="turtle"))
    print(f"\n{rel}: + {label} ({added} triples)")
    if not dry_run:
        ops.write_text(rel, after, make_parents=True)


def main(argv: list[str]) -> int:
    dry_run = "--dry-run" in argv
    config_path = str(_CONFIG)
    if "--config" in argv:
        config_path = argv[argv.index("--config") + 1]
    elif os.environ.get("CWVA_DASHBOARD_CONFIG"):
        # The variable that SELECTS the production instance for uvicorn. A
        # script that read only the flag would act on QA for an operator who
        # had exported it and said nothing.
        config_path = os.environ["CWVA_DASHBOARD_CONFIG"]

    cfg = cfgmod.load_config(config_path)
    root = cfgmod.sandbox_root(cfg, create=False)
    layout = cfgmod.active_layout(cfg)
    ops = FileOps(Sandbox.open(root, create=False),
                  git_content_extensions=cfgmod.git_content_extensions(cfg))

    print(f"config : {config_path}")
    print(f"qa     : {root}")
    print(f"moving : {', '.join('the:' + t for t in MOVED)}")
    print(f"staying: {', '.join('the:' + t for t in STAYS)}")

    model = layout.dir("model_ttl").rstrip("/")
    _section(ops, f"{model}/operations.ttl", add_status,
             "workflow-state section", dry_run=dry_run)
    _section(ops, f"{model}/entity.ttl", add_grounding,
             "grounding vocabulary", dry_run=dry_run)

    changed, skipped, scanned = [], [], 0
    for path in sorted(Path(root).rglob("*.ttl")):
        rel = str(path.relative_to(root))
        if rel.startswith(".qa/"):
            continue
        scanned += 1
        text = path.read_text(encoding="utf-8")
        if not _MENTIONS.search(text):
            continue
        graph = Graph()
        graph.parse(data=text, format="turtle")
        original = Graph()
        original.parse(data=text, format="turtle")
        touched = rewrite(graph)
        if isomorphic(graph, original):
            skipped.append(rel)
            continue
        bind_standard(graph)
        changed.append((rel, touched))
        if not dry_run:
            ops.write_text(rel, graph.serialize(format="turtle"),
                           make_parents=True)

    print(f"\nscanned {scanned} TTL file(s)")
    if not changed and not skipped:
        print("no `the:status` predicates found; nothing to rewrite")
    print(f"  rewritten {len(changed)} file(s), "
          f"{sum(t for _r, t in changed)} triple(s)")
    for rel in skipped:
        print(f"  {rel:58} unchanged (skipped)")

    if dry_run:
        print("\nDRY RUN — nothing written.")
        return 0
    print("\nThe QA tree is UNCOMMITTED. Review it at Preview Staged and "
          "distribute it there.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
