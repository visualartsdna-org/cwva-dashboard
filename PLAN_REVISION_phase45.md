> **MERGED into PROJECT_PLAN.md (Phase 4.5 + Phase 5) and CE_DESIGN.md (§9.1)
> on 2026-07-16 — historical provenance only, not normative.** The canonical
> docs are the source of truth; do not treat anything below as pending work.

# PLAN_REVISION — insert Phase 4.5, restructure Phase 5

Merge-ready fragment for PROJECT_PLAN.md (repo copy is source of truth).
Replaces the existing Phase 5 section; Phase 4.5 inserts after Phase 4.
CE_DESIGN.md §9 additions at the end. Numbering of later phases unchanged.

---

## Phase 4.5 — Dashboard UX + framework function port

Goal: every framework function working under a human-driven UX, proven by
real workflow episodes against real data on multiple transports, before
any AI wraps it.

**Law (add to CLAUDE.md non-negotiables): UX handlers are thin bindings
over registry tools — the same tools the agent will call.** Nothing
UX-reachable may bypass the registry; the registry is where confinement,
audit, and provenance live. Ported functions that write toward SOT
terminate in promotion units — no legacy direct-write behavior survives
the port.

- [ ] Integrate the existing dashboard UX (handoff document + current
      html) with the FastAPI app; UX routes dispatch through the tool
      registry only.
- [ ] Port the Groovy functions supporting the UX to Python as registry
      tools (one schema per function; MCP-shaped, per Phase 2 convention).
      SOT-writing functions terminate in promotion units; read-side
      functions run against the QA store.
- [ ] Scoping decision recorded: what Phase 4.5 absorbs from the planned
      cwvaFunction-py faithful port, and what (if anything) remains a
      separate deliverable in that project.
- [ ] **Shadow SOT** per transport: disposable clones of production
      content (bucket, git remote, git local, plain files). Episodes run
      against shadows until several complete cleanly; live SOT only after.
- [ ] **Scenario capture**: each smoke episode recorded as a scenario file
      — initial state, steps, expected end state (SOT contents, QA HEAD,
      queue positions). Scenarios are replayable artifacts, stored in
      tests/scenarios/.
- [ ] Smoke episodes: real workflow episodes with real data, including
      commit/refresh points, drift adoption, at least one rollback, and
      binary replacement — across at least two transports.
- [ ] Close the carried Phase 1–4 test gaps before exit:
      - mid-convergence failure per transport family (inject failure
        mid-push; re-converge heals to SOT ≡ QA),
      - Windows CI runner for the Layer-1 corpus + fileops tests,
      - SOT-side orphan report test (pre-seeded orphan in a SOT fixture).

Exit: all dashboard functions usable by a human against a shadow SOT;
scenario corpus captured; carried gaps closed.

## Phase 5 — AI coverage, then agnosticism  [priority 4, restructured]

Stage A — AI coverage (Anthropic-first):
- [ ] `ai_service/` seam from the first line of code: handlers never touch
      an SDK; everything goes through `ai_service.call(task_profile,
      inputs)`. One adapter (Anthropic) initially.
- [ ] Build AI coverage against every registry function (coverage is
      automatic where Phase 4.5's law held: the agent calls the same
      tools the buttons call — verify no orphaned functions).
- [ ] Replay the Phase 4.5 scenario corpus through the agent: same
      scenarios, two drivers (human UX vs agent), compared end states.
- [ ] **Function classification**: from scenario runs, classify every
      AI-involved task into a capability tier; write the task profiles
      from this empirical record. This defines what API compliance means.

Stage B — agnosticism and routing:
- [ ] Second adapter (OpenAI-compatible / OpenRouter) — or LiteLLM if the
      Stage A surface inventory argues for it. Recorded doubles are
      provider-neutral, keyed by task profile; CI runs the suite against
      both wire formats offline; opt-in live smoke lane.
- [ ] **Three-layer routing model** (see CE_DESIGN §9 additions):
      profiles → capability floors (stable);
      provider catalog → tier-to-model mapping with prices (volatile,
      config; refreshable from published pricing);
      router → cheapest model satisfying the floor.
- [ ] **Admission by scenario**: a model enters a tier only by passing
      that tier's scenario suite (from Phase 4.5/5 corpus).
- [ ] **Escalation ladder**: start at floor tier; on validated failure
      (schema repair exhausted, gate rejection) escalate one tier, capped
      N attempts. Escalation-rate metric per model → demotion signal.
- [ ] **Metering**: every ai_service response carries model identity
      (shared plumbing with prov: attribution), token usage, computed
      cost; audit-logged by profile/tier/model. Per-episode cost report.
- [ ] Schema validation with retry/repair on every structured output;
      malformed-output and budget-enforcement tests; profile-swap
      invariance test (same task, both adapters, schema-identical results
      from doubles).
- [ ] Secrets in environment only; ai_profiles.yaml and the provider
      catalog never contain keys.

---

## CE_DESIGN.md §9 additions (routing policy)

- Task profiles declare **capability floors** (tiers), never model names.
  Suggested tiers: T0 extraction/classification, T1 summarization and
  violation-translation, T2 structured generation (SPARQL, form drafting),
  T3 orchestration and curation reasoning.
- A **provider catalog** (config) maps tiers → concrete models with
  current prices; price changes are catalog edits (optionally refreshed
  from published pricing), never profile or code changes. Catalog review
  on a cadence (e.g. monthly); no live spot arbitrage in v1.
- **Admission by scenario**: models enter tiers empirically, by passing
  the tier's scenario suite — never by spec sheet.
- **Escalation ladder**: floor tier first; validated failure escalates one
  tier (capped). Validation is code and free, so cheap-model failures are
  caught, not shipped. Escalation rate per model is the demotion signal.
- **Metering**: model identity, usage, and cost on every call, tagged by
  profile/tier/model in the audit stream (provenance and cost attribution
  share plumbing).
