# OPERATIONS.md — the operator's cheat sheet

Every command and endpoint a human drives, what it touches, and whether it can
lose anything. Generated from the code on 2026-09-11; when you add a script or a
route, add it here.

**Read the blast-radius column first.** Three of these delete or overwrite, and
two reach outside this machine.

---

## Starting up

```bash
cd ~/cwva-py/dashboard && source .venv/bin/activate
uvicorn cwva_dashboard.main:create_app --factory --port 8100   # localhost only
pytest -q                                                      # expect 854 passed
```

`create_app` loads `config/dashboard.rson`. It refuses to start without
`domain` — there is no default identity (CE_DESIGN §13.4a).

---

## The two stores, and which way things flow

```
  production bucket ──seed_shadow_sot.py──▶ shadow-sot/ ──/api/refresh──▶ sandbox (QA)
      (read-only)                            (the dashboard's SOT)         ~/.local/share/…
                                                   ▲                            │
                                                   └────── Approve & distribute ┘
```

Two hops, and that is the single most common source of "my edit didn't show up":
editing production does **not** reach the dashboard, and editing the shadow does
not reach it either until a refresh.

---

## Scripts — `python scripts/<name>`

| command | what it does | blast radius |
|---|---|---|
| `verify_shadow.py` | shadow vs its frozen baseline | **read-only** |
| `verify_shadow.py --compare` | also diffs against production | **read-only** |
| `gate_baseline.py` | asset + vocabulary gates over the whole QA tree | **read-only** |
| `gate_baseline.py --verbose` | …listing every finding | **read-only** |
| `build_assistant_guide.py` | assemble `docs/ASSISTANT_GUIDE.md` from `docs/assistant/preface.md` and the About pages; `--check` exits 1 if it is out of date (a test runs that) | writes that one file |
| `split_aggregate.py --file … --dry-run` | report how a multi-subject TTL would split | **read-only** |
| `split_aggregate.py --file …` | split it into one file per subject; original to `.qa/trash`; result left uncommitted for the review stop | writes QA |
| `split_aggregate.py --file … --from <config>` | take each record from ANOTHER sandbox instead; prints the per-record diff and every statement that would be lost | writes QA |
| `sync_shadow_to_qa.py --dry-run` | report the sync plan | **read-only** |
| `sync_shadow_to_qa.py` | shadow → QA, leave uncommitted | writes QA |
| `sync_shadow_to_qa.py --adopt` | …and commit as the baseline | writes QA + commits |
| `sync_shadow_to_qa.py --config config/production.rson --adopt` | seed the PRODUCTION instance's sandbox. The source is opened read-only whichever target it is — this script can never write to a bucket | writes QA + commits |
| `seed_shadow_sot.py` | production → shadow, everything | **writes the shadow bucket** |
| `seed_shadow_sot.py ttl/,documents/` | …selected prefixes only | **writes the shadow bucket** |
| `seed_shadow_sot.py ttl/model/ --force-qa-only` | …including QA-only paths | **overwrites QA-only work** |
| `seed_shadow_sot.py --mirror --dry-run` | what a mirror would copy (new, changed) and **every object it would delete**; writes nothing. Takes a prefix filter like the others | **read-only** |
| `seed_shadow_sot.py --mirror` | make the shadow **equal** to production, `operational/` included: copy only new/changed, delete every shadow-only object. Nothing of QA's survives and `qa_only` does not apply; only paths outside a prefix filter are left. Refuses if production lists nothing or more than 25% of the shadow would go. Then rebuild the QA sandbox (LegacyToNewDashboardProcedure.md) | **deletes from the shadow bucket** |
| `dts.py status` | every AI entity and the DTS queue it sits in | **read-only** |
| `dts.py create --doc … --label … --topic … --tag …` | queue 0: ingest a criticism document from the drop folder and create its entity; definition taken from the first human turn unless `--definition` is given; result left uncommitted for the review stop | writes QA |
| `migrate_agent_iris.py --dry-run` | report the `…/agent/` -> `ops:` provenance migration and the ontology section it needs | **read-only** |
| `migrate_agent_iris.py` | apply it: add the agency section to `operations.ttl`, rewrite every agent IRI, re-serialize. Idempotent; result left uncommitted for the review stop | writes QA |
| `migrate_agent_iris.py --config … --ontology-from …` | bring `operations.ttl` over from another deployment first. Production has none and already uses the vocabulary, so it needs this | writes QA |
| `migrate_dts_vocabulary.py --dry-run` | report the DTS vocabulary migration: the eight status terms moving `the:` -> `ops:`, and the two ontology blocks that declare all sixteen | **read-only** |
| `migrate_dts_vocabulary.py` | apply it: add the workflow-state section to `operations.ttl`, the grounding block to `entity.ttl`, rewrite `the:status` and its stamps. The grounding terms stay in `the:` and are only declared. Idempotent; result left uncommitted for the review stop | writes QA |
| `migrate_status_shape.py --dry-run` | report the status-node tidy: grounding moved under `ops:status`, status labels recomputed, inline agent declarations stripped from records | **read-only** |
| `migrate_status_shape.py` | apply it, and mark `the:conceptsExtracted` `owl:deprecated` in `entity.ttl`. It never removes that predicate from a record — it stays on the 85 that have it. `--list` names every file. Idempotent; result left uncommitted for the review stop | writes QA |
| `new_incipient_provenance.py --work <guid> --dry-run` | show the DI and owner an existing work would get | **read-only** |
| `new_incipient_provenance.py --work <guid>` | write that work's incipient provenance, for a work entered before profile forms did it. Refuses a work that already has one; result left uncommitted for the review stop | writes QA |
| `backfill_dts_state.py --dry-run` | report which pre-DTS entities would be stamped complete, and which have no evidence of the old flow | **read-only** |
| `backfill_dts_state.py` | stamp them, so the queue surface shows what needs attention rather than every record that predates DTS. Skips anything mid-flight; result left uncommitted for the review stop | writes QA |
| `dts.py session` / `--new --label '…'` | show or start a DTS session — the run whose derived concepts share one vocabulary file | writes QA (`.qa/`) |
| `dts.py derive --entity <guid>` | stage 1: propose concepts; writes the proposal record and stamps `derived`, no concepts | writes QA |
| `dts.py curate-derive --entity <guid> --exclude 'A,B'` | keep/reject the proposals; writes the concepts, rewrites the evidence, stamps `derivationCurated` | writes QA |
| `dts.py tag --entity <guid>` | stage 2: propose tags; stamps `tagged`, places nothing | writes QA |
| `dts.py curate-tag --entity <guid> --exclude 'A,B'` | place the kept tags through TCAP with their grounding; stamps `taggingCurated` | writes QA |
| `dts.py summarize --entity <guid>` | stage 3: propose a summary; stamps `summarized`, not on the record | writes QA |
| `dts.py curate-summary --entity <guid> --accept` | write the summary onto the entity; stamps `summaryCurated` | writes QA |
| `backup_qa.py --status` | what would be backed up (history + attic + ledger) | **read-only** |
| `backup_qa.py` | git bundle + attic + hygiene ledger → SOT `operational/` (`qa.bundle`, `qa-attic.tar.gz`, `qa-ledger.ttl`) | writes the bucket |
| `reset_to_baseline.py --dry-run` | what a reset would change | **read-only** |
| `reset_to_baseline.py` | roll QA **and** the shadow back to the baseline | **destructive, both sides** |
| `reset_to_baseline.py --to <sha>` | …to a specific commit | **destructive, both sides** |

**Before any seed, run `verify_shadow.py --compare`.** `qa_only` is empty by
policy (CE_DESIGN §13.4c), so a seed overwrites anything the shadow holds ahead
of production — and that window is a deliberate soak that can run for a week.

---

## Endpoints — pages

| route | what it does |
|---|---|
| `GET /` | the hub (`html/function.html`, served as-is) |
| `GET/POST /rdf/entry` | RDF Entry — watercolour/drawing record |
| `GET/POST /rdf/digital` | RDF Digital — sculpture, 3D, video |
| `GET/POST /rdf/entity` | RDF Entity — entity/criticism/document |
| `GET/POST /rdf/profile/{guid}` | **the profile-driven entry form** — fields, order and rules from that artist profile's `ops:template` |
| `GET/POST /rdf/artist` | **bootstrap** — the person or persona whose work this records |
| `GET/POST /rdf/artist-profile` | **bootstrap** — a profile and the template that becomes its form |
| `GET/POST /rdf/artist/edit` | **Edit artist** — the artist record (name, contact, brand), not the works. Replaces what the form owns and preserves the rest |
| `GET/POST /rdf/artist-profile/edit` | **Edit artist profile** — label, description, measurement system and the TEMPLATE, which applies to works made from now on. The artist cannot be changed; `ops:dependsOn` survives an edit |
| `GET /rdf/resume/{guid}` | reopen the form a draft came from, repopulated — the way back from a failed gate |
| `GET /backup` | what SOT cannot give back: history + attic counts |
| `POST /backup` | run the backup now |
| `GET /edit?kind=work\|entity` | pick a record to edit — single-subject files only, one group at a time: works (typed as an art form) or entities (in the entities scheme). Artists and artist profiles have their own editors above |
| `GET /edit/open?path=…&kind=…` | the field editor for one instance file; `kind` only decides which list rides above the fields, so any single-subject file can be opened by path |
| `POST /edit/save` | rewrite that file, then stop at the review. A file picked for a work's image or any record's PDF/markdown **replaces the current file under its existing name** (old bytes to the attic); a refused save copies nothing |
| `GET /annotate` | Annotate Work (TCAP) — opens with the work's CURRENT concepts ticked. `?work=…` picks the work, `?concepts=…` overrides the ticks (the way back from the review) |
| `POST /annotate` | **replaces** the work's annotation with the selection — unticked concepts are discarded — then stops at the review |
| `GET/POST /site/update` | updateWorkOnSite — GET lists sites, POST reads them |
| `GET /sparql?query=…&format=…` | **SPARQL browser** — read-only query over the whole sandbox (records, provenance, model, vocabulary, tags; drafts included). UPDATE refused, 10 s timeout, 10,000-row cap on a SELECT without a LIMIT | **read-only** |
| `POST /check` | **Syntax Check RDF/JSON** (Files tab): is the uploaded file well formed, the parser chosen by its extension: `.ttl` Turtle, `.rdf`/`.owl`/`.xml` RDF/XML, `.nt`, `.n3`, `.trig`, `.nq`, `.jsonld` JSON-LD, `.json` plain JSON. If not, the first error with its line and the lines around it. Passed to `check.syntax` as text and **never stored** | **read-only** |
| `POST /md2html` | **Markdown to HTML** (Files tab): the uploaded markdown, rendered as a standalone page by `doc.render_markdown`, **opens in a new tab**. Nothing is saved, and it carries no instance banner | **read-only** |
| `POST /image/{op}` | **Scale Image / Convert Image** (Files tab; `op` is `scale` or `convert`): the uploaded image comes back as a download, `<name>-<w>x<h>.<ext>` or `<name>.<new ext>`, via `image.transform`. Up to 40 MB. Formats: what Pillow can write (JPG PNG TIFF WEBP GIF BMP PDF). Nothing stored | **read-only** |
| `GET /report/storage?storage_class=…` | **Storage Report** (Tools tab): DispId, title and a 50-px thumbnail for every provenance in one storage class, in DI order (year, then item). Blank class = default storage, the paper works. Reads this instance's sandbox, drafts included, so run it on the production dashboard for production. Thumbnails come from the published site's `/thumbnails/`, falling back to the full image. Printable, and without the instance banner (reports are documents, `X-Cwva-No-Banner`) | **read-only** |
| `GET /report/registry?profile=…` | **Print Registry** (Tools tab, #19): one artist profile's works by title with image, QR code, year and description, titled with the profile and "by" its artist from the data. With no profile, the profiles to choose from. Printable | **read-only** |
| `GET /certificate?guid=…` | **Generate Certificate** (Tools tab, #20): a Certificate of Authenticity for one work, the record as Property / Value with concepts by name, then lines to sign and date. Printable | **read-only** |
| `GET /about`, `GET /about/{slug}` | **About** (nav bar): the project's documentation, the Markdown files in `docs/about/` in the order `contents.rson` gives, with the hub's header and a contents list. The same files are the docs on GitHub | **read-only** |
| `GET /about/assistant-guide.md` | the one-file guide to hand an AI assistant (`docs/ASSISTANT_GUIDE.md`), as plain Markdown | **read-only** |
| `GET /instances` | **Monitoring** — Instance Control, one card per configured server |
| `GET /viewer` | **cwva-py view** — Start / Reload / Stop cwva-py over THIS instance's sandbox, drafts included, to see a change before distributing it. Confined by Landlock: it can write only its scratch folder (`viewer-<sandbox>/`, beside the sandbox), listens on 127.0.0.1 only (`viewer.port`: QA 8091, production 8093), and has no bucket, credentials or AI endpoint. Every HTML page it serves carries the instance's banner, e.g. "QA · DASHBOARD VIEW — this sandbox, drafts included; not published", added by the launcher around cwva-py's app so the published site never has it. Reload restarts it (about 20 s) | **read-only** |
| `GET /api/viewer` | the viewer's state (`stopped`/`loading`/`running`/`failed`) and the end of its log | **read-only** |
| `GET /workflows?wf=…&finished=1` | **Workflow board** — one row per work, one column per step of its workflow (A Watercolor, B Blender; `config/workflows.rson`), each step derived from the records: done with its date, under way, ready, or waiting on an earlier step. A dashed ring marks a step whose record is not yet distributed. Works entered before `track_since` are not shown; finished works only with `finished=1` | **read-only** |
| `POST /rdf/entry/approve` | the review page's **Approve & distribute** — converges |
| `POST /rdf/entry/edit` | the review page's **Edit form** — reopens the form, **keeps** the draft |
| `POST /rdf/entry/reject` | abandons the pending promotion, leaves QA as it is |
| `GET /dts` | every DTS queue and what is in it, plus documents in the drop folder with no entity | **read-only** |
| `POST /dts/entity/new` | queue 0: generate the entity a criticism document implies — label, topics, definition and the work it criticises derived from the document — then open it in Edit Record for review | writes QA |
| `GET /dts/entity?guid=…` | whatever that entity's queue calls for: runs the proposing stage (a model call, 30-60s) or shows its curation screen | writes QA |
| `POST /dts/curate/derive` | record keep / reject / demote per concept; writes the kept ones, records the rest | writes QA |
| `POST /dts/curate/tag` | place the kept tags through TCAP with their grounding | writes QA |
| `POST /dts/curate/summary` | accept the summary onto the record | writes QA |
| `GET /drafts` | **Drafts** — every record written here and not distributed, by name, with the way back into the editor that made it |
| `GET /drafts/view?guid=…` | one draft: its triples as written, and its diff against the last distributed version (compared as graphs, never as text) |
| `POST /drafts/discard` | **destructive** — the chosen drafts (or all of them) go back to their last distributed version, or away if they never had one |
| `GET /refresh` | read-only — what a refresh would destroy, then asks |
| `POST /refresh` | **destructive** — discards work in progress, pulls the SOT into QA, adopts it as the baseline, reloads the ontology and registries |
| `POST /episode/stage` | **leave it staged** — keep the record as a draft, drop the restore point and the pending token, go to Drafts. Distributes nothing, destroys nothing |
| `POST /episode/abandon` | **leave without saving** — puts the sandbox back to where this session's work started: modified records restored, records it created deleted, binaries follow their sidecars out of the attic |
| `GET /staged/preview` | **Preview Staged** — the review stop reached from the staged tree, for work no form is holding open. Read-only; converges nothing |
| `GET /wip/discard` | read-only — shows what discarding would throw away, then asks |
| `POST /wip/discard` | **destructive** — clears everything uncommitted in QA |

The three `/rdf/entry/*` actions serve **every** record form, not just Entry —
the prefix is historical. Annotation uses `Back to annotation` instead, since it
came from no record form.

Every writing form ends at the **Distribute review**: gates, preview, then
`Approve & distribute`. Nothing reaches the SOT until that click.

## Endpoints — API

| route | what it does |
|---|---|
| `GET /api/refresh` | **sync SOT→QA, adopt it, reload ontology + registries.** `?detail=1` for evidence |
| `GET /api/health` | sandbox root, Landlock state, tool list |
| `GET /api/tools` | every registry tool's schema (what the forms render from) |
| `GET /api/workflow-state` | the standing-query panel's data |
| `GET /stageStatus` | hub queue badges, same engine |
| `POST /api/tool/{name}` | dispatch one registry tool directly |
| `GET /api/affordance/file-ref?subtree=…&kind=…[&edit=1&current=…]` | what a file picker offers; with `edit=1`, what an edit form offers |
| `GET /api/affordance/vocabulary/{name}` | what a vocabulary picker offers |
| `POST /api/promotion/preview` | build a unit, run gates, **stop** |
| `POST /api/promotion/approve` | converge the reviewed change (needs the token) |
| `POST /api/promotion/reject` | drop the pending promotion |
| `GET /api/promotion/pending` | tokens awaiting a decision |
| `GET /api/episode` | read-only — the open unsaved work session, if any |
| `GET /api/wip` | read-only — what is uncommitted in QA |
| `POST /api/wip/discard` | **destructive** — same as the page, without the asking |
| `POST /api/instances/{action}` | run `status`/`refresh`/`metrics` on the servers, in parallel. `?target=…` for one |
| `POST /api/viewer/{action}` | `start`, `stop` or `reload`: start, stop or restart the cwva-py viewer. Audited; refuses a busy port, a missing cwva-py, or a system without Landlock (it never runs unconfined). Stopped automatically when the dashboard shuts down | starts/stops a local process; writes only its scratch |
| `POST /api/hub/layout` | save the order of a hub section's cards after a drag (`{"section": "content", "order": [card links]}`; `order: []` is "reset order"). Kept in `hub-layout.json` beside the audit log, shared by both instances; a card it does not name keeps its place after the named ones | writes the layout file only |
| `POST /api/workflows/mark` | tick (`done: true`) or untick a **manual** workflow step for a work (`{"workflow","step","work"}`), today only "update external website". Written to the hygiene ledger (`.qa/hygiene_ledger.ttl`) with its date; a step the data decides is refused (`not_manual`) | writes the ledger only |
| `POST /api/workflows/skip` | dismiss any step for one work as **not needed** (`{"workflow","step","work","reason"}`; `skip: false` restores it). The step stops holding the work in flight and satisfies what depends on it, but never counts as done, and data showing it done outranks it. Same ledger, kind `board-skip:<wf>:<step>` | writes the ledger only |
| `GET /api/record` | is a session being recorded, and what is in it so far | **read-only** |
| `POST /api/record/start` | begin recording this session as a replayable scenario (`{"name": …}`). Reads are dropped; writes and the promotion tail are kept | starts recording |
| `POST /api/record/stop` | finish, capture the end state, write `.qa/scenarios/<name>.rson`. A session artifact, NOT a committed fixture — copy it to `tests/scenarios/` to make it one | writes QA (`.qa/`) |
| `POST /api/inbox/open` | show the **configured** drop folder in the desktop's file manager — the path is never taken from the request |

## Entry forms come from artist profiles (CE_DESIGN §14)

The Content Management cards are **one per artist profile**, labelled with the
profile's own `rdfs:label` — `Watercolor materials profile`, not `RDF Entry`.
Behind each is `/rdf/profile/<guid>`, a form generated from that profile's
`ops:template`: which properties, in what order, which are required, and which
depend on another being filled in.

| where it comes from | what it decides |
|---|---|
| the profile's `ops:template` | the fields, their order, required/dependsOn |
| `tools/property_map.py` (code) | how each field renders and what triples it writes |
| the ontology | what the type picker offers, and every caption and hint |
| the profile's `vad:measurementSystem` | the unit — so `units` is not a field |
| the artist's `vad:brand` | *(next)* whether an arriving image is branded |

One **registry tool per profile** (`record.new.<guid>`), generated with the same
schema the form renders from — so what the form offers is what `validate_args`
enforces, per profile, and the agent can author the same records. Tools are named
by GUID because a label is the card's text and may be edited.

**A profile that cannot build a form gets a dead card saying why**, rather than
being left out: an absent card is indistinguishable from a profile nobody wrote.
`RDF Entry` / `RDF Digital` / `RDF Entity` keep their routes — nothing breaks —
but only the profile cards are offered. A deployment with **no** profiles falls
back to offering the three hand-written forms, so a fresh install is not an empty
Content tab.

Profiles are read at startup **and at every registry rebuild**, so a profile
edited in the store changes its form after a refresh, with no restart.

---

## Starting from nothing: the two bootstrap forms

Every entry form is generated from a profile's `ops:template` — which cannot
help a deployment whose first act is creating that profile. So exactly two forms
are hand-written, and they are the first two cards a new user needs:

| card | writes | notes |
|---|---|---|
| **New artist** | `vad:Painter` (or another `vad:VisualArtist` subclass) with `rdfs:label` + `foaf:name`, optional `foaf:mbox` / `foaf:homepage`, and **`vad:brand`** | The brand is the signature stamped into published images. Leaving it empty means this artist publishes unbranded — a decision, not a gap. |
| **New artist profile** | `vad:ArtistProfile` with its artist, measurement system (`schema:unitCode`) and an `ops:template` | This is the **form builder**: a tick and a position per property, which is the shape of `ops:field [ops:property … ; ops:order …]`. Everything is marked required while "all required for now" stands. |

The order matters and the dashboard says so: asking for a profile with no artist
in the store answers **409** with a link to create one, rather than rendering a
form whose artist picker is empty.

**A bootstrap record takes effect immediately.** Both forms re-read the artists
and profiles and rebuild the registry on submit, so a new artist is in the next
profile's picker and a new profile is a card you can click — without a refresh,
and while the record is still in QA awaiting its review. The review stop governs
what reaches the SOT, not what the dashboard can see in its own store.

The properties the builder offers are **derived from `tools/property_map.py`**,
so adding a property there makes it available to every new profile. Housekeeping
(`schema:identifier`, `vad:qrcode`, `vad:hasArtistProfile`) is not offered,
because it is written whatever the template says (§14.8).

---

## Getting to the drop folder

Every form that ingests files names the folder and offers two ways to reach it:

- **Copy path** — the one that always works, including from another machine or
  a headless install. A path you can paste is the whole answer.
- **Open folder** — `POST /api/inbox/open`, which shows it in the desktop's file
  manager (`explorer.exe` under WSL, with `wslpath -w` translation; `xdg-open`
  on Linux; `open` on macOS).

A browser cannot do the second itself: navigation from an http page to a
`file://` URL is blocked silently in every current browser, which is why this is
a server-side launch rather than a link.

Two constraints on it. It is a **POST**, because a GET is something a prefetch,
a back button or a link preview can fire, and this starts a process. And the
folder is the **configured** one, never a path from the request — a caller who
could name a directory could name any directory, and "open this in a file
manager" is a fine way to find out what is on a disk. It opens on whatever
machine runs the dashboard, so the answer always carries the path: when there is
nothing to launch, naming the folder is the point anyway. Audited as
`inbox.open`.

---

## What the QA trash is, and when it goes

Nothing an agent or a form does hard-deletes content you typed. A draft
abandoned at the review stop, an image replaced during an edit, a record
superseded — all move to `.qa/trash` inside the sandbox.

**Trashed files are never distributed.** `/.qa/` is in the QA repo's
`.gitignore` and the promotion manifest is derived from git, so they are
invisible to a promotion whether or not you have discarded work in progress.
(Checked 2026-09-17, against a store holding 82 of them.)

**They are pruned after a successful convergence**, dropping anything older than
`sandbox.trash_keep_days` (default 30, `0` keeps everything). Convergence is the
window's end because it is the moment the work a draft belonged to is
definitively somewhere else. A preview, a rejection or a failed promotion prunes
nothing, and `.qa/attic` — the rollback reserve — is never touched. The prune is
recorded in the audit log as `qa.trash_pruned` and never fails a promotion that
has already published.

---

## Branding images (inventory #7)

There is **no Brand Image page**. The stamp is applied on the **ingest path**, so
both writers get it: `RDF Entry` and `Edit Record` each carry one control,
**Brand arriving images**, offering the signatures derived from `sites` in
`config/dashboard.rson` (`https://visualartsdna.org` → `visualartsdna.org`). The tool
is `image.brand`, and its `enum` is that same derived list — what the form offers
is what the tool accepts.

| property | why |
|---|---|
| Sits under the image field | The decision belongs beside the field that makes it live. At the foot of the form it read as configuration and was missed. |
| Blank by default | Branding is **destructive and not idempotent**: a second stamp lands on the first — invisible when the fonts match, a smear when they don't. Rick's images already arrive branded from the legacy Groovy server, so a default of ON would double-stamp his current workflow. |
| Only files the save **copied in** | An image already in the store belongs to a record published with whatever it carries. |
| Only images | Markdown and PDF fields carry no signature, so the control is not offered for them. |
| Reported at the review | Each image the save copied in is listed under *Applied on entry* — **branded, with which signature, or `not branded`**. An unstamped arrival is a fact the reviewer needs, so it is stated rather than left silent. A failure reads `NOT branded — …` and never costs you the record. |
| The drop folder is untouched | The stamp lands on the sandbox copy (law 12), so re-running an entry still starts from a clean original. The overwritten original goes to the attic. |

Geometry is the Groovy's (`support/ImageMgt2`), because it has to match 1,600
published images: text at (0.9w, 0.98h) with **0.98h as the baseline**, size
`clamp(max(h,w)/1028*8, 10, 35)`, light gray on a dark corner and dark gray on a
light one, decided by sampling that corner. Arial where it exists — including
`/mnt/c/Windows/Fonts` from WSL — then Liberation Sans, then DejaVu. **No
usable font is an error**, not a fallback: Pillow's built-in bitmap font does not
scale and would burn an illegible speck into a published image.

---

## Instance Control — the running servers

`GET /instances` is the Monitoring tab's Instance Control card. The servers it
talks to are config (`instances.targets` in `config/dashboard.rson`), never
code; each has a `name`, a `tag` and a `url`.

| action | cwvaServer-py (`api: py`) | Groovy/Jetty (`api: groovy`) | effect |
|---|---|---|---|
| Status | `GET /status/os?token=…` | `GET /cmd?token=…&cmd=stats` | read-only — uptime, memory, disk |
| Refresh | `GET /cmd?token=…&cmd=refresh` | same | **the server rereads its RDF store** |
| Metrics | `GET /metrics?token=…` | same | read-only — request counters |

**The two server generations disagree about Status**, and both are in service:
the Python `/cmd` accepts only `refresh` and `cestfini`, while the Groovy server
has no `/status/os`. The flavour is **declared** per target (`api`), not sniffed,
because the Groovy answers a route it does not have with an empty 200 — a wrong
guess would read as a healthy server. An empty 200 is reported as such rather
than as success; that server answers the same way for a rejected token, so the
console is the place to tell those apart.

**A target's `url` may name the host symbolically.** `wsl-host` (or
`host.wsl.internal`) resolves to the Windows host at call time, for a dashboard
running in WSL2 against a server on the PC: `localhost` inside the VM is the VM,
so the request never leaves it — connection refused, and nothing in the server's
log because nothing arrived. The address is WSL's default gateway, which changes
when WSL restarts, so it is resolved per call and never frozen into config. The
page shows the configured host and the resolved one. Off WSL this raises rather
than dialling the machine's real gateway, which would be the router.

Three things about it are deliberate:

- **Fired together, reported apart.** `POST /api/instances/{action}` with no
  `target` runs every server at once (`instances.call_all`, a thread per target)
  and returns one result object each — `ok`, HTTP status, elapsed ms, body or
  error. A refresh is a full store reload, so serial updates meant waiting
  through them one after another; and one unreachable server must not hide the
  others' answers.
- **A target is named, never given.** `?target=` is matched against the
  configured names. A URL there is a 404, not a fetch: the token authenticates
  against whatever host it reaches, so a caller who could name a URL could
  spend the user's credential on it.
- **There is no stop.** The server's `cestfini` shutdown command has no route,
  no action and no client function here. `POST /api/instances/cestfini` is a
  404 like any other unknown action. Charts are likewise absent — not hidden.

**Each card shows its last refresh and how old it is.** No server reports this, so the dashboard keeps it: `instance-refreshes.json`, beside the audit logs and shared by the QA and production dashboards, since both refresh the same servers. Only a successful refresh updates it. It knows only about refreshes fired from a dashboard on this machine, so a server restart or `refresh.s` reloads the store without changing the time shown. The Groovy server answers a completed refresh and a rejected token with the same empty 200, so its time is marked unconfirmed. Losing the file loses nothing but this display.

**A drifted clock looks exactly like a bad secret.** The token *is* a timestamp,
accepted within ±30 s, so a server whose clock has wandered refuses a perfectly
good credential — and refuses it *intermittently* as the skew crosses the line.
Every response carries the server's clock in its `Date` header, so each result
reports the skew and says so above about 20 s. Measured 2026-09-13: the PC ran
29 s behind, right on the boundary. The fix is on that machine (`w32tm /resync`
as administrator on Windows), never in the dashboard.

**Getting there: the hub's `Monitoring` nav item IS this page.** There used to be
two — a static Monitoring tab whose cards only linked here, still advertising
Stop, Charts and `localhost:8080` — and two descriptions of one thing drift. The
tab is deleted; `Metrics & Reports` went with it at Rick's word. Nothing runs on
arrival: a GET that reloaded a server's RDF store would also fire on a browser
prefetch or a back button.

Authentication is the cwvaServer token scheme, ported from
`~/cwva-py/main/tools/cwva_cmd.py` rather than imported, since the dashboard and
the server need not be coresident: `milliseconds * javaHashCode(phrase)`, which
the server divides back out and accepts within ±30 s. The phrase comes from
`instances.secrets_path` (default `~/.secrets.rson`) and is read fresh per call.
**The token is never audited** — the `instance.command` record carries the
action, the target and the elapsed time only.

Note that the server does **not** validate the token on `/metrics`; it is marked
internal there. The dashboard sends one anyway.

---

`/api/refresh` is a **coarse reset**: it discards work in progress, pulls SOT,
and adopts the result as the QA baseline. Uncommitted QA work is lost. That is
its job (CE_DESIGN §4), not a side effect.

---

## The things that bite

- **A promotion unit sweeps up everything uncommitted** (law 4). Check the
  `manifest {...}` line on the review page: an annotation should read
  `modifies: 1`. A large number means something else is riding along.
- **Content enters through the drop folder**, `~/cwva-py/stage/data` — never by
  copying into the sandbox. A hand-placed *binary* has no `.ptr` sidecar and is
  invisible to promotion; a hand-placed *TTL* is fine (it is git content).
- **Filenames are normalised on entry** — spaces collapsed, extension
  lowercased — because the name becomes part of the IRI. Collisions are checked
  case-insensitively, after normalising.
- **Editing production does not reach the dashboard.** Two hops, always.
- **The QA history, `.qa/attic` and the hygiene ledger are the only things SOT
  cannot restore.** Content and `.ptr` sidecars come back from a sync; the
  commit history that law 6 rollback depends on, the superseded binaries in the
  attic, and the ledger's dismissals and workflow-board ticks (each with its
  date) exist on this disk alone. To restore the ledger, copy
  `operational/qa-ledger.ttl` back to `.qa/hygiene_ledger.ttl`. `backup_qa.py` (or the QA Backup card) puts them in the
  target's `operational/` prefix — which is **excluded from sync and from the
  drift stamp**, so it never returns as content and never looks like someone
  else changed SOT. **A successful promotion backs up automatically**; the
  script and the card are for running it on demand. A failed backup never fails
  the promotion — the content is already published — but it is reported on the
  page that follows. Watch the attic count: zero means history is the only
  exposure.
- **The record editor rewrites one file whole.** That is safe because it renders
  every predicate in the file — but an empty field *removes* the statement, and
  clearing an image reference leaves the image in the SOT, unreferenced.
  Aggregates (`workonsite_*.ttl`, `conceptQueue.ttl`) are not editable: they
  describe many records, so there is no single instance to edit. `rdf:type` is
  read-only, and **every save stamps `schema:dateModified`**, accumulating — so
  a save is always a change, even when no field was touched. File fields
  (image, 3D object, markdown, PDF) offer **the drop folder only** — never what
  is already stored, since that belongs to some record — and saving copies the
  chosen file in. The video file cannot be repointed: it sits inside a blank
  node beside a thumbnail and a title computed from it.
- **An image absent from QA fails the asset gate.** Since the 2026-09-11 seed
  the shadow carries all 1093 production images, so this should no longer bite.
