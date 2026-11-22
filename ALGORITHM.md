# ALGORITHM.md — TCAP annotation port (#6 Annotate Work, #15 Annotate Doc Instances)

**Status: for Rick's review before the port is written** (per TCAP_README).
Produced from the Groovy source at `/mnt/c/temp/git/cwvaServer/src/main/java`.
This documents the *orchestration around* the most-specific-property query — the
part the two handoffs do not cover — and flags each quirk as **load-bearing**
(port faithfully) or **candidate bug** (fix, with your sign-off). It also lists
the behaviors that are new in the dashboard and therefore *not* in the Groovy.

A ten-minute read here beats discovering a faithfully-ported bug during
shadow-SOT episodes.

---

## 1. Endpoint → class map (from `function/Servlet.groovy`)

| Inventory | Endpoint | Groovy invocation |
|---|---|---|
| #6 Annotate Work | `POST /annotateWork` | `AnnotateWork.handleAnnotateWork(request.reader.text)` |
| #6 (picker data) | `GET /api/annotateWork` | `AnnotateWork.handleConceptsApi()` |
| #14 Tag Markdowns | `/tagMarkdowns` | `CriticalConcepts.process("Tagging")` |
| #15 Annotate Doc Instances | `/promoteMarkdownTags` | `CritInstTagPromote.process(rdfs)` |

The two annotation consumers (#6, #15) **both call one method**:
`AnnotateWork.linkConceptsToWork(subject, curis, rdfs)`. That is the single
shared module to port → `concepts/tcap_navigation.py`. They differ only in how
they gather `(subject, curis)` — interactive picker vs. batch over tag files.

## 2. The shared algorithm — `linkConceptsToWork(subject, curis, rdfs)`

`support/AnnotateWork.groovy:170`. For each concept CURI:

1. Run the most-specific-property **CONSTRUCT** query (the Query-handoff query)
   against `rdfs` = `cwva.Server.getInstance().dbm.rdfs`, the **RDFS-materialized
   model**. Add the resulting triple(s) to an accumulation model.
2. `DESCRIBE $subject` from `rdfs`. If empty, load `/stage/data/{guid}.ttl`
   (an incipient, not-yet-promoted record). If still empty → throw
   `"No existing {subject}.ttl"`.
3. `subjectModel.add(accumulationModel)`; save to `/stage/data/{guid}.ttl` (TTL).

**Load-bearing detail the handoff omits:** the ported query in the Groovy adds,
in *both* branches, a line the handoff query does not have:

```sparql
?op a owl:ObjectProperty .
```

This restricts candidate properties to declared object properties. **Port it** —
without it, datatype properties or untyped predicates with a matching
`rdfs:range` could leak in. (Otherwise the Groovy query is identical to the
handoff, including the `owl:` prefix, which must be in `Prefixes.forQuery`.)

**Hard dependency (confirmed):** the query runs on `dbm.rdfs`, an RDFS-inferred
model. This is TCAP_README port-dependency #1 — the QA store must materialize
RDFS (Fuseki reasoner or RDFLib + owlrl). Tests must assert the inferred type
exists in the fixture before running the query.

**Port note — RESOLVED (2026-07-18):** confirming TCAP_README dependency #2, the
query is **Jena-calibrated**. rdflib mishandles `NOT EXISTS` containing a
property path bound to an *outer* variable (`?rtX rdfs:subClassOf+ ?rt`), so the
cross-branch specificity filter silently no-ops on rdflib — the query returned a
false *tie* on acceptance case 2. Resolution: `concepts/tcap_navigation.py` keeps
`TCAP_QUERY` as the spec of record (the Fuseki QA store runs it directly, Phase
7) and implements the **same algorithm in Python** for correct results on rdflib
until then: effective types (own + broader, RDFS-materialized) → those with a
matching object property → keep the most specific → emit. All four handoff cases
(incl. CrowdHingeBand single-triple + broken-hierarchy tie) pass on the Python
path.

## 3. #6 interactive path — `handleAnnotateWork`

`AnnotateWork.groovy:101`. Body `{ "work": "work:abcd", "related": ["the:x", …] }`.

- Validates `work` non-empty and `related` a non-empty list.
- **Filters `related` to CURIs starting with `the:`** (`curis = related.findAll
  { it.startsWith("the:") }`). This is the interactive path's role filter — only
  thesaurus concepts reach the algorithm. Load-bearing.
- Calls `linkConceptsToWork(workUri, curis, dbm.rdfs)`.
- The picker's concept list (`/api/annotateWork` → `getConceptsData`) is built
  from a **hardcoded scheme allow-list** (`the:paintingTerms`,
  `the:WatercolorPaintScheme`, …) in `queryConceptSchemes`. → **config** in the
  port, not code.

## 4. #15 batch path — `CritInstTagPromote.process(rdfs)`

`support/util/CritInstTagPromote.groovy:37`.

- `loadFilesHere("C:/stage/conceptQueue")` → loads all tag TTL there.
- `loadTags`: `SELECT ?s ?tag { ?s the:tag ?tag }` — reads `the:tag` triples.
- Groups tags by subject into `wmap[subject] = [tag, tag, …]` (CURIs via
  `ju.getCuri`).
- For each `(subject, tags)`: `new AnnotateWork().linkConceptsToWork(subject,
  tags, rdfs)`.

Where the tags come from (**#14, `CriticalConcepts.process("Tagging")`**): reads
`/stage/conceptQueue/*.md|.txt`, extracts `[id=work:GUID]` from the doc text,
invokes the concept agent in `tag` mode (`--tag-ttl`) writing a tag TTL beside
the doc, then moves the processed markdown to `conceptQueue/processed/`. The
agent-produced tag TTL is what #15 consumes.

## 5. Answers to TCAP_README's open questions

**Tag-role discrimination — RESOLVED (2026-07-17, Rick).** `the:tag` is a
**general-purpose association property** between two `rdfs:Resource` instances —
the loosest link in the vocabulary, deliberately untyped (no domain/range, no
ontological commitment; Restructuring handoff). "Scaffolding" names a *usage
context*, not a kind of tag; the same property appears in many places. It
follows that there is **no semantic discriminator even in principle** — object
namespace, `skos:inScheme`, concept-ness: none reliably separates a scaffolding
tag from a durable association, because tags legitimately connect anything to
anything. What varies is the **lifecycle of the file** the tag lives in. The
Groovy's source-based behavior is therefore correct, and the port states it as a
**positive rule**, not an implementation accident:

> **The pipeline's authority over `the:tag` extends exactly to the queue files
> it consumes. A `the:tag` triple anywhere else is opaque user data** — read it
> if useful, but never retract, rewrite, or interpret it.

Tags in conceptQueue pipeline files are consumable inputs (read → promoted to
typed properties → preserved in `evidence/` → never merged into instance data).
`the:tag` triples in instance files are ordinary data the pipeline must never
touch. Phrasing it as a rule (not "conceptQueue happens to hold only scaffolding
tags") guards against a future refactor helpfully "cleaning up" tags it finds in
instance graphs.

**Re-run semantics — RESOLVED (2026-07-17, Rick): skip-if-done + explicit
re-annotate.** The Groovy has **no guard** (`model.add(...)`, Jena set-semantics:
identical triples idempotent, but a *changed* vocabulary **accumulates** — the
stale typed property is never removed). The port replaces that with:

1. **Skip-if-done.** Default runs skip an instance whose `conceptsExtracted` is
   `true` (three-state flag, §7). No accidental accumulation.
2. **Explicit re-annotate = replace.** A deliberate re-annotate **retracts
   exactly what the prior run produced** — the derived typed properties recorded
   in that run's `evidence/` — then re-derives. Evidence is the retraction
   ledger: "retract exactly what run N produced," not "delete anything that
   looks TCAP-shaped."
3. **Instance-level `the:tag` is never a derived artifact.** Replace must never
   treat an instance file's `the:tag` triples as pipeline output, even when they
   connect the same subjects the pipeline touched (work↔criticism tags sit
   adjacent to pipeline outputs in the same files). The evidence-scoped rule
   already guarantees this; stated explicitly so no retraction ever reaches
   them.

**Result composition.** One TTL per subject at `/stage/data/{guid}.ttl`
(DESCRIBE-from-DB or load incipient, merge, save). In the dashboard this becomes
a per-instance file in the QA content tree, terminating in a **promotion unit**.

## 6. Quirks flagged

**Candidate bugs (fix with sign-off):**
- **`guid = workUri.substring(5)`** (`AnnotateWork.groovy:248`) hardcodes a
  5-char prefix (`work:`). Criticism/entity subjects with a different prefix
  length (or full IRIs) break this. The port must resolve GUID → file path
  properly (via prefix expansion / a URI→path map), not by `substring(5)`.
- **Accumulation on re-run** (§5) — no removal of superseded typed properties.
  *Resolved:* skip-if-`conceptsExtracted`; explicit re-annotate retracts the
  prior run's evidence-recorded derived properties, then re-derives.
- **No tie handling.** `model.add m` adds *all* triples the query returns; a tie
  (>1 surviving triple) is silently written to the instance. The port must add
  tie detection + the TCAP_README tie policy (adjudicate via ai_service, record
  to hygiene ledger + workflow-panel open item, never surface tied triples).

**Load-bearing (port faithfully):**
- `?op a owl:ObjectProperty` in both query branches (§2).
- Query runs on the RDFS-materialized model (§2).
- `the:`-prefix filter on the interactive path (§3).
- Per-subject TTL composition via DESCRIBE-or-load-incipient (§2, §5).

## 7. New behavior the dashboard adds (NOT in this Groovy)

- **`conceptsExtracted` three-state flag** (absent/false/true): the pipeline
  flips `false`→`true`; standing query = `conceptsExtracted false`.
  **Erratum (2026-07-17):** TCAP_README says writing `false` on new entities is
  "not in the Groovy — CC builds it." It **is** in the Groovy —
  `EntityEntry.groovy:134` writes `the:conceptsExtracted false` on every new
  entity (and `skos:inScheme the:entities`). What is genuinely new is the
  *three-state interpretation* (absent = grandfathered, never nagged) and the
  pipeline's flip-to-`true`; the entry-form write itself is faithfully ported,
  not invented.
- **Consumed tag TTL never promoted to SOT**, preserved as **curation evidence**
  in the QA repo's non-converged `evidence/` area (CE_DESIGN §3.4 amendment).
  The Groovy neither deletes nor preserves the tag TTL — this is current
  dashboard practice, confirmed against production July 2026.
- **Tie adjudication + ledger/panel** (§6).
- **Concept-agent invocation** moves off the `execCA.bat`/`%1`-API-key pattern
  (key in argv, visible in process listings) to a direct call with the key from
  `ANTHROPIC_API_KEY`, endpoint/dirs/log from config, routed through
  `ai_service` in Phase 5.
- **GUID-safe path resolution** replacing `substring(5)`.

**Forward-looking (Phase 7 browser):** because `the:tag` appears in many places
as a generic association, the data browser and future AI features should render
it generically — "an association; follow it and see" — not assume the
work↔criticism shape is the only one. (The reused cwvaServer-py browser
presumably already treats it this way; noted so the reuse preserves it.)

## 8. Open questions for Rick

1. ~~Tag-role discrimination~~ **RESOLVED** (§5): source-based, stated as the
   positive rule "pipeline authority over `the:tag` = the queue files it
   consumes; anywhere else is opaque user data."
2. ~~Re-run policy~~ **RESOLVED** (§5): skip-if-`conceptsExtracted`; explicit
   re-annotate retracts the prior run's evidence-recorded derived properties and
   re-derives.
3. ~~`the:AI` typing / `the:Collection`/`the:topic` scheme lookup~~ **RESOLVED**
   (§9): keep the hardcoded values faithfully; defer generalization.
4. ~~Concept picker scheme allow-list → config~~ **RESOLVED** (§9): keep the
   hardcoded allow-list; defer.

All four review questions are answered — the ALGORITHM.md gate is clear and the
TCAP port is unblocked.

## 9. Scope (deliberate) — hardcode faithfully, generalize later

**Decision (2026-07-17, Rick): port faithful-first against the working oracle;
generalize once behavior matches.** Current scope is **AI-generated criticisms
only, by design.** The document-concept pipeline can do more than criticisms,
but that is deferred to a later release — tuning surface added before the
process works is just more ways to be wrong while debugging. The narrowness is
*chosen*, not a gap.

- **Hardcode, but hoist.** The frozen values — the `the:AI` qualification
  filter, the `the:Collection`/`the:topic` topic-scheme lookups, and the concept
  scheme allow-list — go in **one named constants block at the top of the
  module**, commented *"deliberately hardcoded; process generalization deferred
  to a later release."* No config machinery; but the later release becomes a
  mechanical extraction, not an archaeology dig, and no future session mistakes
  the hardcoding for an oversight to helpfully "fix."
- **Grandfathering reconciliation (state in the parity scenario).** The new
  `conceptsExtracted` guard layers on top of the hardcoded qualification and the
  two interact on grandfathered docs: Groovy is effectively "typed `the:AI` →
  tag it, every run, no guard"; the port is "typed `the:AI` **and**
  `conceptsExtracted false`." Old entities with no flag qualify under Groovy but
  not under the port — exactly the intent (they are the not-worth-updating
  cohort), but it means the **parity comparison must use flag-carrying entities**
  or it will show a deliberate difference someone chases as a bug. One sentence
  in the scenario notes.

---

*Glossary: TCAP — Thesaurus Class Annotation Pattern; ontology-class annotations
on thesaurus concepts, navigated by the most-specific-property query.*
