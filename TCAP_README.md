# TCAP_README — Concept Annotation: Pattern, Algorithm, and Port Notes

Cover document for the two TCAP handoffs in this repo. Read this first,
then the handoffs. It defines terminology, records the decisions made
around the port, and lists what remains open — including the one document
CC must still produce (ALGORITHM.md) before writing the port.

**Companion documents:**
- *SPARQL Most Specific Property Query Handoff* (2026-02-19) — the
  navigation algorithm: final query, rationale for its non-obvious
  filters, three acceptance test cases.
- *CWVA Ontology VisualAnalysis Restructuring Handoff* (2026-03-16) — the
  data pattern the algorithm depends on, a worked failure case
  (CrowdHingeBand), and the semantic placement rules for decorations.

---

## Terminology

**TCAP — Thesaurus Class Annotation Pattern.** Ontology classes annotated
onto thesaurus concepts within the `skos:broader` hierarchy. Sparse by
design: not every concept is annotated; concepts inherit typing from their
nearest typed ancestor. TCAP is **data**, not code — it lives in the
vocabulary files and is maintained through vocabulary workflows and the
RDF Graph Editor.

**The navigation algorithm** (the "most-specific-property query") consumes
TCAP: given a subject and a concept, it finds the most specific object
property whose range matches the concept's effective type. This is the
part that ports to Python (suggested home: `concepts/tcap_navigation.py`).

## One algorithm, two consumers

The navigation algorithm is a **single shared module** with two consumers.
Do not port it twice; the two paths must not drift. **Both consumers emit
typed properties** via the navigation query — they differ in input and
invocation, not output:

| Consumer | Target | Input & invocation | Output |
|---|---|---|---|
| Annotate Work (inventory #6) | Work instances | Interactive: concepts chosen in the picker | Typed properties (e.g. `vad:hasWatercolorPaint`, `vad:hasWatercolorTechnique`) |
| Annotate Document Instances (inventory #15) | Criticism/Entity instances | Batch: curated `the:tag` concept links from the tagging step | Typed properties (e.g. `vad:hasComposition`, `vad:hasVisualAnalysis`, `vad:hasCriticism`); **the consumed tag TTL never reaches SOT** — replaced by the typed-property placements, and preserved as curation evidence (see *Tag evidence* below) |

> **Supersedes the Restructuring handoff on one point.** That handoff's
> "Impact on Work Instance Data" section describes tag-to-typed-property
> promotion on criticism instances as a *future possibility*. That future
> arrived: the current pipeline performs the promotion; the consumed tag
> TTL never reaches SOT. Where the handoff and this README disagree, this
> README reflects current practice (confirmed against production
> instances, July 2026).

**Two roles of `the:tag` — do not conflate.** (a) *Instance linkage*:
persistent, reciprocal links between instances (work ↔ its criticisms;
`the:tag` is symmetric); never touched by the pipeline. (b) *Concept
scaffolding* for Entity instances: transient tag TTL naming thesaurus
concepts, consumed by #15 and never promoted to SOT. **Discriminator
caution:** Entity instances are themselves `skos:Concept`s
(`skos:inScheme the:entities`), so "object is a SKOS concept" does NOT
distinguish the roles — discrimination must be by namespace (`work:` vs
`the:`) or by `skos:inScheme`. ALGORITHM.md must confirm which check the
Groovy uses.

**Tag evidence (design decision).** The consumed tag TTL carries curation
information — grounding phrases and the evidence behind each tagging —
worth preserving as an audit trail for later questioning of a decoration.
It is stored in a top-level `evidence/` directory of the QA repo, sibling
to the mirrored content/metacontent trees: **tracked in the QA git,
excluded from transport convergence** (the convergence manifest computes
over the mirrored subtrees only; `evidence/` never pushes to SOT). The
tag TTL commits in the same promotion unit that places the typed
properties, binding evidence and outcome in one atomic commit. Naming:
by document/entity GUID. *(Amends the QA-git design in CE_DESIGN §3.4:
QA repo = mirrored trees + non-converged evidence area.)*

**Processing flag — three-state lifecycle** (`the:conceptsExtracted`):
- **absent** — grandfathered: entity does not want concept derivation
  (typically early criticism documents not worth updating). Never nagged.
- **false** — pending extraction: the open obligation. The workflow-panel
  standing query is `conceptsExtracted false` — explicit, no inference
  from absence.
- **true** — done; set by the pipeline upon extraction.

**New behavior, not in the Groovy:** the Entity entry form (#3) must
write `conceptsExtracted false` on every new entity; the pipeline flips
it to true. CC builds this — do not hunt for it in the Groovy source.
Likely re-run semantics: skip where true (ALGORITHM.md to confirm
against the code's actual guard, if any).

**Uniform vocabulary across instance types:** the same typed properties
appear on works and criticism entities (e.g. `vad:hasWatercolorTechnique`
on both — artist's chosen technique vs. critic's observed technique).
One navigation algorithm applied uniformly; the instance type carries the
semantic distinction, not the property choice.

**Background — entity.ttl:** `the:Entity` is the top class of the
entity.ttl thesaurus-oriented ontology, modeling things beyond the art
realm covered by cwva.ttl (often art references, never catalog artworks).
It is `rdfs:subClassOf skos:Concept` and superclass of all types
selectable on the Entity entry form; instances are further qualified by
`the:topic` referencing the `the:TopicScheme` (top concept
`the:Interpretation`; narrower concepts such as `the:Criticism`).

**Concept agent invocation (replaces the legacy .bat).** The Groovy
server invokes concept_agent.py via a batch file that passes the API key
as argv %1 — visible in process listings; this is retired as both an
interface change and a security fix. The port invokes the agent directly
from dashboard code with: the key from `ANTHROPIC_API_KEY` in the
environment (secrets convention — never argv, never logged); the SPARQL
endpoint, working directory, and log location from config (endpoint now
targets the QA store, log inside the sandbox); mode/confidence/limits/
schemes as tool parameters. In Phase 5 this invocation routes through
`ai_service` task profiles like every other AI call.

## Port-critical dependencies

1. **Materialized RDFS inference is a hard dependency.** Branch 1 of the
   query and the `broader+`-not-`broader*` choice both exist because the
   store contains RDFS-inferred types from property usage. The QA store
   must reproduce this (Fuseki with RDFS reasoner, or RDFLib + owlrl
   materialization after load). Without inference the query does not fail
   — it silently returns different results, the worst failure mode.
   **Tests must assert the inferred type exists in the fixture store
   before running the query.** This dependency also weighs on the Phase 7
   Fuseki-vs-in-process decision.
2. **The handoff's performance notes are Jena-calibrated.** "Efficient"
   there means efficient on Jena; RDFLib's SPARQL engine handles property
   paths and NOT EXISTS less gracefully. Benchmark against a
   realistically-sized fixture as part of the port tests. Poor results
   are a second thumb on the Fuseki side of the Phase 7 scale.
3. **The three test cases in the Query handoff are the acceptance suite.**
   Port them as fixtures verbatim. The CrowdHingeBand case from the
   Restructuring handoff is a fourth: after the vocabulary fix, exactly
   one triple; a regression to two triples means TCAP data or inference
   setup is wrong.

**Erratum — the query in the SPARQL handoff is incomplete.** The actual Groovy
(`support/AnnotateWork.groovy` `linkConceptsToWork`, confirmed 2026-07-17)
includes in **both** the direct-type and broader-type branches a filter the
*Most Specific Property Query Handoff* omits:

```sparql
?op a owl:ObjectProperty .
```

This restricts candidates to declared object properties (`owl:` must be in the
query prefixes). **Port the query with this filter**, not the handoff's printed
version — without it, datatype or untyped predicates with a matching
`rdfs:range` can leak in. The three handoff test cases still pass with it added;
see ALGORITHM.md §2, §6 for the full port analysis.

## Tie policy (decided)

A tie — more than one triple surviving the query's cross-branch filter —
is a **symptom of a vocabulary modeling defect** (false `skos:broader`
link or misplaced class annotation), never a normal situation and never a
defect in the algorithm. The CrowdHingeBand case is the precedent: the
fix was structural (thesaurus repair), and a query-side tie-breaker was
explicitly rejected as masking the modeling error. The port handles ties
accordingly:

1. **Adjudicate to unblock:** the AI service picks the surviving triple
   (task input: work, concept, candidate properties, ontology context) so
   the workflow never blocks. The emitted triple carries `prov:`
   attribution marking it AI-adjudicated. (Until Phase 5 provides the
   task profile, stub = deterministic pick + the ledger entry below.)
2. **Record to force the fix:** every tie lands as a hygiene-ledger entry
   and a workflow-panel open item ("TCAP tie on the:X — investigate
   thesaurus/ontology"), pointing at the vocabulary, not the code.
3. **Resolve structurally:** the open item's resolving action is
   investigation via the prompt; the eventual fix is a vocabulary repair
   that ends in a promotion unit like any other change.
4. **Never surface tied triples to the end user** in data views — the
   ledger/panel entry is the user-visible artifact; the data stays clean.

## Still required from CC before porting: ALGORITHM.md

The two handoffs fully specify the query and the data pattern. What they
do **not** cover is the orchestration around the query in the Groovy code.
Before writing the Python port, CC produces a short ALGORITHM.md from the
Groovy source (path provided in the inventory) covering:

- How the pipeline path (#15) reads the curated tags and iterates
  instances; how the interactive path (#6) invokes the algorithm from the
  picker.
- **Re-run semantics:** with consumed tag TTL never promoted and the
  three-state `conceptsExtracted` flag (absent/false/true), confirm what
  guard the Groovy actually applies on re-runs, and what happens to
  existing typed properties when an instance is processed again (skip,
  replace, or duplicate).
- **Tag-role discrimination:** confirm the pipeline consumes only
  concept-scaffolding tags (role b) and never instance-linkage tags
  (role a); document how the code distinguishes them.
- How results are composed into the instance files (file layout, one
  graph per instance vs. consolidated, prefixes).
- Any quirks found in the Groovy, each flagged as either load-bearing
  behavior or candidate bug — **Rick reviews ALGORITHM.md before the
  port is written.** A ten-minute review of the description beats
  discovering a faithfully-ported bug during shadow-SOT episodes.

## Housekeeping

- The handoffs reference a development transcript at a local path; the
  repo copies must stand alone. The test-data snippets in the Query
  handoff are believed complete for fixture-building; flag if anything
  proves missing rather than improvising data.
- Glossary line for any doc that uses the acronym cold: *TCAP —
  Thesaurus Class Annotation Pattern; ontology-class annotations on
  thesaurus concepts, navigated by the most-specific-property query.*
