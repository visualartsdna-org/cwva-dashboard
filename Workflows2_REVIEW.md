# Workflows2 — design review (rounds 1–4, consolidated)

**Updated 2026-09-26.** Supersedes earlier rounds; it carries forward what round 1 found and folds in Rick's answers. Nothing here has been built. Counts marked as measured come from the real QA store (`~/.local/share/cwva-dashboard/sandbox/ttl`, model + vocab + data, 17,879 triples) and are reproducible — re-run them when the data moves on.

Abbreviation used throughout: **DTS** = the derive / tag / summarize workflow.

---

## 1. Settled

| # | Decision | Source |
|---|---|---|
| A | The selection query in Workflows2.txt is withdrawn. There will be **one rule per queue state** instead. | Rick, round 2 |
| A | **Queue status must be prominent and very accessible** — the dashboard will host workflows in myriad states, and a user cannot make progress without seeing them. | Rick, round 2 |
| B | State is **per entity**, recorded as stamps in a blank-node structure under `the:status`, with a computed `rdfs:label` naming the current state. | Rick, round 2 |
| B | `the:conceptsExtracted` supported the old workflow and is retired. The prod SOT is to be **assumed up to date** with all expected concept processing. | Rick, round 2 |
| C | Distribution is **implied by finishing a step**, never a card the user has to press. Each of the four steps ends in one promotion. | Rick, round 2 |
| C | A process may be **stopped and resumed mid-way**, skipping completed steps. This is why state is per entity rather than per session. | Rick, round 2 |
| D | **Tagging goes through TCAP**, exactly as the annotation service does: the agent proposes concepts, the ontology decides the property. | Rick, round 2 |
| D | The concept agent exists and runs in a separate process today; integrating it is part of this development. Its relationship to `ai_service` (token budgeting) is **deliberately not yet designed**. | Rick, round 2 |
| E | Review screens are **include / exclude per item**, not editors. The curator says "not this concept", "not this tag". | Rick, round 2 |
| E | History of what the agent proposed is **captured now**, surfaced later. How it is surfaced is out of scope. | Rick, round 2 |
| F | Concept-scheme enrollment is a **separate curatorial tool** and is not needed by DTS. | Rick, round 2 |
| F | Keeping the vocabulary and the model in step for TCAP is an **ontology task**, and it needs a way to distribute to `model/` and `vocab/`. | Rick, round 2 |
| G | A criticism document belongs to a single work in the normal case. Criticism of a **collection is out of scope**. | Rick, round 2 |
| H | The sandbox is always current; **downstream requires a refresh** and does not get one automatically. | Rick, round 2 |
| 9.1 | The agent takes its thesaurus **from the QA store**, not from the running server's SPARQL endpoint. DTS therefore needs no distribute-and-refresh barrier between derive and tag. | Rick, round 3 |
| 9.3.2 | Creating broader terms is a **thesaurus-modeling exercise, a discrete task** — not part of DTS. But the information about orphaned concepts is **valuable to that task and must be kept**. | Rick, round 3 |
| 9.4 | The grounding BN **keeps the match type** alongside the score. | Rick, round 3 |
| 9.4 | Matching follows **CE_DESIGN §6**: the label set is `skos:prefLabel ∪ skos:altLabel ∪ rdfs:label`, on both sides of the comparison. | Rick, round 3 |
| 9.5 | The orphan backlog lives in **`evidence/`** — committed to QA git so it has history, excluded from convergence so it never reaches the SOT. | Rick, round 3 |
| 2.1 | DTS has **two stopping points per stage**, not one: pending derivation and pending curation, then pending tagging and pending curation. **A stage cannot be left until it is curated.** | Rick, round 4 |
| 2.2 | **The dashboard owns the concept agent now.** New functionality belongs in dashboard code; agent functionality is transferred out or eliminated. The dashboard composes the grounding blank node after collecting the information. | Rick, round 4 |
| 2.3 | **There are no re-runs.** DTS is once per entity; an error is recovered by surgically deleting and starting again. (A possible future exception: re-summarizing at a higher cost tier after a cheap first pass.) | Rick, round 4 |
| 2.4 | **One structure carries state and provenance together** — the status node holds both. | Rick, round 4 |
| 2.5 | In-progress state **does reach the SOT**, and downstream seeing "derived but not yet summarized" is not a problem. | Rick, round 4 |
| 2.1a | **Summarization has a curation step too** — Rick reads summaries before release, though not to edit them. Seven queue states. | Rick, round 5 |
| 10.2 | The stamp names stand: `entityCreated`, `derived`, `derivationCurated`, `tagged`, `taggingCurated`, `summarized`, `summaryCurated`. | Rick, round 5 |
| 10.3 | **"Reset DTS state for this entity"** is the supported error path, replacing hand-editing TTL. | Rick, round 5 |
| 10.8 | **Show all the queue information prominently first**, then work on UX design. Real estate is accepted. | Rick, round 5 |
| 2.1b | **`entityCreated` is inferred**, not stamped — the entity's existence is the evidence. Six stamps, not seven. | Rick, round 6 |
| 2.3a | **Reset goes all the way back to "entity created"** — the whole status node and everything the DTS stages wrote. | Rick, round 6 |

---

## 2. The state model — settled in round 4

The shape Rick proposes puts the stamps in a blank node so the detail has somewhere to live without spraying predicates across the entity:

```turtle
the:entity_1 a the:Entity ;
    the:status [
        # stamps here
        rdfs:label "tagged" ;   # computed from the stamping
    ] ;
.
```

**This shape suits the machinery well, which is worth knowing before we argue about it.** The draft diff pairs blank nodes by position rather than by graph hash (fixed 2026-09-19), and a single child under one predicate is identified by its path alone — so the contents of the status node can change freely and still diff as one changed line rather than as the whole node removed and re-added. If status nodes ever become a *series* (one per run), they become siblings, which the same code tells apart by content.

**The legacy problem is nearly nil, and one predicate can close it.** Of 58 AI document entities, **57 carry `the:conceptsExtracted`** and **exactly one carries neither that nor a summary**; all 58 already carry TCAP typed properties. So `conceptsExtracted` can retire from its old job and take a new one — *"processed under the pre-DTS flow"* — which makes "assume prod is up to date" true by construction, requires no migration, and leaves exactly one record to fix by hand.

### The states, as settled in round 4

DTS has **two stopping points per stage**, because a stage cannot be left until it is curated — and that holds for all three stages, summarization included: Rick reads summaries before release, though not to edit them. That gives seven queue states, one of which is a folder count rather than a rule:

| # | Queue | Rule | Source |
|---|---|---|---|
| 0 | Documents to process | a file in the drop folder with no entity | `fs` |
| 1 | Pending derivation | entity created, not derived | `sparql` |
| 2 | Pending derivation curation | derived, not curated | `sparql` |
| 3 | Pending tagging | derivation curated, not tagged | `sparql` |
| 4 | Pending tagging curation | tagged, not curated | `sparql` |
| 5 | Pending summarization | tagging curated, not summarized | `sparql` |
| 6 | Pending summary curation | summarized, not curated | `sparql` |

An entity with `summaryCurated` is complete and appears in no queue.

**The stamps this implies**, for confirmation — these names are mine, not Rick's:

```turtle
work:b4f470cc-… a the:AI, the:Entity ;
    the:status [
        rdfs:label            "tagged" ;          # display; what last happened
        the:derived           "2026-09-26"^^xsd:date ;
        the:derivationCurated "2026-09-26"^^xsd:date ;
        the:tagged            "2026-09-26"^^xsd:date ;
        # then taggingCurated, summarized, summaryCurated
        # prov: attribution for the agent steps lives here too (2.4)
    ] .
```

**Six stamps, and no `entityCreated`** (Rick, round 6): the entity's existence is the evidence, so stamping it would record a fact the record already carries. An entity with no status node at all is therefore queue 1 — which also makes the reset trivially definable, because *every* triple in the status node is something DTS put there.

**The queue rules should key off the STAMPS, not off the label.** The label is a denormalization — the same fact in two places, able to disagree — and making the rules depend on it means a drifted label silently empties or fills a queue. Testing the stamps costs one extra triple pattern per rule (`has X`, `not has Y`) and cannot be wrong. The label stays, because a person reading a record wants to see "tagged" rather than reconstruct it, and because one writer composes the whole node at once — but nothing load-bearing depends on it.

**Note that summary curation is a different act from the other two.** There is nothing to include or exclude in a single summary, so the screen is accept or send it back — which is also the natural home for the future "try again at a higher cost tier" (§2, no re-runs). The stamp is the same shape; the screen is not.

**One thing to confirm:**

**2.1b Is "entity created" a stamp or an inference?** An entity exists, so its existence is already the evidence. A stamp records *when*, which is worth having if the queues ever sort by age — and the first queue is a folder count precisely because nothing exists yet to carry a date (2.6).

### The consequences of "no re-runs"

Settled: DTS runs once per entity, and recovery is surgical deletion. That collapses the hardest part of the state model — one status node, stamps written once, no history to disambiguate, no "which is current". It also means the status node is small and monotonic, which is exactly what the positional blank-node diff renders well.

**Decided (Rick, round 5): "reset DTS state for this entity" is the supported error path.** Hand-editing TTL was the alternative, and it is what law 12 exists to prevent — Edit Record is restricted to `vad:ArtForm` subclasses and will not open an entity, so there was no supported route at all. The action removes the status node and whatever the failed stage wrote, through a registry tool, ending at the ordinary review stop like every other writer.

**Decided (Rick, round 6): all the way back to "entity created".** Since `entityCreated` is inferred and every stamp in the status node is something DTS wrote, the reset has a one-line definition — **remove the status node and everything the DTS stages produced** — and the entity falls back into queue 1. The kinder alternative, resetting only the failed stage, would have had to answer for concepts derivation already wrote into `vocab/` and may have distributed; that question is now deferred rather than answered, which is the right trade before any failure mode has actually been seen.

**What the reset has to reach is wider than the status node**, and this is the part to get right when it is built: the derived concepts in `vocab/`, the tags placed on the entity by TCAP, the summary, and the proposal records in `evidence/`. Some of those may already be in the SOT, because each stage distributes. So the reset is a promotion unit like everything else — it stages deletions, shows them at the review stop, and converges only on approval. It is not a quiet cleanup.

### The legacy population

**The legacy problem is nearly nil, and one predicate can close it.** Of 58 AI document entities, **57 carry `the:conceptsExtracted`** and **exactly one carries neither that nor a summary**; all 58 already carry TCAP typed properties. So `conceptsExtracted` can retire from its old job and take a new one — *"processed under the pre-DTS flow"* — which makes "assume prod is up to date" true by construction, requires no migration, and leaves exactly one record to fix by hand.

### 2.6 The first queue has no entity to carry state

"Documents to process" means a file in the drop folder that has no entity yet. That count is a folder count, not a SPARQL rule. The standing-query engine already supports both (`source: fs | sparql`), so this costs nothing — it is just worth saying out loud that one of the six rules is a different kind of rule.

---

## 3. The concept agent contract

Tagging through TCAP is settled, and it has a consequence worth stating plainly: **the agent proposes concepts, never properties.** TCAP walks the ontology to the most specific property whose range accepts the concept, and records a tie rather than guessing between equals. An agent that proposed `vad:hasProcess the:FacetedSurface` directly would be asserting an answer the ontology derives, and the two could disagree silently.

**Where the call happens is forced by the architecture, not by preference.** The Landlock-confined worker cannot resolve DNS — a fetch to a hostname fails with `EAI_AGAIN`, measured 2026-09-09 — so a tool that called the agent would silently return nothing. The call must be a trusted-orchestrator effect, and the pure result handed to a registry tool that does the writing. That is the same split as the ffprobe duration probe. If the agent is reached over HTTP it also becomes a fifth member of the sanctioned network-effect class (law 11), which brings its rules with it: the target is resolved **by configured name**, never by a URL supplied in a request, and its credential never enters the audit log.

### Open questions

**3.1 What does the dashboard send, and what comes back?** For derivation: the document text, or its IRI and let the agent fetch it? Does it send the existing thesaurus (the agent "loads the thesaurus and can locate broader candidates", so perhaps not)? For tagging: the document plus which concepts are available to choose from? The shape of the answer matters as much — a declared schema is a prerequisite for the structure-not-strings testing law 8 requires, and for a recorded double that lets the suite run without the agent.

**3.2 One call site, so the agent can move later.** The `ai_service` relationship is deliberately undesigned, which is fine — but the workflow should reach the agent through a single trusted-side function with a typed result, so that moving it behind `ai_service` later is a change of implementation rather than a change of workflow. Worth agreeing now, because it costs nothing now and is expensive to retrofit.

**3.3 Does a derived concept arrive with a `skos:broader`?** TCAP needs a concept to have some effective type — its own `vad:` type, or one inherited through `skos:broader`. Measured: **691 thesaurus concepts have no `vad:` type of their own**, so most are reachable only through a broader link. A newly minted concept with neither can be derived and curated but never tagged. You noted the agent can locate broader candidates but does not propose them. If it does not, the derivation step should mark such a concept **"not taggable yet"** so the gap is visible rather than discovered two steps later.

---

## 4. Curation screens and history

Include / exclude per item is a much smaller surface than an editor, and it fits what is already there: a checkbox grid whose ticks post a closed set, like the template builder. The important property is that **exclusion is a decision about the proposal, not an edit of the record** — so the proposal survives the curation, which is what E asks for.

**Where the proposal lives.** `evidence/` is the intended home — the existing #15 writes consumed tags there, and its docstring calls it "QA git, never pushed to SOT". That gives history in git without shipping working notes to the SOT.

**Except that exclusion is not implemented — see §7.1.** It has to be fixed before we lean on it.

### Open questions

**4.1 Granularity of the proposal record.** One file per agent run (per session, per document, per work)? Naming it is the whole of the retrieval story later, and it decides whether "the history of this document's derivations" is a directory listing or a search.

**4.2 What the curator's exclusion leaves behind.** When a concept is dropped, is it recorded as *rejected* (so a later run does not re-propose it, and so the record shows the curator considered it), or simply absent from the output? Recording rejections is more useful and slightly more work, and it is the kind of thing that is painful to add retroactively because the past is already gone.

---

## 5. Queue status as a first-class surface

Requirement A raises the stakes: this is no longer a badge, it is the thing that makes a multi-workflow dashboard usable. The machinery exists — `config/standing_queries.rson` defines rules as data, the engine subtracts dismissals, and the panel and the hub badges both render from it — so the work is the presentation and the rules, not the plumbing.

### Open questions

**5.1 Where does it live?** The hub currently shows queue badges inside the Content section header, which is the least prominent place on the page. Options worth choosing between: a permanent status strip across the top of every page; a Workflows tab of its own; or the hub's first section, above the cards. My instinct is a strip that is present everywhere, because the point is to notice a queue while you are doing something else.

**5.2 How does it relate to the Drafts count?** Drafts counts *records written and not distributed*, which is a different axis from *documents at step 3 of DTS*. Both are "work in flight", both will be on the same screen, and two numbers that both look like a queue will be confused unless the screen says which is which.

**5.3 Is a queue actionable from the status?** Clicking "4 documents ready for tagging" could take you to the tagging step with those four selected. The standing-query engine already carries a `resolving_action` per rule, which is exactly this idea, unused so far.

---

## 6. Distributing to `model/` and `vocab/`

The placement map already has both — `metacontent/model` and `metacontent/vocab` — and anything written into them converges on the next approval, so "a means to distribute to model/ and vocab/" needs no new channel. **What is missing is a way to get a file in there at all.**

The drop folder allowlists five kinds — image, model3d, video, markdown, pdf — and **`.ttl` is not among them**. A hand-authored ontology or vocabulary file therefore has no legitimate route into the sandbox, and law 12 forbids the obvious workaround: a file placed by hand has no `.ptr` sidecar and is invisible to promotion.

**Question 6.1:** should `.ttl` become a sixth drop-folder kind, with a small page that says which folder it is destined for (model or vocab) and runs the parse and SHACL gates before it is staged? That is the cheapest honest route, and the gates make it safe — an ontology file that does not parse should never reach the store.

---

## 7. Defects found while reviewing

**7.1 `evidence/` is not excluded from convergence — now a BLOCKER.** Only `operational/` is (`_is_operational` in `promotion/transports.py`). The annotate docstring's claim that evidence is "never pushed to SOT" is not implemented, so #15's evidence files have this exposure today. Since round 3 put the orphan backlog and the proposal history in `evidence/` (§9.5, §4), this must be fixed **before the first DTS run writes anything there**.

**7.2 One document entity has no legacy marker.** 57 of 58 carry `the:conceptsExtracted`; one carries neither that nor a summary. Under the "legacy means processed" rule it would re-enter the pipeline. One record, fixable by hand, but it should be fixed deliberately rather than discovered.

**7.3 The withdrawn query, recorded for the record.** It returned 0 rows against the real store for two independent reasons: `?dt` was bound inside `FILTER NOT EXISTS` and therefore out of scope for the outer filter and the `order by`; and the tag direction was reversed — 34 criticism documents tag a work, only 4 works tag a document. Both are now moot, but the direction finding survives the query: **the canonical link is entity → work**, which the prose already said.

---

## 8. Evidence from the store

| Measurement | Count |
|---|---|
| AI document entities | 58 |
| … carrying `the:conceptsExtracted` | 57 |
| … carrying neither `conceptsExtracted` nor `the:summary` | 1 |
| … carrying at least one TCAP typed property | 58 |
| `the:summary` without `the:conceptsExtracted` | 0 |
| `the:conceptsExtracted` without `the:summary` | 24 |
| Criticism documents that tag a work (entity → work) | 34 |
| Works that tag a criticism document (work → entity) | 4 |
| Criticism documents linked to no work either way | 8 |
| Criticism documents in total | 42 |
| Thesaurus concepts with no `skos:inScheme` | 52 |
| Thesaurus concepts with no `vad:` type of their own | 691 |

`the:conceptsExtracted` is not confined to AI documents — Operation (10), Concept (3), Study (2) and Article (1) carry it too, and `config/standing_queries.rson` has a live `concepts_extracted_false` rule reading it. Retiring the predicate touches all of that.

---

## 9. The concept agent as it stands

Read 2026-09-25: `PLAN_CA_v2.1.txt`, `concept_agent.py` (3,450 lines), `agent_common.py` (540 lines). Rick: assume direct integration with the dashboard; `ai_service` integration is a later phase.

### What is already right for this

The agent's own data structures are close to the contract we need. `ProposedConcept` carries label, altLabels, category, definition, broaderLabel/URI, confidence, wikipediaUrl, scopeNote, `groundingPhrase` and `grounding_verified`, plus a `status` drawn from a fixed set — `pending | accepted | duplicate | near_match | orphaned | invalid | filtered` — and only `accepted` becomes RDF. `TaggedConcept` carries uri, label, confidence, groundingPhrase and grounding_verified. `SummaryResult` carries the summary and `novel_terms` (terms it used that are not in the source). Three `*_to_dict` functions already serialise all of it as JSON, so a typed contract exists in everything but name.

**Tagging already emits `doc the:tag concept` and nothing more** — the TCAP placement is left to #15. That matches the decision in §1: the agent proposes concepts, the ontology decides the property.

The curator's include/exclude therefore sits on top of a filter the agent already performs: it narrows `accepted`, rather than choosing from raw proposals.

### What integration forces

**It must run trusted-side, and it must stop writing files.** The agent calls `api.anthropic.com` through `requests` and reads a SPARQL endpoint over HTTP; the Landlock-confined worker cannot resolve DNS at all, so none of this can live in a registry tool. It also writes its own output (queue submission, `fallback_file`, `--out-dir`), which must be turned off: everything that lands in the sandbox goes through `FileOps` or it has no `.ptr` sidecar, no audit entry, and no place in a promotion unit. The dashboard should take `result.turtle` (or better, the dataclasses) and do the writing itself.

**`requests` is not a dashboard dependency today**, and the API key needs a home. There is already a secrets convention — `~/.secrets.rson`, which Instance Control reads for its shared phrase — and that is where a key belongs rather than in `config/dashboard.rson`.

**The hardcoded model names move to config.** `agent_common.py` fixes `MODEL_SONNET = "claude-sonnet-4-6"` and `MODEL_OPUS = "claude-opus-4-6"`; the dashboard's rule is that no model name, threshold or endpoint lives in code. This is also the natural seam for `ai_service` later, so doing it at integration costs nothing and retrofitting costs a refactor. Separately, both identifiers look out of date against the current Claude model family and should be checked against the API before the first run.

**Availability is the agent's, and the UI has to show it.** `AgentCore` carries its own retry schedule (15s, 30s, 60s, four attempts) and a 30-minute cooldown after credit exhaustion, per instance. A DTS step can therefore block for roughly two minutes, or refuse instantly with "cooldown active". The step must run off the request thread, and the screen needs to say *the agent is unavailable until HH:MM* rather than showing a generic failure.

### 9.1 The thesaurus comes from the QA store, not from the running server

`DEFAULT_SPARQL_ENDPOINT = "http://localhost:8082/sparqlEndpoint"`. This is the single most consequential fact in the three files, because it explains the old workflow's shape: "Function Distribute Metadata. Then refresh DB to make concepts available for tagging." The step order was not stylistic — **the agent could not see newly derived concepts until they had been distributed and the downstream server refreshed.**

It also contradicts §1's settled position that the sandbox is always current and only downstream needs a refresh. If the agent queries downstream, the agent is the one component that is *not* looking at the current sandbox, and DTS acquires a distribute-and-refresh barrier between step 2 and step 3.

**Decided (Rick, round 3): the thesaurus comes from the QA store.** The agent's `sparql_endpoint` is replaced by an injected provider — an in-memory graph, or the `rdf.sparql` registry tool over the QA content, which is how the annotation picker already reads the vocabulary. DTS is then self-consistent inside the sandbox: a concept derived in step 2 is visible to tagging in step 3 without distributing anything or refreshing anything, and the whole of DTS can be done in one sitting. It also removes the last reason for a mid-workflow refresh, which is what made that barrier dangerous in the first place.

Two consequences worth naming. The agent's queries are written against a Jena-backed endpoint and will now run against rdflib, so anything relying on Jena-specific behaviour needs checking. And the QA vocabulary includes **undistributed** concepts, which is the point — but it means the agent can propose a duplicate of a concept that exists only as a draft, so dedup sees drafts too. That is the correct behaviour and worth stating, because it differs from every run the agent has made so far.

### 9.2 The grounding BN needs data the agent does not currently keep

The requirement is `the:grounding [ rdfs:label ...; the:phrase ...; the:match ...; the:srcEntity ... ]`, where `the:match` is either `the:unique` or a list of `[the:concept …; the:distance …]`.

The phrase and the verified flag exist. **The match list does not.** `_token_overlap` is computed against every candidate in a loop, but only the single best score is retained, and it is recorded as prose in `validation_notes` ("Near match (0.51) with X (uri) -- resolved as DISTINCT"). The `# --- MATCHES (against thesaurus)` block in `PLAN_CA_v2.1.txt`, with its per-candidate distances, **is not produced by this code at all** — it must come from an earlier version or another tool.

So the change is concrete and small, and it is a precondition for the UI: `ProposedConcept` needs a structured `matches: list[(uri, score)]`, retention changes from "best" to "every candidate above threshold", and `the:unique` becomes the empty case. Worth deciding the threshold and the cap now, since the BN is stored data and a list of forty near-misses per concept is not a UI.

**`the:srcEntity` also has to be supplied.** The agent knows `--work` and `--doc-uri`; the grounding node wants the criticism document's *entity* URI. The dashboard has it, because step 1 created it, so this is a contract addition rather than a lookup.

### 9.6 Who does what, now that the dashboard owns the agent

Round 4: "You now own the CA agent. Integrate it and divide up responsibilities as needed … I expect new functionality to be in dashboard code not CA code where functionality should be transferred from or eliminated."

That settles a set of questions at once, and it shrinks the agent considerably. What is left in it is the part only it can do.

| Concern | Where it goes | Why |
|---|---|---|
| Prompt construction and the model call | **agent** | This is the agent's actual value, and the extensive grounding commentary in the prompts is the accumulated tuning. |
| Parsing the model's reply into typed proposals | **agent** | It owns the prompt, so it owns the reply's shape. |
| Retry, backoff, availability cooldown | **agent**, for now | `AgentCore` already does it per instance. It moves behind `ai_service` later; until then the dashboard surfaces its state. |
| Reading the thesaurus | **dashboard** | Decided in 9.1 — from the QA store, not a SPARQL endpoint. |
| Dedup and near-match scoring | **dashboard** | One matcher, `concepts/matcher.py`, CE_DESIGN §6. The agent's `_token_overlap` and the Groovy composite both go. |
| Grounding verification (is the phrase in the source?) | **dashboard** | A pure string check over a document the dashboard already holds. |
| Composing the grounding blank node | **dashboard** | Rick, round 4, explicitly. |
| Building Turtle | **dashboard** | `_build_concept_graph` and `_build_tagging_graph` are writers, and writers go through `FileOps`. |
| Writing files, queue submission, `--out-dir` | **eliminated** | Everything that lands in the sandbox goes through `FileOps` or it has no sidecar, no audit entry and no place in a promotion unit. |
| The HTTP server mode | **eliminated** | Direct integration; it only exposed derivation anyway. |
| Model names, thresholds, endpoints | **dashboard config** | No hardcoded model name, threshold or endpoint in code. |
| TCAP placement | **dashboard**, already built | The agent proposes concepts; the ontology decides the property. |

**Worth noticing: what is left of the agent is almost exactly what `ai_service` will be** — prompt, call, parse, retry. Stripping it now is not throwaway work; it is the same seam, pulled a phase early.

**One caution.** The commentary blocks in `_build_concept_graph` are not only decoration — the orphan epilogue, the per-concept status markers and the metrics summary are the curator's current record of what happened. They must not simply be deleted with the Turtle builder: the orphan list has a new home (§9.5), the statuses become the review screen (§4), and the metrics belong on the review stop. Each has somewhere to go, but each has to be *taken* somewhere.

### 9.3 Open questions on the agent

**9.3.1 Where does the tag grounding get written?** The Entity example puts one `the:grounding` node per tagged concept on the entity, beside the TCAP-placed properties. The agent proposes the concepts and #15 places them, so which side writes the grounding node — and what guarantees the two agree about which concepts survived curation? The simplest answer is that placement and grounding are written together, from the curated list, in one tool call.

**9.3.2 Can the curator rescue a concept, or only drop one?** *Answered for orphans (round 3): no — broader terms are a separate modeling task, and the orphan list feeds it (§9.5).* Still open for `near_match`: when the agent resolves a near match as MERGE or DUPLICATE, the proposed label is discarded. Should the screen let a curator disagree with that resolution, or is the agent's call final?

**9.3.3 Schemes are assigned after all.** `SCHEME_CONFIG[category]` writes `skos:inScheme` from the agent's own category — formal, contextual or production — so a derived concept does land in a scheme (`the:digitalArtTerms` in the example). That softens §1's "schemes are not needed for DTS": they are assigned automatically and the separate curatorial tool is for *correcting* them. Worth confirming which schemes this deployment wants and whether the dashboard passes `--schemes`.

**9.3.4 Does derivation still submit to a queue?** `queue_id` and `--concept-queue-url` suggest the agent posts results somewhere. Under dashboard integration that path is replaced by the review stop, and it should be switched off rather than left dangling.

### 9.4 The matching, found — and it is not the matcher the dashboard has

`support/util/LoadConceptMatch.groovy` is where the `# --- MATCHES` block comes from, and `LoadConceptQueue.callbackMatch` is what prints it. It is a **composite ranked matcher**: four strategies, each contributing a confidence, keeping the highest per candidate, sorted descending.

| strategy | condition | score |
|---|---|---|
| exact | `rdfs:label` equal | 1.0 |
| normalized | equal after lowercase + strip non-alphanumerics | 0.9 |
| fuzzy | Levenshtein similarity ≥ 0.55 | similarity × 0.8 |
| token | Jaccard overlap of >2-char tokens ≥ 0.7 | 0.8 |

Empty result prints "*X* is unique" — which is exactly the `the:match the:unique` in the plan's BN.

**The score is not a similarity, and storing it as `the:distance` alone would mislead whoever reads it later.** `0.50526315792` in the plan is a Levenshtein similarity of 0.63 scaled by 0.8 because it came from the fuzzy branch; an 0.8 from the token branch is a flat constant, not a measurement. **Decided (Rick, round 3): the BN keeps the match type.** `the:match [ the:concept … ; the:distance … ; the:matchType "fuzzy" ]` costs one triple and is the difference between "these two strings are nearly identical" and "these two share most of their words", which is precisely the distinction a curator is being asked to make.

**There are now three matchers in play, and that is the real problem.** The dashboard already has one, `concepts/matcher.py`, whose docstring says it is "the single shared matcher" so that "calibration never drifts" — `max(rapidfuzz.ratio, token_sort_ratio)` after normalization, threshold **0.9**, used by concept dedup, the annotation-time remedy and updateWorkOnSite title matching. The Python agent has a third, a plain Jaccard `_token_overlap` against its own `NEAR_MATCH_THRESHOLD`.

**The reconciliation is a single observation: dedup and display are different questions with different thresholds.** The Groovy threshold was lowered from 0.85 to 0.55 (the old value is still in the source, commented out), and every match in the plan's example scores between 0.45 and 0.51 — all of them far below the dashboard's 0.9. Those are not duplicate candidates; they are *neighbourhood*, shown so a curator can see what the new concept sits near. So:

- **dedup** keeps the dashboard's matcher at its configured threshold (0.9) and keeps its one answer — "is this the same concept as one we have";
- **grounding display** uses the same scoring function at a much lower threshold, capped, to answer "what else is nearby".

That gives one calibration rather than three, keeps the Groovy's tiering as the `matchType`, and the numbers a curator sees stay comparable with the numbers the dedup decision was made on. The cost is that they will not be the same numbers the Groovy printed, because `rapidfuzz.ratio` and `similarity × 0.8` are different scales.

**The Groovy's label asymmetry is not reproduced.** Its source side queries `rdfs:label UNION skos:prefLabel` while its candidate side (`findMatchingConcepts`) queries `rdfs:label` only, so a concept named in `skos:prefLabel` or `skos:altLabel` can never be matched *against*. **Decided (Rick, round 3): follow CE_DESIGN §6** — the label set is `prefLabel ∪ altLabel ∪ rdfs:label`, symmetrically, which is what the dashboard's matcher is already built for. Expect this to find matches the Groovy never could, which is the point, and to change the counts on a re-run of old material.

### 9.5 Orphaned concepts are a modeling backlog, so they need a durable home

Decided: supplying broader terms is a separate thesaurus-modeling task, and the orphan information must be kept to inform it.

Today it is printed in a Turtle comment and lost when the file is discarded — which is exactly the loss the old workflow's `conceptQueue/processed` directories existed to prevent. The dashboard already has a home for this species of finding: the **hygiene ledger**, which records TCAP ties under the description "awaiting structural vocabulary repair" and is surfaced by a standing query with `severity: warn`. An orphaned concept is the same kind of thing — a vocabulary-modeling gap discovered by a workflow — and adding a ledger kind makes it visible on the queue surface (requirement A) instead of buried in a comment.

**Decided (Rick, round 3): `evidence/`, not the hygiene ledger.** The ledger lives at `.qa/hygiene_ledger.ttl`, and `.qa/` is gitignored — it survives a refresh but is not in the QA git history and would not survive rebuilding the sandbox. A backlog that accumulates over months needs history. `evidence/` is committed to QA git and excluded from convergence, so the list is versioned and never reaches the SOT.

**This promotes §7.1 from a defect to a blocker.** The exclusion of `evidence/` from convergence is *not implemented* — only `operational/` is excluded — so until that is fixed, anything written to `evidence/` ships to the SOT with the next promotion. It has to be fixed before the first orphan is written, not after.

Worth recording what an orphan entry needs to be useful to the modeling task later: the proposed label and definition, the broader term the agent *wanted* (`broaderLabel`, which it already produces), the source entity, the grounding phrase, and the date. That is enough to reconstruct the case for adding a term without going back to the document.

## 10. Still open

**The state model closed in round 4.** What remains is smaller, and none of it blocks starting.

### The state model is closed

Rounds 4–6 settled all of it: seven queue states, six stamps in one status node, rules keyed off the stamps rather than the label, provenance in the same structure, no re-runs, and a reset that goes back to entity-created.

**One rule carries the legacy population, and it is load-bearing.** Queue 1 is "an entity with no `the:derived` stamp", and 57 of the 58 existing AI document entities have no status node at all — so without an exclusion they would all appear as pending derivation. `the:conceptsExtracted` is what excludes them (§2, "processed under the pre-DTS flow"), which makes a retired predicate a working part of the first queue rule rather than a historical curiosity. Worth knowing, because it looks deletable and is not.

### The agent (§9.3)

**10.4 Can a curator overturn a `near_match` resolution?** The agent resolves MERGE/DUPLICATE and discards the proposed label. Orphans are settled; this is not.

**10.5 Which concept schemes this deployment wants.** `SCHEME_CONFIG` assigns `skos:inScheme` from the agent's category, so derived concepts land in a scheme automatically.

### Curation and history (§4)

**10.6 Granularity of the proposal record** — one file per run, per document, or per work. It decides whether "the history of this document's derivations" is a directory listing or a search.

**10.7 Is a rejected concept recorded as rejected**, or simply absent? It means a later run need not re-propose it, and it cannot be reconstructed later.

### Surfaces (§5, §6)

**10.8 Queue layout — sequenced, not open.** Rick, round 5: put all the information up prominently first, then work on UX design; the real estate is accepted. So the first cut renders all seven DTS queues plus whatever else the standing-query engine holds, and the arranging comes after there is something real to arrange.

**10.9 How queue counts relate to the Drafts count** — both are "work in flight" on one screen, on different axes. Worth settling while the surface is being designed rather than after.

**10.10 Should `.ttl` become a sixth drop-folder kind** (§6.1), so hand-authored model and vocabulary files have a legitimate route in. Without it the ontology task in §1 has no ingress.

### Must be fixed before the first run

**10.11 `evidence/` is not excluded from convergence** (§7.1). Round 3 put the orphan backlog and the proposal history there, so this is now a blocker rather than a latent defect.

**10.12 One AI document entity** carries neither `conceptsExtracted` nor a summary (§7.2) and would re-enter the pipeline under the legacy rule. One record, to be fixed deliberately.
