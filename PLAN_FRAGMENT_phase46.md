# PLAN FRAGMENT — Phase 4.5 close + new Phase 4.6 (dashboard replication)

**MERGED into PROJECT_PLAN.md 2026-07-24 — historical provenance only, not
normative.** Scope was echoed back and confirmed before implementation.

Merged with these findings folded in:

1. **§3's SHACL question, answered from the code:** there are no SHACL shapes at
   all — `shacl_gate` is wired but never armed, and `record_tools` writes
   `vad:hasPaper` unvalidated. The Groovy dropdowns were the sole dangling-
   reference guard, so the referential-integrity shape is confirmed 4.6 scope,
   built together with the affordance enums as two halves of one guarantee.
2. **Enforcement locus made explicit (design-brief addition):** `validate_args`
   is hand-rolled and enforces only `additionalProperties`/`required`/`type` —
   it **ignores `enum`/`format`**. So "enforced at Phase-2 arg validation" is
   not yet true for enums; the design states, per field-type, where each
   constraint is enforced (dispatch vs. gate), and notes dynamic-vocabulary
   fields are a gate concern because the confined worker must not enumerate the
   store. Extending `validate_args` for `enum`/`format` is an explicit 4.6 task.
3. **§3 mechanism feasibility confirmed:** `build_default_registry(
   standing_queries, domain, sites)` already receives `sites`/`domain`, so the
   config-sourced `work_on_site` enum and the `has_artist_profile` default need
   no plumbing change.

The affordance design lives in `AFFORDANCE_DESIGN.md` (Rick-reviewed before
renderer work, per the extraction-doc convention).

---

## 1. Phase 4.5 closes at unit-test level

Phase 4.5 is complete when its work is proven **by test**. Everything
requiring synced real content or a human at the dashboard moves to 4.6.

**Re-homed to 4.6** (they cannot complete at unit-test level, and must
not fall into the gap between phases):
- conceptsExtracted backlog triage — needs synced production content.
- Scenario #1 human recording — needs a driveable UX (see §6).
- Shadow→QA sync itself — first sync is now 4.6's opening move (§5).

**Stays in 4.5** (test-level, unaffected):
- Deferred standing queries (WIP / drift / staleness) with the §1b
  shape already resolved: `evaluate()` stays pure and sandbox-derived;
  the panel endpoint and agent-narration path (both trusted) enrich with
  orchestrator-computed git/audit items. No git input crosses into the
  worker.
- Carried Phase 1–4 gap tests: mid-convergence failure per transport,
  Windows CI runner, SOT-side orphan report test.

Revised 4.5 exit: exit item 0 (landed) + carried gaps + standing
queries, all at test level. The image-dependent items (pHash against
real originals, orphan heuristic at corpus scale, binary promotion at
real sizes) and the migration first-run remain explicitly unexercised,
carried forward as-is — not silently discharged by the phase close.

## 2. Phase 4.6 — Existing-dashboard replication

**Goal:** the new dashboard supports the functionality of the existing
(Groovy) dashboard, driven by a human, against real synced content.

**Two reference sources, two different roles — keep them distinct:**
- `html/function.html` is the **layout** reference: tab/card structure,
  field grouping and ordering, which controls sit together. Preserve it.
- The **Groovy HTML-generating and request-handling code** is the
  **semantics** reference: which fields are closed sets and what is in
  them, which are file choosers, defaults, derived values, validation,
  and what the handler does with each field on submit. These behaviours
  are reimplemented over the existing registry tools — not ported as
  code.

**Scope is the intersection** of function.html's surface and what is
already ported. Explicitly out of 4.6 because they are dependency-gated:
reports #19/#20/#22/#23 (QA store, Phase 7), concept pipeline
#12/#13/#14/#16 (AI, Phase 5/8), proof #5 and brand #7 (deferred).
"Replicate the existing dashboard" means the previously-defined limited
functionality, not the full historical surface.

**Polish is still later.** 4.6 restores parity; the improvement pass
(config-templated UX, richer cards) remains a later phase.

**Groovy-extraction convention applies.** These are Groovy-sourced
behaviours, so the standing convention holds: an extraction doc
(ALGORITHM.md-style) precedes the port, Rick's review gates it, and
quirks are classified load-bearing vs. candidate bug. That gate has
already paid for itself three times (owl:ObjectProperty constraint,
substring(5), the conceptsExtracted erratum). One extraction doc per
function group, reviewed before the UX for that group is built.

## 3. The affordance layer (resolved decision — schema-first)

**Problem being fixed.** Every registry tool schema types its fields as
`string` (except two `number`s). No enums, no formats, no file
references. The renderer therefore produces a text box per field, and
the affordances the Groovy form carried — the four `type` radio options,
the `hasPaper` dropdown, the `units` select, the site choice, the file
chooser — were lost at the **schema** layer during the port, not at the
UX layer.

**Decision: the affordances live in the tool schemas, not in bespoke
per-function HTML.** The generic renderer is upgraded to honour them.
Bespoke UI is permitted only where a schema cannot express the
affordance (the concept picker is the known case — already on the
watch-list).

**Rationale — this is a Phase 5 decision as much as a UX one.** Phase 5
puts an agent on the same tools as the second driver. A constraint in
the schema binds both drivers and is enforced at the existing Phase 2
deny-by-default arg validation. A constraint in a hand-written `<select>`
binds only the human, and reappears in Phase 5 as malformed AI output
plus a vocabulary the agent has no way to enumerate. Schema-first also
preserves the zero-UX-code property (new tools surface automatically,
held by the synthetic-tool contract test) and keeps law 10 meaningful
rather than nominal.

**Mechanisms** (naming is CC's call; the shapes are the decision):
- **Static closed sets → JSON-Schema `enum`.** `units`
  (cm|inch|meter|pixel), `type` (vad: work classes), `file_format`.
  Several are already spelled out in their own `description` strings —
  they only need to become machine-readable.
- **Config-sourced sets → `enum` built at registry-build time.**
  `work_on_site` from `sites`, which `build_default_registry(
  standing_queries, domain, sites)` already receives.
- **Dynamic vocabulary → a schema annotation resolved by the trusted
  side** (e.g. `x-vocabulary` naming a standing query / `.sparql` file);
  the panel endpoint resolves it via the existing read-only SPARQL path
  and hands candidates to the renderer. Covers `has_paper`,
  `background`, and is the same mechanism the concept picker needs — build
  once, serves both. Values come from the store; nothing is hardcoded.
- **File references → a schema annotation** (e.g. `x-file-ref` naming a
  sandbox subtree) rendered as a picker over `fs.list`. Covers `image`,
  `image3d`, `qrcode`.
- **Formats/defaults** — `format: date` on `recorded_date` /
  `completed_date`; config-sourced default for `has_artist_profile`
  (required, effectively constant for a single-user CE instance).

**Correctness, not only usability.** `additionalProperties: false`
rejects unknown *keys*; nothing today rejects `units: "metre"` or a
misspelled `the:StrathmoreColdPres`. Those generate syntactically valid
TTL and pass the parse gate. **Check whether the SHACL shapes assert
referential integrity for `vad:hasPaper` / `vad:background` against the
thesaurus** — if they do not, the Groovy dropdowns were the only thing
preventing dangling references, and the enums/vocabulary annotations
restore that guarantee at arg-validation time. Report the answer; if
absent, a referential-integrity shape is 4.6 scope.

**Terminology caution:** "semantic layer" in this project usually means
RDF. Prefer *affordance layer* (or an equivalent unambiguous term) in
the docs for this schema-annotation work, to avoid a collision that will
confuse a later reader.

**"Text-based form entry is deprecated"** means the all-text *rendering*
is deprecated. The generic registry-driven renderer is upgraded, not
replaced — replacing it with per-function HTML would discard the
zero-UX-code property and the dual-driver benefit above.

## 4. Deferred / assumed-unchanged

Phase 5 remains AI workflow implementation over the Phase 4.x function
surface. All other assumptions from the current plan stand.

## 5. Opening move — sync shadow content into QA, first

4.6 begins by syncing the seeded shadow (534 objects; TTL / documents /
stats) into QA, before UX work, so surprises surface against real content
early rather than mid-phase.

Checkpoint at first sync — record, do not assume:
- The QA repo initializes under the current managed-extension list, so
  the storage policy applies from the start and `migrate_to_pointer_
  management` does **not** run (it remains the scheduled-first-run item).
- Expected split from the dry run: ~463 files / 3.9 MB git content;
  ~71 files / 128.4 MB pointer-managed. Deviation is a finding.
- The shadow's **flat** production layout exercises the per-target
  placement map and the layout-translation path, not the identity case
  fixtures use — first real exercise of §3.6.
- Capture the post-sync baseline of gate findings, orphan report, and
  panel obligations **immediately**, before triage. The shadow has no
  images, so TTL will reference absent assets; that baseline is what
  keeps partial-copy artefacts from being read as real defects (and
  keeps a clean-looking orphan report from being read as evidence the
  heuristic works at scale).

## 6. Per-function acceptance protocol — and it produces the scenario corpus

Each function is built, then Rick tests that function and its workflow
before the next is started. RDF Entry first: enter a newly-finished work
in QA → promote → land on the shadow SOT → verify.

**Instrument the recording before the first test, not after.** Rick's
manual RDF Entry session *is* the reserved Scenario #1 (recorded human
entry, routing-policy admission seed). The harness is driver-agnostic by
construction — steps are registry-tool invocations — so capturing the
step sequence while he drives is nearly free, whereas reconstructing it
afterwards is retyping from memory. Each subsequent function test adds an
episode, so 4.6 yields the human-driven scenario corpus as a by-product
rather than as separate work.

## 7. Known partial — updateWorkOnSite

Its 4.6 test can exercise scrape / extraction / confirmation queue, but
**not** pHash matching against real originals: the shadow carries no
images by decision. Record this as a known partial at the time it is
tested, so it is not read as a full pass — it remains one of the three
items awaiting a full-corpus pass.

## 8. Phase 4.6 exit gate

- Shadow content synced into QA; first-sync checkpoint (§5) recorded.
- Every in-scope function from function.html (per §2 intersection)
  working with its Groovy-sourced affordances and semantics, via the
  upgraded generic renderer.
- Extraction docs written and Rick-reviewed for each function group.
- Rick's per-function acceptance passed, with each session recorded as a
  scenario episode (Scenario #1 onward).
- Main workflows tested end-to-end against the shadow SOT: entry →
  gates → preview → promote → converge → refresh.
- Known partials (§7) and the carried image-dependent items recorded as
  unexercised, not discharged.

## 9. Historical rationale (fenced — not normative)

Discovered by Rick opening the dashboard for the first time and finding
one flat page of text inputs where he expected function.html's tabbed
layout with gaps. Diagnosis: the plan's own language ("registry-driven
shell"; "templating the full function.html cards from config is a later
polish, not a blocker") licensed the shell, and the affordances had
already been dropped upstream at the schema layer during the Groovy
port. No decision point ever chose the flat form — it accreted through
deferral, and no test could catch it, because "function works under a
human-driven UX" is satisfied by a text box that accepts a valid value.
Same silent-divergence shape as the week's other findings; the
difference is that this one was only detectable by a human looking at
it. Consequence worth keeping: exit criteria phrased in terms of
function rather than fidelity will pass on a degraded surface.
