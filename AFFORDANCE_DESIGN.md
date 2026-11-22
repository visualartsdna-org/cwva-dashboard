# AFFORDANCE DESIGN — schema-first form affordances (Phase 4.6 §3)

**Status: design for review. No code yet.** Per the extraction-doc convention,
this is reviewed before the renderer/validator work it describes. Companion to
`PROJECT_PLAN.md` Phase 4.6 → "The affordance layer".

Term of art: **affordance layer** — never "semantic layer" (that means RDF here).

## The failure this fixes

Every registry tool schema types its fields as `string` (plus a few `number`s);
closed sets survive only as prose in `description`. The generic renderer emits a
text box per field, so the Groovy form's affordances (`type` radios,
`hasPaper`/`units` selects, site choice, file chooser) are gone. They were lost
at the **schema** layer during the port, not the UX layer — so the fix is in the
schema, and the generic renderer is upgraded to honour it. Bespoke UI only where
a schema cannot express the affordance (concept picker; §7).

## The one principle: render ≠ enforce, and enforcement has two loci

An affordance has two independent jobs, and conflating them is the bug:

1. **Render** — help the human produce a well-formed value (a `<select>`, a
   file picker). Client-side, advisory, and **binds only the human**.
2. **Enforce** — reject a bad value regardless of who sent it. This is what
   binds the **second driver** (the Phase 5 agent on the same tools).

The rendered `<select>` is *never* the enforcement. A field whose only
constraint is its `<select>` is exactly the hole: the agent sends
`units:"metre"` and nothing stops it. Every affordance below therefore names its
**enforcement locus**, and there are only two:

- **Dispatch** (`validate_args`, Phase-2 deny-by-default) — enforces what is
  knowable **from the argument alone**: shape, type, a *fixed or materialized*
  closed set, a stateless format. Cheap, synchronous, store-free.
- **Gate** (`run_promotion`, SHACL/SPARQL) — enforces what is knowable only
  **relative to the store**: dynamic-vocabulary membership, asset/reference
  existence. The confined worker must not enumerate the store to validate an
  argument, so store-relative validity is a promotion-time concern, not a
  dispatch-time one.

**This split is the whole point.** A constraint that is dispatch-enforceable
goes to dispatch (binds both drivers immediately, no store). A constraint that
is inherently store-relative goes to the gate (binds both drivers at the single
gated exit). Neither relies on the renderer. The design's job is to put each
field in the right locus and to say plainly which enforcement **does not exist
yet**.

## Enforcement-locus table (the load-bearing artifact)

| Affordance | Fields (examples) | Rendered as | **Enforced at** | Enforcing code | Exists today? |
|---|---|---|---|---|---|
| Static `enum` | `units`, `type`, `file_format` | `<select>` / radios | **Dispatch** | `validate_args` enum check | **NO — must add** |
| Config `enum` | `work_on_site` (from `sites`) | `<select>` | **Dispatch** | same enum check; set materialized at registry-build | **NO — must add** |
| `format: date` | `recorded_date`, `completed_date` | date input | **Dispatch** | `validate_args` format check | **NO — must add** |
| `x-vocabulary` (dynamic) | `has_paper`, `background`, `tags` | picker (store-resolved) | **Gate** | SHACL referential-integrity shape | **NO — must add (shape)** |
| `x-file-ref` | `image`, `image3d`, `images`, `qrcode` | picker over `fs.list` | **Gate** | asset referential-integrity (schema:image → file present) | **NO — must add** |
| URL `format` | `wikipedia`, `dbpedia` | url input | **Dispatch** | `validate_args` format check (well-formedness only) | **NO — must add** |
| Config default | `has_artist_profile` | prefilled | Dispatch (default applied) + Gate (validity) | default mechanism exists; validity is `x-vocabulary` | default: **yes**; validity: no |

Three things this table makes explicit:

- **`enum` is not enforced today.** `validate_args` checks
  `additionalProperties`/`required`/`type` and **ignores `enum`/`format`**. So
  authoring an enum without extending the validator gives a `<select>` that the
  agent bypasses. Extending `validate_args` is the first code task, and it is a
  security change (it is the deny-by-default surface), so it lands with its own
  adversarial tests.
- **Dynamic vocabulary is a Gate concern, not Dispatch.** `has_paper`'s valid
  set is the current thesaurus, which changes with content. `validate_args` is
  pure and store-free by design; teaching it to query the QA graph would couple
  the security-critical validator to the RDF store and answer a *referential*
  question in an *argument-shape* place. So membership is enforced by the SHACL
  ref-integrity shape at promotion — which is exactly why the affordance enums
  and that shape are **two halves of one guarantee** (see §4).
- **File references are Gate, not Dispatch.** "The file exists" is checkable at
  dispatch only if the validator holds `fileops` (it does not, and should not).
  More decisively: the shadow carries **no images by decision**, so a dispatch-
  time existence check would reject legitimate real-content entries. Asset
  presence is verified at the gate, when the unit is actually promoted.

## Mechanisms in detail

### 1. `enum` — static and config-sourced (Dispatch)

Static sets are literals in the schema (`units`, `file_format`); several were
already spelled out in `description` and only needed to become machine-readable.
Config sets are built at `build_default_registry(…)` time. Once materialized, a
config enum is indistinguishable from a static one at dispatch. **Both enforced
by one check in `validate_args`.**

**Model-sourced sets are the same pattern, one step further (Q9, `type`).**
`type`'s valid set is not the code's business but the ontology's — so it is
resolved from the ontology model at registry-build time as the RDFS subclass
closure of a per-form `type_root` (`build_record_tools(domain, model=…,
entry_forms=…)`), materialized into the schema enum, and dispatch-enforced like
any other. The per-form root lives at dispatch (each tool built with its own
root) precisely because the promotion gate cannot tell a painting record from a
digital one — both are `a vad:X`. Adding a work kind is then an ontology edit
(data, promoted through the gated exit) + a registry rebuild, zero record-tool
code. This is the correct home for the externalization instinct: the tier that
IS vocabulary (`type`) goes to the model; genuine constants (`units`) stay
literals; and `file_format` — which has NO ontology backing — stays a literal
set too, not externalized for uniformity's sake.

### 2. `x-vocabulary` — dynamic, store-resolved (render trusted-side; enforce at Gate)

A schema annotation naming a vocabulary source (a `.sparql` file / standing-query
id), e.g. `"x-vocabulary": "papers"`. **Rendering:** the trusted side (panel
endpoint / renderer) resolves candidates via the existing **read-only SPARQL
path** over the QA store and hands them to the picker. Note this is a *different
entry point* from `workflow.state`, which runs SPARQL in the **worker** over
sandbox content — the affordance resolution is render-time and trusted-side, so
it does not touch the confined surface. **Enforcement:** membership is asserted
at the gate; the annotation is a render hint, never the guard.

> **⚠ DEFERRED — vocabulary-half enforcement is NOT built yet, pending one
> decision (2026-07-29 findings against real shadow data).** Building the
> asset-reference gate (§3, done) turned up two facts that make the design's
> earlier "one SHACL shape for both" wrong:
>
> 1. **`vad:background` is NOT a thesaurus reference — it points at `work:`
>    URIs** (verified: 9 distinct values, all `work:<guid>`). It is a work-to-
>    work cross-reference, so its referential integrity is "the referenced work
>    exists," checked against the *works* graph — a different (heavier) reference
>    set than the thesaurus. Reclassify: `background` is not `x-vocabulary`.
> 2. **`vad:hasPaper` IS a real thesaurus reference** (values like
>    `the:FabrianoArtisticoGranaFinaColdPress`, declared in
>    `vocab/watercolorPaper.ttl`, which the shadow carries) — so it is
>    checkable and NOT an expected-dangler class. But the check needs the vocab
>    graph, which is **not in a work-entry's promotion manifest**. The gate
>    currently loads only manifest files.
>
> **The decision needed before arming:** where does the reference graph come
> from, and how much of it? Options — (a) load the vocab dirs (`ttl/vocab`,
> `ttl/tags`) from the QA tree at gate time (cheap, ~0.4 MB, covers `hasPaper`);
> (b) also load the works graph for `background` (heavier, ~327 records); (c) a
> SPARQL assertion vs. a SHACL `sh:class` shape — the project already has a
> SPARQL-assertions gate, and "object is a declared concept" is a clean SELECT.
> This is the arming moment the never-armed lesson is about, so it gets decided,
> not guessed. Vocabulary-half pickers (`x-vocabulary`) do not ship until it is
> armed (governing rule).

### 3. `x-file-ref` — sandbox asset picker (render over `fs.list`; enforce at Gate)

A schema annotation naming a sandbox subtree, e.g.
`"x-file-ref": "content/images"`. **Rendering:** a picker over `fs.list` on that
subtree (`fs.list` takes a sandbox-relative `path`, default `.`). **Enforcement:**
asset referential integrity at the gate, for the shadow-has-no-images reason
above.

> **The shape asserts the reference *resolves*, not that a file exists at the
> path.** For a pointer-managed image (every `.jpg`/`.glb` under the inverted
> policy) the tracked artifact is the `.ptr` sidecar, and the real bytes live in
> the attic or as the real file depending on where in the promotion lifecycle
> the check runs. A naive `os.path.exists(images/x.jpg)` passes a fixture test
> (real file present) and fails on real pointer-managed content (only the
> sidecar is tracked) — the exact fixture-vs-real seam this week keeps producing.
> Definition: the reference `{img_base}<name>` resolves iff `<name>` is a known
> managed asset in the target — a real file **or** a sidecar (`<name>.ptr`)
> whose bytes are recoverable (attic or file). This is the intersection of this
> shape with the binary-policy work; the shape is written against the pointer
> layer's notion of "present", not the filesystem's.

Covers `image`,
`image3d`, `images`, and **`qrcode`** — a QR-code *JPEG* that lives with the
images and is pointer-managed like any other image (the fragment had this right;
an earlier draft of this doc wrongly reclassified it as a URL). `wikipedia` and
`dbpedia` are genuine URLs and get URL `format`, dispatch-enforced for
well-formedness only.

> **Candidate bug for the record-group Groovy extraction (do not fix here) —
> now grounded in the shadow data (2026-07-29).**
> `record_tools` writes `image` as `SCHEMA.image, URIRef(img_base + image)` and
> `image3d` as `VAD.image3d, URIRef(img_base + image3d)`, but `qrcode` as
> `VAD.qrcode, URIRef(qrcode)` — **the raw value, no base join**. `qrcode` is the
> lone image-family field missing the join (`img_base = domain + "/images/"`).
>
> **What the real data says:** all 202 `vad:qrcode` triples in the shadow's 327
> `ttl/data` records are well-formed absolute URIs
> (`http://visualartsdna.org/images/qrc_<guid>.jpg`), the same shape as
> `schema:image`. So the Groovy generator joined the base correctly and **there
> is no legacy qrcode dangler in the data** — the defect is entirely in the *new*
> tool, which produces `URIRef("qrc_xxx.jpg")` (non-resolving) the moment it is
> driven with a bare filename, exactly what the `x-file-ref` picker will supply.
>
> **Consequence for build order:** the qrcode base-join must be fixed *before*
> the qrcode picker ships, or new dashboard records get malformed URIs where
> old ones were fine. This is the same "transition into the mechanism is where
> state goes weird" lesson, pointed at a new-vs-old-data seam rather than a
> retroactive-migration one. The `.jpg` file itself is already pointer-managed
> by the inverted policy, so storage needs nothing — only the reference is wrong.
> Classify load-bearing vs. bug in the extraction doc and correct under that gate.

### 4. Referential-integrity SHACL shape — the enforcement half for §2/§3

**Confirmed 4.6 scope by investigation (2026-07-24): no SHACL shapes exist.**
`shacl_gate` is wired but never armed (`run_promotion(shapes=None)`, nothing ever
passes a graph); `record_tools` writes `vad:hasPaper` unvalidated; a misspelled
`the:StrathmoreColdPres` yields valid TTL that clears the only live gate (parse).
The Groovy dropdowns were the *sole* dangling-reference guard. So:

- The affordance enums block bad values at **dispatch** for static/config sets.
- The SHACL shape catches store-relative danglers (`vad:hasPaper`,
  `vad:background`, and the asset refs) at the **gate**.

They are built and reviewed together. Arming `shacl_gate` in `run_promotion`
with this shape is the same task as the `x-vocabulary`/`x-file-ref` enforcement
column above — those annotations have no enforcement without it.

## Field inventory (in-scope record tools + annotate)

Grounded in the live schemas; `?` marks a closed set whose membership needs the
Groovy semantics extraction to pin (do not invent the set here — that is what
the extraction doc is for).

| Tool | Field | Affordance | Locus |
|---|---|---|---|
| new_work / new_digital / new_entity | `type` | `enum` (vad: work classes) `?` | Dispatch |
| new_work / new_digital | `units` | `enum` cm\|inch\|meter\|pixel | Dispatch |
| new_digital | `file_format` | `enum` `?` | Dispatch |
| new_work | `has_paper` | `x-vocabulary` (thesaurus papers) | Gate |
| new_digital | `background` | `x-vocabulary` | Gate |
| new_entity | `media`, `tags` | `enum`/`x-vocabulary` `?` | Dispatch/Gate |
| all | `recorded_date`, `completed_date` | `format: date` | Dispatch |
| all | `has_artist_profile` | config default + `x-vocabulary` validity | Dispatch/Gate |
| new_work/new_digital/new_entity | `image`,`image3d`,`images`,`qrcode` | `x-file-ref` | Gate |
| any | `wikipedia`,`dbpedia` | URL `format` | Dispatch |
| new_work | `work_on_site` | config `enum` (from `sites`) | Dispatch |
| annotate_work | `concepts` | concept picker (§7) | Gate |

## The concept-picker exception (§7)

`concept.annotate_work.concepts` is the known case a schema cannot express: it is
a multi-select over a large, dynamic, hierarchical vocabulary with inline
merge/demote. It gets bespoke UI, but its **enforcement is still the gate** (TCAP
+ ref-integrity), so it obeys the same render≠enforce rule — the bespoke widget
is a renderer, not a guard.

## Build order (approved 2026-07-29)

**Governing rule — no dynamic-affordance form ships before its shape is armed.**
A field whose enforcement locus is the **Gate** (`x-vocabulary`, `x-file-ref`)
must not have its picker rendered to a user until the SHACL shape that enforces
it is armed in `run_promotion`. Otherwise the picker suggests the constraint is
enforced while nothing at the gate checks it — the render-≠-enforce hole, now in
its dynamic form. Dispatch-locus fields (`enum`, `format`) are bound the moment
`validate_args` is extended, so their `<select>`s may ship with step 1.

0. **[DONE — `5c53012` extraction, `9257e26` applied]** Record-group Groovy
   extraction (`EXTRACTION_record_group.md`), Rick-reviewed. Pinned the closed
   sets, and its decisions landed: **qrcode is a derived field, NOT `x-file-ref`**
   (removed from input); image required; workOnSite not written; documents-base
   join; vocabulary gate tightened to `vad:WatercolorPaper`.
1. **[DONE — `84a0c99`]** Extend `validate_args` for `enum` + `format` (Dispatch
   locus), with adversarial tests — it is the deny-by-default surface. Unblocks
   all dispatch-locus affordances.
2. Referential integrity at the Gate — split into two mechanisms, since asset
   presence is a filesystem fact and vocabulary membership is a graph fact:
   - **[DONE — `c0265b4`] 2a. Asset-reference gate** (`x-file-ref` enforcement):
     `schema:image`/`vad:image3d`/`vad:qrcode` resolve to a managed asset
     (file **or** sidecar — the pointer layer's "present", not the filesystem's),
     armed in `run_promotion`, malformed/absent discriminated. `x-file-ref`
     pickers may now ship (their guard is armed).
   - **[DONE — `31a44e8`] 2b. Vocabulary-reference gate** (`x-vocabulary` /
     `hasPaper`): decision was (a)+(c) — load the vocab dirs from the QA tree and
     enforce via a SPARQL-style SELECT of violations (reusing the graph idiom,
     no SHACL shape introduced), armed in `run_promotion` via `vocab_dirs`. The
     reference-graph load is load-bearing (manifest alone false-dangles every
     ref) and tested as such. `background` reclassified out (work-ref, its
     integrity is a deferred work-cross-reference check). `x-vocabulary` pickers
     for `hasPaper` may now ship (guard armed); `tags` still pending the Groovy
     extraction that pins whether it is `x-vocabulary` or an `enum`.
3. **Fix the `qrcode` base-join in `record_tools` (record-group extraction).**
   Must precede any `qrcode` `x-file-ref` picker — a bare-filename picker on the
   unfixed tool produces non-resolving URIs (§3 candidate-bug note). Same gate as
   the other `?`-set resolutions from the Groovy extraction.
4. **[DONE — `9257e26`, this step]** Author `enum`s and annotations on the record
   schemas. Split by real-data evidence: **strict `enum`** (units, entity type,
   `format: date`) where truly closed; **`x-enum-suggested`** (render hint, not
   enforced) where real data exceeds the form set (work/digital type + casing
   fork, file_format + HTML — EXTRACTION F1/F2, Q6/Q7). `x-vocabulary`/
   `x-file-ref` annotations added; `the:topic`/TopicScheme added to the
   vocabulary gate (requirements generalized to (pred,obj) lists). qrcode is
   derived (not an affordance); background stays a deferred work-ref.
5. **[DONE — `a29f899`]** Upgraded the generic renderer (`dashboard.html`),
   retiring the all-text rendering — upgraded, not replaced. A single
   `widgetKind(spec)` (shared by build and collect) dispatches on declared
   affordances with **no per-field special-casing** (the old `key === 'text'`
   name branches removed): strict `enum` → closed `<select>`; `x-enum-suggested`
   → `<input>` + `<datalist>`; `format:date`/`uri` → typed inputs; `x-multiline`
   → textarea; number → number input; array → multi/csv; `x-vocabulary`/
   `x-file-ref` → async pickers from uniform endpoints
   (`/api/affordance/vocabulary/{name}`, `/api/affordance/file-ref?subtree=`),
   the vocabulary one querying exactly what the gate enforces, both degrading to
   a text input pre-sync. The zero-UX-code contract is asserted by
   `test_affordance_annotations_survive_to_the_renderer`.

**The affordance layer is complete.** Static affordances enforce at dispatch,
dynamic ones at the gate, all render from the schema alone; `type` is
ontology-backed (Q9). What remains in Phase 4.6 is execution — the §5 shadow→QA
sync (which activates the model-backed `type` enum and the vocabulary pickers),
per-function acceptance, and Scenario #1.

## Review outcome (2026-07-29 — approved)

1. **`?` closed sets** (`type`, `file_format`, `media`, `tags`) — **confirmed**
   pinned by the per-function Groovy extraction, not guessed here. The qrcode
   discovery is the proof this gate earns its cost.
2. **`x-file-ref` enforcement = Gate** — **confirmed**, with the refinement now
   folded into §3: the shape asserts the reference *resolves to a managed asset*
   (real file **or** sidecar-with-recoverable-bytes), not that a file exists at
   the path — otherwise it passes fixtures and fails on pointer-managed content.
3. **`has_artist_profile`** — **confirmed** an overridable default, not a hard
   constant (single-user CE ≠ single-artist-profile forever).
4. **Annotation naming** `x-vocabulary` / `x-file-ref` — **confirmed** (JSON-
   Schema-legal `x-` keys; `validate_args` ignores them harmlessly).

Two additions folded into build order above: the governing "no dynamic-
affordance form ships before its shape is armed" rule, and the qrcode base-join
fix sequenced before the qrcode picker. The qrcode-legacy-baseline decision is
recorded in `PROJECT_PLAN.md` Phase 4.6 §5 first-sync checkpoint.
