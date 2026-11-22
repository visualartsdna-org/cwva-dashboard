# PLAN FRAGMENT — Phase 4.5 exit conditions + shadow SOT (2026-07-19, v2)

**MERGED into PROJECT_PLAN.md 2026-07-19 — historical provenance only, not
normative.** Scope was echoed back and confirmed before implementation.

Merged with three changes to what is written below:

1. **A new exit item 0 was added above everything here**, gating all of §2/§3/§4:
   the Layer-1 denial of trusted-side control state (`a1f834f`). Answering §1b
   surfaced a live sandbox escape — the confined tool surface could assemble
   arbitrary code execution as the orchestrator from `copy` + `write_text`
   against `.git/hooks/`, no `chmod` required. Credential-adjacent work
   sequences behind it.
2. **§1b is settled, and inverts the premise below.** The blocker was never
   worker visibility: the worker could read *and write* the QA `.git`. It is
   that git is not an agent-side capability (law 6) and the worker cannot exec
   (law 2). Candidate shape 1 (pass git-derived inputs into the worker) is
   rejected — it would have dignified the escape as architecture. Shapes 2/3
   (pure `evaluate()` + trusted-side enrichment) are adopted.
3. **§2c and §2e are recorded as settled mechanisms, not open questions:** the
   clone needs new code because `sync()` conflates read-source with
   write-target (shape: a read-only source transport); and production safety is
   a `ReadOnlySource` *type* with no `converge` method, so a push against
   production cannot be constructed rather than being rejected at runtime.

The §2 "empty shadow populated by first promotion" suggestion from the CC
session is withdrawn, per §2's correction — the clone-from-live decision stands.

---

## 1. Deferred standing queries — resolve exit-gating and the architectural blocker

Current state in the plan: scrape staleness, drift-awaiting-adoption,
and uncommitted-WIP standing queries are declared but deferred, "(need
the git/audit orchestrator-tool context)" — tracked as [~] under the
workflow panel, but **absent from the Phase 4.5 exit criteria**. The
chat-side position (v2 handoff): these should land before phase exit,
because they are what makes the panel honest about promotion state; a
panel that can't show drift, WIP, or staleness reports a cleaner world
than exists.

**1a. Exit-gate them.** Add the three deferred standing queries to the
Phase 4.5 exit list alongside the carried gaps and Scenario #1.

**1b. But first, surface the design question the deferral note implies.**
`workflow.state` is a registry tool; per law 10 and the two-context
model, registry tools execute in the confined worker, which cannot see
the QA git repo or the audit log (both orchestrator-side, by design).
If that is why these queries were deferred, then "implement them" is
not a task, it's a design decision about where git/audit-backed
standing queries execute. Candidate shapes (advisory, not chosen here):
the engine gains orchestrator-computed inputs passed into the worker;
or `workflow.state` splits into worker-computed and orchestrator-
computed halves merged at the panel endpoint; or the panel endpoint
(trusted side) enriches the tool result. **CC: state which constraint
actually blocked these, and propose the shape, before implementing.**
Do not weaken the confinement boundary to make a query convenient.

Note: the drift-adoption episode (00b2133) now provides a live fixture
the drift query can be asserted against — whatever shape is chosen,
that assertion should ride the existing episode via the new per-step
`expect`.

## 2. Persistent shadow SOT — apply the settled scoping decision

The plan already settles this: "Shadow SOTs are cloned from the **live
GCP bucket** (disposable copies)" (Phase 4.5 scoping decisions). The
2026-07-19 session's suggestion of an empty shadow populated by first
promotion contradicts that settled decision and is withdrawn. What the
test suite built (ephemeral per-test prefixes) satisfies the smoke-
episode use; what remains is the **persistent** shadow the exit
criterion "usable by a human against a shadow SOT" and the Scenario #1
recording both need. Make it concrete:

**2a. Transport entry.** Stable prefix on the test bucket (e.g.
`shadow-sot/`) as a transport entry in config/dashboard.rson, distinct
from `cwva-dashboard-tests/<uuid>/`. No folder pre-creation — flat keys
only; never use the GCS console "Create folder" (its zero-byte `/`
placeholder objects would surface as spurious drift and a
file/directory collision in sync).

**2b. Seed by cloning production**, per the settled decision: read-only
against the production bucket, writes only to `shadow-sot/` on the test
bucket. This is also what the conceptsExtracted triage (§4) requires —
grandfathered vs. pending states exist only in real content — and it
makes Scenario #1 a recording against a realistic SOT (drift, orphans,
legacy quirks), the population Phase 5 admission tests will face.

**2c. Clone through the sync machinery, not around it** — no ad-hoc
copy, no CLI path (the Windows gcloud CLI is broken regardless). The
clone doubles as the first sync-at-scale exercise. If the current
wiring can't express "source bucket A → shadow prefix on bucket B"
without new code, say so before building — design conversation, not
implementation detail.

**2d. Measure, don't optimize.** GCS snapshot md5 vs QA sha256 forces
full re-fetch on sync (known, correct-but-wasteful). Record object
count and wall time for the clone and the first re-sync. No hash
caching or md5 bridge unless the numbers are painful; candidate cleanup
entry, not an exit condition.

**2e. Safety invariant, in code.** This work is the first time
production credentials and the promotion machinery coexist. The
production bucket must be structurally unable to appear as a converge
target — enforced in code (e.g. the production bucket name is only ever
a snapshot/fetch source in the clone path, never constructible as a
transport push destination), per the security-in-code-not-prompts law.
State the guard when echoing scope back.

## 3. Suggested sequencing (advisory, not normative)

1. §1b design answer → standing queries, drift asserted via the episode.
2. Shadow transport entry + production clone (§2), with §2d measurement.
3. Panel run against the seeded shadow → Rick's triage (§4).
4. Scenario #1 human recording against the seeded shadow.
5. Carried gap tests as filler throughout.
6. Then 4.5 exit → Phase 5 Stage A.

## 4. New exit item — conceptsExtracted backlog triage (Rick-executed)

Not currently in the plan; add under Phase 4.5 exit. On the first panel
run against the synced shadow (real production content), Rick triages
the conceptsExtracted backlog: flip done items to `true`, dismiss the
rest — the first real exercise of `workflow.dismiss` and the dismissal
half of the obligations model against non-fixture data. CC prerequisite:
§2 complete.

## 5. Historical rationale (fenced — not normative)

Cross-boundary audit result, corrected from the first draft of this
fragment: of three chat-side items suspected lost at the context
boundary, only the triage (§4) was actually absent from the plan. The
shadow-clone intent was already a settled scoping decision the new CC
session proposed against, having read a handoff that didn't repeat it —
argument for keeping settled scoping decisions in the startup-read
path, not only in phase bodies. The standing queries were tracked but
not exit-gated, and their deferral note encodes an architectural
constraint (worker confinement vs. orchestrator-side git/audit) that
the chat-side "land before exit" instruction had not engaged with —
argument for recording *why* something is deferred, as that note did,
since the reason is the real content. Durable rule retained: anything
phrased "should happen before X" in a session is exit-condition
material and gets merged into PROJECT_PLAN.md the same session
(extends standing rule 3, which currently covers CE_DESIGN.md only).
