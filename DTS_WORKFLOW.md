# DTS — the derive / tag / summarize workflow

**Status: QA-PASSED 2026-10-01.** All four stages run end to end through the curation UX against the real QA store, and both Three Graces criticisms are complete and distributed. Rick: "Much happier with the tag results. Both summaries are fine. DTS QA is completed." The design record is `Workflows2_REVIEW.md` — settled decisions with attribution. This document is the *specification of the process*: what each stage does, what it writes, what it refuses, and where the seams are. Where the two disagree, the review is the record of what was decided and this is the record of what was built.

## What DTS is for

A criticism document arrives in the drop folder — an export of a conversation in which a critic assessed one artwork. DTS turns it into three things the catalogue can use: **new thesaurus concepts** the criticism introduced, **tags** connecting the document to concepts that already exist, and a **summary** a reader can decide from. Each of the three is proposed by a model, judged by a person, and written by a registry tool.

## The rules that shape it

**A stage cannot be left until it is curated.** Three stages with two stopping points each gives six states after the folder count, and a document sits in exactly one of them. Summarization has a curation step too — Rick reads summaries before release — though its screen is accept-or-send-back rather than include/exclude, because there is nothing to include or exclude in one paragraph.

**There are no re-runs.** DTS runs once per entity. An error is recovered by resetting the entity's DTS state back to "entity created" and starting again, which is a supported action rather than hand-edited TTL. That collapses the hardest part of the state model: one status node, stamps written once, no history to disambiguate, no "which is current".

**Distribution is implied by finishing a step, never a card someone presses.** Each stage ends with its writes uncommitted in the QA tree; the ordinary review stop gates what reaches the SOT.

**The agent proposes concepts; the ontology decides the property.** TCAP walks the model to the most specific property whose range accepts a concept and records a tie rather than guessing between equals. An agent proposing `vad:hasProcess the:FacetedSurface` directly would be asserting an answer the ontology derives, and the two could disagree silently.

**Everything that decides anything is the dashboard's.** The model reads the document and proposes; the dashboard verifies the grounding phrase, decides what is a duplicate, computes the neighbourhood, composes the grounding node, chooses the scheme, and does the writing. This is not tidiness — a model asked to verify its own evidence is not a check.

## The state model

One status node per entity, under `ops:status`, carrying six stamps and a computed label:

```turtle
work:4dd85266-… a the:AI ;
    ops:status [
        rdfs:label "derived" ;
        ops:derived [ ops:at "2026-09-30T01:36:48+00:00"^^xsd:dateTime ;
                      prov:wasAttributedTo ops:claude-opus-5-5 ] ;
    ] .
```

**The status vocabulary is `ops:`, and the grounding vocabulary is `the:`.** Both were `the:` for one sitting and neither was declared anywhere — sixteen predicates in use with no ontology behind them, which is the same defect that had just been fixed for the agents. Rick, 2026-10-01: "what was the reasoning for placing the properties in the thesaurus namespace as opposed to the operations namespace?" There was none; the shape came from the review sketch and `the:conceptsExtracted`, the flag the stamps retire, was already in `the:`. The split that came out of it is a real distinction and not a tidy-up: a **stamp is what the dashboard did to a record**, so `status`, the six stages and `at` moved to `ops:` (`migrate_dts_vocabulary.py`), while a **grounding is about a concept** — the phrase that warrants it and the labels near it — so `the:grounding`, `the:phrase`, `the:srcEntity`, `the:concept`, `the:match`, `the:unique`, `the:distance` and `the:matchType` stayed in the thesaurus and are declared in `entity.ttl` beside `the:topic` and `the:summary`.

The six stamps, in order: `derived`, `derivationCurated`, `tagged`, `taggingCurated`, `summarized`, `summaryCurated`.

**There is no `entityCreated` stamp** — the entity's existence is the evidence. An entity with no status node is therefore in queue 1, and because every triple in the node is something DTS put there, reset has a one-line definition.

**State and provenance are one structure.** Each stamp is itself a node carrying *when* and *by whom*, attributed to a `prov:SoftwareAgent` IRI declared in the operations ontology. A curation stamp names the curator **by role** — `ops:user` — and never by address, because these records converge to a published catalogue.

**The queue rules key off the stamps, never off the label.** The label is the same fact in a second place, able to disagree; a drifted one would silently empty or fill a queue. It stays because a person reading the record wants to see "tagged" rather than reconstruct it, and it is recomputed from the stamps on every write.

The stamp carries an `xsd:dateTime` where the design sketch showed an `xsd:date` — a deliberate deviation, because all six stages are normally done in one sitting and a date cannot order them.

## The queues

| # | queue | rule | source |
|---|---|---|---|
| 0 | documents to process | a file in the drop folder with no entity | `fs` |
| 1 | pending derivation | entity exists, no `derived` stamp | `sparql` |
| 2 | pending derivation curation | `derived`, no `derivationCurated` | `sparql` |
| 3 | pending tagging | `derivationCurated`, no `tagged` | `sparql` |
| 4 | pending tagging curation | `tagged`, no `taggingCurated` | `sparql` |
| 5 | pending summarization | `taggingCurated`, no `summarized` | `sparql` |
| 6 | pending summary curation | `summarized`, no `summaryCurated` | `sparql` |

An entity with all six stamps is complete, appears in no queue, and its status node reads **`curation complete`** — a state rather than the name of whichever act happened to be last (Rick, 2026-10-02). Safe to change because nothing reads the label: the queue rules key off the stamps. Queue 0 is a folder count rather than a rule about an entity, because nothing exists yet to carry state.

**Open: the legacy population.** 77 AI entities predate DTS and carry no stamps, so under the stamp rules every one of them sits in queue 1. `the:conceptsExtracted` is deprecated and will not be used as the exclusion, so the resolution is a one-time backfill stamping them complete. Not built.

## Stage 0 — the entity

**Input:** a markdown criticism export in the drop folder. **Output:** an entity record, the document in the sandbox, and a CURIE stamp in the document.

**The entity can be GENERATED from the document** (`POST /dts/entity/new`, a button beside each waiting document), and everything it proposes is derived from data the dashboard already holds — no model call, because a step that reads a title and counts vocabulary does not need one and paying for it would make queue 0 the only step with a cooldown.

- **The material** comes from what the artist said when they asked: "this digital sculpture", "this watercolor, 15x11 on cold press". That beats counting, which got it wrong on the first real pair — 7 digital against 6 watercolour, because several watercolour-scheme labels are common English words (`Balance`, `Overlap`, `nature`) that discriminate by scheme membership and not by meaning. Vocabulary frequency is the fallback, over the DISCRIMINATING labels only, and a document whose evidence is neck and neck is left for a person.
- **The topics** follow the store's own pattern, read off 60 real records: a watercolour criticism carries `[Criticism, Watercolor]`, a digital sculpture `[Criticism, Digital, Sculpture]`.
- **The source** comes from the export's own headings (`## Prompt:`/`## Response:` is ChatGPT, `## User:`/`## Assistant:` is Claude), which is more reliable than a filename a user may have renamed.
- **The work** is matched by label against every heading plus the first prompt — a criticism names its subject in a heading, while its title is often generic. Below the threshold **nothing is named**: on a real document the nearest label was `Thistle` at 0.73, and the matcher sits near 0.59 for unrelated strings, so a sub-threshold best is noise wearing a number.
- **Why each guess was made** is written onto the record as a `skos:note`, because "why does it say Digital" is a question the record should answer for itself tomorrow.

It then opens in **Edit Record**, which opens entities (§14.11) — which is what makes "generate then review" a workflow rather than a promise. A document with no human turn is refused and sent to the Entity form: it cannot describe itself, and an entity with an empty definition is worse than none.

Three things happen in a fixed order and the order is the point:

1. **Ingest**, trusted-side, through `FileOps`, so the `.ptr` sidecar is minted on arrival. A document copied in by hand is invisible to the git-derived manifest, so the record would reach the SOT while the markdown never followed — and every grounding phrase would then point at a document nobody downstream can read. The file lands under its normalized name; the drop folder keeps its own.
2. **The record**, through `record.new_entity`, so the confinement, the audit entry and the schema check are the ones every other writer gets.
3. **The CURIE stamp** on the markdown, through `doc.set_id`, because the later stages read that line to find which entity a document belongs to.

The `skos:definition` is **the first human turn in the document** — which is what every criticism record in the store already carries there. The reader takes it from `## Prompt:` (ChatGPT's heading) or `## User:` (Claude's), dropping the quoted metadata block of timestamps and attachment names. Keying on one of them would have produced a silently empty definition for the other.

## Stage 1 — derive

**Input:** the document, the existing concepts for this material. **Output:** new concepts with grounding, an evidence record, the `derived` stamp.

**Which concepts the model is shown** is scoped by the entity's own `the:topic`, through a config table. The concept agent hardcoded one map in which every category resolved to a watercolor scheme; for a criticism of a digital sculpture that would have shown 315 watercolor concepts as "do not duplicate" and none of the 77 tensegrity terms that are the actual neighbourhood.

**One vocabulary file per SESSION, not per entity.** A session is what a person means by "a run of DTS" — the documents they sat down to process — and it is the granule they would look for later. Per-entity naming reads well and still inflates the vocabulary folder by one file per document forever. `evidence/` stays per entity, because the two directories answer different questions: the vocabulary is read as a body of terms, the evidence as "what happened to this document".

**Which scheme a new concept joins is the ontology's answer, not a table's**: a derived concept joins the scheme its **broader term** is in. Measured across the 670 store concepts that have both a scheme and a scheme-bearing parent, 523 (78%) already sit in a scheme their parent is in, and most of the rest are scheme heads whose parent lives one level up. The config table remains the fallback for a concept whose parent is unknown, unplaced or absent, and every placement reports which rule decided it.

**What the dashboard decides about each proposal**, in this order:

- **Duplicate** — `max(rapidfuzz.ratio, token_sort_ratio)` at 0.9 against every labelled concept in the store, alt labels included on both sides. Dedup is deliberately *not* scoped by scheme: "do we already have this concept" is not a question about schemes. A duplicate cannot be ticked.
- **Neighbourhood** — the same scoring function at 0.70, capped at 5, for the curator to read. Measured: the Groovy's 0.45 gives the median concept 100 neighbours on this scale, 0.55 gives 17, 0.70 gives 2 with "unique" common.
- **Grounded** — is the quoted phrase actually in the document? Forgiving about line wrapping and curled quotes, strict about words.
- **Orphan** — does the broader term *resolve*? A broader term the model invented reads as a parent and behaves as none: the concept gets no `skos:broader`, inherits no type, and is discovered to be untaggable two stages later.

**`derive_limit` is a curation control before it is a cost one.** Unlimited, the model overran a 16,384-token cap on a 23 KB criticism, which arrives as broken JSON; and a person asked to include/exclude sixty proposals from one document is triaging rather than curating. Twelve.

**Nothing is written until the curator has decided**, which is what makes an abandoned curation leave no trace and a failed call leave no half-derivation.

## Stage 2 — tag

**Input:** the document and the concepts that already exist — **including the ones stage 1 just wrote**, because the thesaurus is read from the QA store rather than from a downstream SPARQL endpoint. That is the decision that lets DTS be done in one sitting: the old workflow's "distribute metadata, then refresh the DB to make concepts available for tagging" existed because the agent could not see a new concept until it had been published.

**Output:** TCAP-placed typed properties on the entity, one grounding node per tag, an evidence record, the `tagged` stamp.

The stage returns concept URIs and phrases; `concept.annotate_work` does the placing — the same tool the Annotate Work page uses, so a DTS-tagged entity and a hand-annotated work are placed by one implementation. It appends rather than replaces: the curated list is the whole of what was decided and there is nothing prior to preserve, and replacing would bring its scope rule along for no reason.

**Placement and grounding are written together from the curated list**, in one act, so the two cannot disagree about which concepts survived.

**The concepts this document's own derivation produced are proposed automatically**, and do not compete for a slot under the tag limit. A concept derived from this document is discussed in it by construction — that is what derivation means — and ranked against 250 pre-existing terms the model dropped four of them on the first real run. They are found from the data (a derived concept's grounding names its source entity) and carry that grounding phrase forward, so the tag is evidenced by the same words the concept was. Still curated like everything else.

Two checks, both the dashboard's: does the concept exist in the store, and is the phrase really in the document. An unknown URI cannot be ticked; an ungrounded tag can be, because that is a judgement.

## Stage 3 — summarize

**Input:** the document. **Output:** `the:summary` on the entity, an evidence record, the `summarized` stamp.

One paragraph, 100–150 words, stored verbatim as the entity's `the:summary`. The prompt carries two rules that are the accumulated tuning and must not be lost: a **recency rule**, because a criticism session evolves and the artwork may change mid-document, so the summary is based on the last update signal onward; and a **grounding rule**, because the model has not seen the artwork and every claim must be traceable to what the critic wrote.

Its curation is accept-or-send-back rather than include/exclude, and it is the natural home for a future "try again at a higher cost tier".

## Whose words, and what is fit to store

**A criticism export is a conversation, and the two sides are not interchangeable evidence.** The document cuts into turns on its headings, and a grounding phrase is attributed to the turn it appears in — the critic winning a tie, because quoting the artist back at them is still the critic using the words. A concept or tag grounded in the ARTIST's own turn is untickable by default: the critic picked the association up rather than making it. "Tend to" is a practice and not a law, so the proposal is shown with the reason and can be pulled back in.

**An ATTACHMENT is not prose.** A newer ChatGPT export embeds the artist's attachment as markdown — `![IMG_2103.JPG](https://chatgpt.com/backend-api/…&sig=…)` — where it used to write `[Attachment: …]`, and only the bracketed forms were recognised. So the embed became the first 230 characters of a 315-character `skos:definition` (2026-10-05). Three things were wrong with that and only one of them was cosmetic: the URL carries a 64-character expiring access signature into a record that converges to a published catalogue; and `match_work` and `detect_material` read a LIMITED window of the first prompt (400 and 600 characters), so a second attachment would push the work's name out of the window and the criticism would be tagged onto nothing, silently. Image embeds are stripped whole, alt text included — a camera filename is not a description. A markdown LINK is left alone: `[text](url)` is prose with a citation attached.

**DTS is where text hygiene stands**, because it imports the widest variety of text of anything in the system. Every literal it takes from a document or a model reply is cleaned at one boundary: angle brackets are DROPPED rather than escaped, C0 control characters go, and the gap a removal leaves is closed. `cwva-py` passes RDF literals through unescaped on the stated assumption that they come from controlled TTL files, so `viewed in <modelviewer>` would reach a browser as an unknown tag and the words would vanish from the page — and to a reader the difference between that and `modelviewer` is nothing.

## Agency and provenance

Agents and roles live in the **operations ontology**, not in a namespace of their own. `update_work_on_site.py` minted `…/agent/updateWorkOnSite`, which parsed and resolved to nothing: no class said what an agent was, no role said what it did, and no list said which models this deployment uses. `ops:` has all three.

A **role is not an agent**. `prov:wasAttributedTo` points at the agent that did the work — `ops:claude-sonnet-5`, `ops:user` — and `ops:hasRole` says the capacity it acted in. Conflating them would make "what did the curator decide" unanswerable without also knowing which model was in the chair. The user is `ops:user`, named by role and never by identity: CE v1 is single-user, and these records reach a published catalogue.

A record CITES its agents and declares none of them, the same way it cites `the:Prestress` without inlining a definition. It did inline two triples per agent, written before the operations ontology existed, and the cost showed only in the UX: three extra named subjects made the file fail the one-named-subject rule, so Edit Record would not open a DTS-processed entity and the Drafts page listed it as `<guid>.ttl (4 subjects)` with no way back in (2026-10-02). The inline copy was also wrong — it typed `ops:user` as a `prov:SoftwareAgent`, which the ontology contradicts with `prov:Agent, prov:Person`.

Nesting cannot rescue it. RDF has no scope: a triple with `ops:user` as its subject makes `ops:user` a named subject of the file wherever it is written, so a declaration cannot be hidden inside the status node. A reference can move there; a declaration cannot exist there.

## The grounding node

One shape, and the rule is which end it hangs from. A grounding relates three things — a concept, a phrase, and the document the phrase came from — and the node names two of them explicitly while the third is whatever it is attached to.

```turtle
the:CaroleDance the:grounding [          # on a DERIVED CONCEPT
        rdfs:label    "ground verified" ;
        the:phrase    "a round dance, a carole winding in one direction" ;
        the:srcEntity work:4dd85266-… ;
        the:match     the:unique ] .

work:4dd85266-… ops:status [              # on a TAGGED ENTITY: UNDER THE STATUS
        rdfs:label "curation complete" ;
        …
        the:grounding [
            rdfs:label  "ground verified" ;
            the:phrase  "merged silhouettes" ;
            the:concept the:SilhouetteMerging ] ] .
```

- **The entity-side node hangs under `ops:status`** (Rick, 2026-10-02: "The grounding is meaningless here. Can the grounding be moved under status?"). Twelve `ground verified` rows sat at the top of the criticism page, above the concepts they are evidence for. It is also where it belongs: a grounding on the entity is this run's account of why it tagged what it tagged, and the status node is the record of what the run did. The concept-side node does NOT move — that one is about the concept, which is why this vocabulary stayed in `the:` when the stamps went to `ops:`. It falls out that `clear_status` now removes the groundings too, so a reset has one less thing to remember.

- **`the:match` is derivation-only.** Tagging chooses from concepts that already exist, so "what is this near" does not arise, and its absence there is not an omission. `the:unique` is the empty case said out loud, because an absent predicate is indistinguishable from a match list nobody computed.
- **A match carries `the:matchType` as well as `the:distance`** — "these two strings are nearly identical" is not "these two share most of their words", and that is precisely the distinction a curator is being asked to make.
- **The context is not stored.** Storing the surrounding sentences copies a slice of the document into every concept and lets the copy drift; the phrase is stored and the context is recovered from the source on demand, through three hops that are all in the store. A document that has since changed is reported as such rather than answered with a window of arbitrary text that would look like evidence.
- **A not-found grounding is written and labelled**, never suppressed. It is the most useful line on a curation screen.
- **One grounding per concept.** A concept re-proposed from a second criticism is REJECTED at derivation, not corroborated with a second grounding node (Rick, 2026-10-01: "The specific derivation doesn't matter so long as it was well founded. A subsequent use of a concept should show up in tagging of the document."). This is what makes the two ends of the shape answer different questions: the node on the concept says why the concept EXISTS, which one well-founded derivation settles; the node on the entity says why THIS DOCUMENT is tagged with it, which is where the second document's evidence belongs. Nothing is lost — the second phrase is recorded, on the second document.

## What each stage writes, and where

| what | where | converges to SOT |
|---|---|---|
| the entity record | `ttl/data/<guid>.ttl` | yes |
| the criticism markdown | `documents/<Normalized>.md` | yes |
| derived concepts + grounding | `ttl/vocab/dts-<session>.ttl` | yes |
| TCAP placements | the entity record | yes |
| tag grounding | the entity record, UNDER `ops:status` | yes |
| the summary | the entity record | yes |
| the proposal record | `evidence/dts/<guid>/{derive,tag,summarize}.ttl` | **no** |
| in-flight proposals | `.qa/dts/<guid>/*.json` | no (gitignored) |

**`evidence/` is committed to the QA git and excluded from every manifest.** It has history across months and never reaches the published catalogue. The exclusion is in the manifest rather than the transport, which is the difference between "not sent" and "not part of the unit": the review stop does not list it, the gates do not read it, and a rollback reverts it in QA without touching a SOT that never had it.

**Rejections are recorded as rejections**, not left as an absence — with the status, the grounding phrase, the broader term the model *wanted* (which is the whole value of an orphan entry to the thesaurus-modelling task it feeds), and the reason. None of it is reconstructable afterwards.

## The tools

Everything that writes is a registry tool, and the tools decide nothing — which concepts survived curation, which scheme each joins, whether a phrase verified, all of it is settled before the call. A tool that re-derived any of it would be a second opinion able to disagree with the one the curator saw.

| tool | writes |
|---|---|
| `record.new_entity` | the entity record |
| `doc.set_id` | the CURIE line in the markdown |
| `dts.write_concepts` | derived concepts with grounding and `prov:` attribution |
| `concept.annotate_work` | TCAP placements |
| `dts.ground_entity` | the entity's tag grounding nodes |
| `dts.stamp` | one stage stamp, refusing out of order or twice |
| `dts.write_evidence` | the proposal record, refusing a path outside `evidence/` |
| `dts.reset` | the status node, placements, groundings and summary |

**The provider call is not among them, and cannot be.** The Landlock-confined worker cannot resolve a hostname — a fetch fails with `EAI_AGAIN` — so a tool that called a model would silently return nothing, which is how updateWorkOnSite's first real run wrote two empty snapshots. `ai_service` is a fifth member of the sanctioned network-effect class: a deliberate, audited effect in the trusted orchestrator whose pure result is handed to a tool that does the writing. It carries a credential, so it takes Instance Control's rules with it — the key is read per call from the environment or `~/.secrets.rson`, never retained, and never present in a completion, an audit entry or a log.

## Reset

`dts.reset` takes an entity back to "entity created": the whole status node, the TCAP placements, the groundings and the summary, plus the files the run produced elsewhere — which are named by the caller and **trashed rather than hard-deleted**, because nothing hard-deletes what a person's work produced.

It is a promotion unit like any other writer, because some of what it removes may already be in the SOT, so the deletions are previewed at the review stop and converge only on approval. It is not a quiet cleanup.

## Known properties worth stating

**Derivation is not reproducible.** Two runs over the same document produced overlapping but different concept sets. The current Claude models reject the `temperature` parameter outright, so there is no knob to pin it. This strengthens both the no-re-runs rule and the evidence record: the run a curator saw is the only account of what was on offer.

**Verification proves a phrase is in the document, not that a concept belongs in an art thesaurus.** The first curated run rejected "Contact sheet" — grounded and verified, and a description of how the *criticism* was produced rather than anything about the artwork. Only a person catches that.

**A generic heading inherits its scheme to everything under it.** "Historical and Conceptual Terms" lives in `the:tensegrityTerms`, so concepts parented there inherit a scheme they may have nothing to do with — the Three Graces is not a tensegrity term. Noted by Rick 2026-09-30; unresolved.

## Operating it

```
python scripts/dts.py status                       # every AI entity and its queue
python scripts/dts.py create --doc … --label … --topic … --tag …
python scripts/dts.py derive --entity <guid>       # proposes; writes nothing
python scripts/dts.py curate-derive --entity <guid> --exclude 'A,B'
python scripts/dts.py tag --entity <guid>
python scripts/dts.py curate-tag --entity <guid> --exclude 'A,B'
```

Everything lands uncommitted in the QA tree. Review it at Preview Staged and distribute it through the ordinary gated exit.

## Curation asks for a third answer

Keep and reject are not the whole of what a curator wants to say. The one that came up on the first run is **demotion**: `the:SelfStressState` is redundant with `the:Prestress` and belongs on it as an `skos:altLabel`, which is neither keeping the proposal nor rejecting it. Rick, 2026-09-30: "this points to the overlapping workflows of DTS and vocabulary management … That implies some way to assert that status during DTS curation and later, when appropriate, act on it."

So the curation screen needs to record a status that outlives the run, and something has to carry it until a vocabulary pass acts. The acting is `concepts/merge_demote.py` (retire → altLabel → reference rewrite), which is not built. The asserting belongs with the curation UX.

**A common concept is not a differentiator, and does not belong on a work at all.** `the:Node` and `the:Cable` are true of every digital sculpture in the catalogue, which is why tagging one with them buys no retrieval. They belong on a record whose subject is the CORPUS — "a catalog of the works or more likely a criticism of the catalog" — which would distinguish the works as a body. That is deliberately not mechanized as a filter: it is a judgement about the catalogue, not about the document.

## Deferred: the derivation criteria

Rick read one criticism by hand and collected eight concepts; Opus proposed one of them and generified it, and Sonnet proposed five of them nearly verbatim — which I then rejected, citing the prompt's own rules. The lever is therefore the CRITERIA and not the model: rule 8 forbids "ad hoc critic phrasings, rhetorical constructions, and invented compound terms" and requires an authoritative reference, rule 4 requires reusability across works, and his target is the propositions a criticism *contributes*. A stronger model complies harder with the rules as written.

Deliberately not touched — "This is the wrong time to challenge the prompt or other derivation criteria, we need to get through DTS QA" — and revisited post-DTS, possibly post-dashboard. `prompts.py` is one module, ported verbatim so that changing it is a decision rather than a drift. The evidence is in `PROJECT_PLAN.md` so the conversation can start from data.

## Not built

- Entity creation from queue 0 — a document in the drop folder still goes through the Entity form rather than a button on the DTS page.
- A proposing stage blocks its request for 30-60 seconds while the model answers. Honest for a single user and the first thing to revisit when it stops being one; the review already notes the step should run off the request thread so the screen can say *unavailable until HH:MM* rather than hanging.
- Acting on a demotion request (`concepts/merge_demote.py`). Asserting one is built; the queue accumulates in `evidence/vocabulary/demotions.ttl`.
- `record.new_entity` still writes the deprecated `the:conceptsExtracted false`.
- A `.ttl` route into the drop folder, for hand-authored model and vocabulary files. Not needed by DTS — derived concepts are written by a tool — but the ontology task has no ingress without it.
