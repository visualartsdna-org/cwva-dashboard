# PROVENANCE_PLAN.md — provenance records and the Disposition Identifier

**Status: phase 1 is largely done.** The backfill shipped on 2026-11-02, and since 2026-11-05 a profile form writes the incipient record on submit (`tools/provenance_tools.py`, shape `config/shapes/provenance.ttl`, `provenance_gate`), which settles §10.3: an id is spent once per work, and the gate refuses a duplicate. A digital profile form also asks for the original file and writes it as `vad:fileLocation`, converting a pasted `G:\\My Drive\\…` path to a `file:///` IRI; on the 31 records whose path is in `fileProvenanceList.txt` it reproduces the stored IRI exactly. Still open: the outlier report. This document records the model as settled in discussion on 2026-10-23/24, the constraints that keep it honest, and the details still open. The artist's design; the analysis, the counts and the objections are mine. Read `CE_DESIGN.md` for the architecture this has to live inside.

**Depends on `ONTOLOGY_PLAN.md`.** The `ttl/model` changes this feature needs are planned there, not here — they are mostly independent of provenance and they precede it. §4 below is the index into them.

## 1. What the feature is

Every physical or digital artwork gets a **provenance record** — a first-class record in `ttl/provenance`, one per custody fact — and each provenance carries a **Disposition Identifier (DI)**: a short, human-writable string that says where the thing actually is. The DI exists because a watercolour in a box in a studio cannot be found by querying its RDF; someone has to read a number off a box flap. It is stored rather than derived because it cannot be recomputed: the box a painting went into in 2022 is a historical fact, not a function of the current state of anything.

The provenance record is also where the chain of ownership lives, ordered chronologically, and — for works whose original is a file rather than an object — where the definitive file is named.

## 2. The Disposition Identifier

### Grammar

```
[ <storage-class> "." ] <year> "." <item>
```

- `<storage-class>` — a subjective, short name for a storage arrangement. **Optional, and a blank class is the default**, because for physical storage the label is usually hand-written and `159` beats `P.2026.159` on a box flap. Most work goes in the default box.
- `<year>` — the year of the work's `schema:dateCreated`.
- `<item>` — a **global, opaque, monotonic** integer, unique across the whole system.

Examples: `2026.159` (a watercolour in a box), `blender.2026.157` (a Blender composition whose original is a file), `wall.1982.292` (an egg tempera hanging on a wall, under a class that is not in the map).

### The item id is global and opaque

One counter for the entire system, never reused, never restarted per year, per artist or per storage class. It carries no information: it does not tell you the order of things in a box or how many are in one — those are queries. The decisive argument against a per-artist counter is that **the DI grammar has no artist component**, so two artists under a per-artist counter would both hold `2026.159` and the DI would stop identifying a provenance.

The year is therefore redundant for uniqueness. It stays because a human reading a label wants it.

The high-water mark is `max(vad:itemId)` over an integer literal — cheap, and specifically **not** string manipulation on the DI, which is why the item id is stored separately from the DI it appears in.

### Only the incipient provenance carries a DI

**Settled 2026-10-23.** A work's chain may hold several provenance records, and only the first — the artist's own, written when the work is entered — carries a `vad:dispositionId` and a `vad:itemId`. A transfer provenance carries neither, because a DI asserts where a thing is and a new owner's storage is not the artist's to claim.

Two consequences worth stating plainly.

**Carrying a DI is itself the marker of being incipient.** No extra term, flag or ordering rule is needed to identify the first record in a chain: it is the one with a `vad:dispositionId`. That makes the SHACL constraint "at most one provenance per work carries a `vad:dispositionId`", which is checkable without reference to dates — and date-based ordering would have been fragile for two records on the same day.

**After a sale the DI is a permanent label rather than a current location.** It says where the work was while the artist held it, and it never retires. That is the intended reading, not a defect, but it means `vad:dispositionId` is a stronger identifier than it is a locator once a work leaves.

### Storage class resolution

The storage class is resolved from the work's type through a map held as data — `vad:StorageSolution` instances in the store. **The instances are the map**; there is no configuration file and no code-side table.

1. Collect the work's `rdf:type`s that are subclasses of `vad:ArtForm`.
2. Find the `vad:StorageSolution` instances whose `vad:hasWorkType` subsumes one of them.
3. **Most specific wins.**
4. **No match → the blank storage class.** This is the resolver's base case, not a record, so incipient provenance is possible in every case — including on day one with an empty map, which yields blank classes for everything and is a working system.

Resolution by subsumption is safe here because the type hierarchy is a **strict tree**: 77 classes under `vad:ArtForm` and **zero with more than one direct parent**, so most-specific-wins is a total function with no ties. A SHACL constraint should assert that, not because it is violated but because the day a second parent appears the map becomes ambiguous with nothing to announce it.

Subsumption also makes the map immune to a data defect already in the store: 16 watercolours are typed three times over (`Watercolor`, `PaintingForm`, `VisualArtForm`), a remnant of an RDFS reasoner. Under most-specific-wins they resolve to `Watercolor` whichever of the three are mapped, so cleaning the remnant is hygiene rather than a prerequisite.

### Why the default solution should still list its work types

A blank-class solution carrying `vad:hasWorkType vad:Watercolor, vad:Drawing` resolves to exactly the same string as no record at all. It earns its place for a different reason: it is the only thing that distinguishes **"mapped to default"** from **"unmapped, fell to default"**, and that distinction is what makes the outlier report usable. List the types and the report names the egg tempera and anything new. Omit them and every type in the collection shows as unmatched on every run, 190 works' worth, and the signal is buried. Same resolution either way; only the report changes. The work types on the default record are report tuning, not resolution input.

A `vad:ArtForm` catch-all solution is expressible and should not be used: it makes everything match, so nothing is ever an outlier, which cancels the migration workflow the report exists to drive.

### Storage class migration

A function measures the dataset against the map (SHACL plus a report) and lists the works whose type matches no solution. Each is offered a migration to a type-specific storage class. The consequence that makes this worth building: new work falls into the default class without ceremony and can be migrated as a group later, so the map can be wrong or empty at the start without blocking anything.

Editing a provenance may change the DI's **storage class**, never its year or item id. A class not in the map is accepted — `wall.1982.292` is a legal DI — and shows on the report as an outlier. That is why the DI is stored and not derived: once it can hold a class the map does not know, no function can reproduce it.

## 3. The records

### A storage solution

```turtle
work:{guid} a vad:StorageSolution ;
    rdfs:label   "default storage solution" ;
    rdfs:comment "boxes; the ordinary disposition for work on paper" ;
    vad:storageClass "" ;
    vad:hasWorkType vad:Watercolor, vad:Drawing .

work:{guid} a vad:StorageSolution ;
    rdfs:label   "blender file storage solution" ;
    rdfs:comment "abstract container for original work" ;
    vad:storageClass "blender" ;
    vad:hasWorkType vad:BlenderComposition .

work:{guid} a vad:StorageSolution ;
    rdfs:label   "digital file storage solution" ;
    rdfs:comment "configuration or creation metadata" ;
    vad:storageClass "digital" ;
    vad:hasWorkType vad:LindenmayerSystemImage .
```

The map keys on **work type, not artist profile**, and this was a deliberate reversal. Three reasons, in increasing strength: types come from the ontology and are always available while a profile is data that may be absent; an edit to a profile would silently re-map storage for every work made under it; and the profile key was **already wrong on real data** — 2 of the 15 `LindenmayerSystemImage` works sit under the "Digital paint application" profile rather than the "Lindenmayer System" profile, so a profile-keyed map would have mis-filed them while scoring 100% profile coverage. Coverage is not correctness.

`rdfs:comment` is worth having on every solution. "Other media may temporarily reside here" is the sentence that stops someone later "fixing" an egg tempera into a box it does not need.

### An object provenance

```turtle
work:1110 a vad:Provenance ;
    vad:hasArtwork      work:1234 ;
    vad:hasArtworkOwner work:{owner} ;
    vad:dispositionId   "2026.159" ;
    vad:itemId          159 .
```

### A file provenance

```turtle
work:1111 a vad:FileProvenance ;
    vad:hasArtwork      work:1235 ;
    vad:hasArtworkOwner work:{owner} ;
    vad:dispositionId   "blender.2026.157" ;
    vad:itemId          157 ;
    vad:fileLocation    <file:///G:/My%20Drive/abc/def/aphrodite.blender> .
```

`vad:FileProvenance rdfs:subClassOf vad:Provenance .`

A `BlenderComposition`'s `.blend` file **is** the digital sculpture, and an `LindenmayerSystemImage`'s JSON configuration is the image, the raster being algorithmically generated from it. So the file is the artifact, not a copy of one, and the provenance is the right place to name it. The value is the **definitive version** — the point of the field is to spare a search through folders and multiple near-identical files — so it is single-valued.

Three things about `vad:fileLocation`:

- **It is documentary only.** No gate resolves it. The target is outside the sandbox by definition, and a `G:` drive does not exist on the Linux host at all. This needs saying beside the term, because `vad:fileLocation` looks exactly like something a referential-integrity gate ought to check.
- **It is the source artifact, never the work's published image.** Those already have a mechanism (pointer-managed binaries). Nothing should ever conflate the two.
- **The IRI must be a real IRI.** `file://G:/My Drive/…` fails twice: the space is not legal in an IRI, so `URIRef` accepts it and the Turtle serializer does not — the 2026-09-17 relative-IRI failure mode, which parses for the gates and throws on the preview with no failing gate to explain it; and `file://G:/` makes `G:` the **authority**, i.e. a hostname, which is the opposite of the server-indifference the cloud path was chosen for. The correct form is three slashes and percent-encoding: `file:///G:/My%20Drive/…`. Encode at the field, where the user can see it, alongside the existing refusal of `<>" {}|\^` + backtick.

A cloud path (`G:` as a mounted Drive, or a third-party URL) is preferred over a local one precisely because it is server-indifferent. A `file:` IRI naming a local folder resolves against whatever machine the reader happens to be on, which is acceptable but not good.

If a Blender file is ever published, that is an Entity with its own IRI, and the reference existing in two places is not a conflict.

### An artwork owner

Already in the store and unchanged in shape, except that `foaf:mbox` takes the `mailto:` scheme (§6).

## 4. Ontology changes — see `ONTOLOGY_PLAN.md`

**This feature depends on ontology changes that are planned, sequenced and justified separately in `ONTOLOGY_PLAN.md`.** They are mostly independent of provenance and they **precede** it; none of them is restated here.

| what this feature needs | there |
|---|---|
| `vad:ArtEvent`, and `vad:Provenance` reparented under it | §3 |
| `schema:startDate` as the event date, via the `schema:Event` alignment | §3, §4 |
| the seven new terms: `StorageSolution`, `storageClass`, `hasWorkType`, `FileProvenance`, `fileLocation`, `dispositionId`, `itemId` | §5 |
| the five terms already in use but undeclared: `ArtworkOwner`, `hasArtwork`, `hasArtworkOwner`, `hasPrivacyRestriction`, `PaintApplicationImage` | §6 |
| the `vad:ArtDomain` hierarchy change, which `vad:ArtEvent` sits inside | §2 |
| the ontology task sequence, and what gates it | §7, §11 |

Nothing there is open any longer; the last blocking question — the event date property — was settled as `schema:startDate` on 2026-10-24 (`ONTOLOGY_PLAN.md` §4).

## 5. Constraints (SHACL)

Conformance is assumed enforced here rather than in the ontology, per the standing decision that an ontology which will never meet a reasoner is the wrong place to rein in a range.

**`vad:StorageSolution`**
- exactly one `vad:storageClass`, `xsd:string`; **may be empty**, so no `sh:minLength`
- `vad:storageClass` unique across all solutions
- `vad:hasWorkType`: `sh:nodeKind sh:IRI`; every object `rdfs:subClassOf+ vad:ArtForm` (SPARQL constraint)
- `rdfs:label` required

**The type hierarchy**
- no subclass of `vad:ArtForm` has more than one direct named parent (SPARQL constraint; currently 0 violations of 77 classes)

**`vad:Provenance`**
- exactly one `vad:hasArtwork`, one `vad:hasArtworkOwner`, one `schema:startDate`
- `vad:dispositionId` and `vad:itemId` `sh:maxCount 1` each, and present together or not at all — a provenance has both (incipient) or neither (transfer)
- **at most one provenance per work carries a `vad:dispositionId`**, which is how the incipient record is identified
- `vad:itemId` **globally unique** — a monotonic counter is only as good as the thing that stops it being reused
- `vad:dispositionId` globally unique
- `vad:itemId` must be the `<item>` component of `vad:dispositionId`

**`vad:FileProvenance`**
- `vad:fileLocation` `sh:maxCount 1`, `sh:nodeKind sh:IRI`
- absolute IRI with a scheme; no raw spaces or other characters the Turtle serializer rejects

**`vad:ArtworkOwner`**
- `foaf:mbox` an absolute IRI (which is to say: `mailto:`)

**The outlier report** is the non-rejecting half of the same measurement: works whose type matches no solution, listed with the migration offer. It is a report, not a gate — an unmapped type is a true statement about the map, not a malformed record.

## 6. Existing data that needs attention first

- ~~`ttl/provenance/provenance.ttl` is an aggregate of four named subjects.~~ **DONE 2026-10-27, and the earlier deferral is obsolete.** Split by hand into **11 one-subject files**, each named for its subject's guid, so the one-named-subject rule is satisfied and Edit Record can open every one — which unblocks phase 2's editable provenance ahead of schedule. Three more owners and four more provenance records were added at the same time, taking the set to **6 provenance + 5 `vad:ArtworkOwner`**.
  **The aggregate itself must be DELETED in the same distribution.** Staging the 11 new files does not remove the old one, and if both reach the SOT then four subjects exist in two files each — with the *stale* copies carrying exactly what this change replaces: the relative `foaf:mbox` IRIs and `schema:dateCreated` instead of `schema:startDate`. The fix would be shadowed by its own predecessor. Deletions are part of the channel (law 4); confirm the old dashboard's distribute path actually carries one, because `seed_shadow_sot.py` on the QA side does not (§11a).
- **Both `foaf:mbox` values are relative IRIs** — a bare address in angle brackets, with no `mailto:` scheme. These resolve against whatever base the reader uses; this is the exact shape that made one artist save break every subsequent promotion with no failing gate. Fix to `<mailto:…>`.
- ~~The two existing provenance records use `schema:dateCreated`.~~ **DONE 2026-10-27:** all six now carry `schema:startDate`. **One thing left on them:** the literals read `"2026-10-27"^^xs:dateTime` — a date lexical form under a dateTime datatype, which is not a valid `xsd:dateTime` and contradicts the `rdfs:range xsd:date` now declared on the property. rdflib silently normalizes it on parse to `"2026-10-27T00:00:00"`, so a parse-and-reserialize invents a midnight nobody asserted — the parses-one-way-rewrites-another shape. Change the datatype to `^^xs:date`; the values themselves are already right. See §7.
- ~~One work has no `schema:dateCreated`.~~ **WITHDRAWN 2026-10-27 — there is no such work.** The subject was `the:DigitalSculptureProcesses`, a `skos:ConceptScheme` that legitimately carries `vad:hasArtistProfile` (it is attributed to the Blender practice), and a concept scheme has no creation date and will never want a DI. The original count treated every `vad:hasArtistProfile` subject as a work, which is the same confusion that argues against narrowing that property's domain (`ONTOLOGY_PLAN.md` §8). **Every actual work is dated.**
- **One work is typed with a class that does not exist.** `work:7fa9876c-…` ("finwin", a logo, created 2022-10-03) is typed `vad:PaintApplicationImage`, which is **declared nowhere in the ontology** — a sibling of the four undeclared properties in `ONTOLOGY_PLAN.md` §6. It matters for this feature specifically: the class is not under `vad:ArtForm`, so the storage-class map cannot reach the work at all. It falls to the blank class and can never be mapped to anything else until it is either retyped or `vad:PaintApplicationImage` is declared in the `vad:ArtForm` hierarchy. (It is also one of the two non-artwork subjects of `vad:hasArtistProfile` noted in `ONTOLOGY_PLAN.md` §8.)
- **16 works are triple-typed** (`Watercolor` + `PaintingForm` + `VisualArtForm`), an RDFS reasoner remnant; the source file should carry one type. Harmless for resolution under most-specific-wins, worth cleaning anyway.
- QA holds test data that production does not — the "Benny's Alternate Reality" profile and its one `VirtualRealityArt` work. Counts below are QA counts.

### Current inventory (QA, including test data)

| profile | type | works |
|---|---|---|
| Watercolor materials | `vad:Watercolor` | 180 |
| Watercolor materials | `vad:Drawing` | 10 |
| Watercolor materials | `vad:EggTempera` | 1 |
| Blender application | `vad:BlenderComposition` | 16 |
| Lindenmayer System | `vad:LindenmayerSystemImage` | 13 |
| Digital paint application | `vad:LindenmayerSystemImage` | 2 |
| Benny's Alternate Reality (test) | `vad:VirtualRealityArt` | 1 |

Unmapped under the initial map, and therefore the first outlier report's contents: `vad:EggTempera` (1) and `vad:VirtualRealityArt` (1, test only).

Works per `dateCreated` year: 1980 (1), 1982 (1), 2019 (4), 2020 (4), 2021 (18), 2022 (40), 2023 (50), 2024 (27), 2025 (47), 2026 (32).

## 7. Date semantics

**Settled 2026-10-24: the event date is `schema:startDate`**, inherited from `vad:ArtEvent`'s `schema:Event` alignment (`ONTOLOGY_PLAN.md` §3, §4). It replaces `schema:datePublished`, which read as a publication rather than a transfer and would have collided with a future `PublicationEvent`.

For the **incipient** provenance, `schema:startDate` is the work's `schema:dateCreated` — the work entered the artist's own custody when it was made. For a **transfer** provenance it is the date of the transfer. The chain is ordered by `schema:startDate`.

The DI's `<year>` component still comes from the **work's** `schema:dateCreated`, not from the event, because that is the authoritative creation year; for the incipient record the two agree in any case. Four works have a year between creation and publishing simply because they predate the RDF data.

Resolved with it: the two existing records' `schema:dateCreated` values (2023-11-09, 2022-11-09) are **transfer dates**, which is exactly what `schema:startDate` means on a transfer provenance. They were never the work's creation date and never a publication — so only the property name changes, not the values, and no third property is needed.

## 8. The provenance report

A per-work or whole-collection view showing the chain, the DI, the owner, and a thumbnail. Explicitly allowed to be inefficient: thumbnails are constrained by `<img>` size attributes and **nothing is stored** — no generated derivatives, no cache. It is an artifact of the request.

## 9. Phasing

**Phase 1 (this proposal)**
- the ontology changes (`ONTOLOGY_PLAN.md` §§2-7) and SHACL (§5)
- split `provenance.ttl`; fix the two `mailto:` IRIs
- the `vad:StorageSolution` records for the initial map
- backfill an incipient provenance per work, allocating DIs
- DI allocation on entry submit: the submit writes the work and its incipient provenance and allocates the item id
- a refresh parameter covering provenance
- the conformance/outlier report

**Phase 2**
- editable provenance: owner name, address, mbox, and the DI's storage class
- the migrate-to-class action on the outlier report

**Phase x**
- terminal provenance for a destroyed or discarded work ("I tore up the paper after entering it")
- a digital entry form that can create the generative types — `vad:LindenmayerSystemImage` sits under `vad:DigitalArtForm` and nothing in the dashboard can create one today, so until that exists a new generative work cannot get a DI because it cannot be entered
- the six `vad:SculptureForm` subclasses have zero instances; no provenance consequence until one does

NFTs are explicitly out of scope.

## 10. Open details

1. ~~Does every provenance in a chain carry a DI, or only the incipient one?~~ **Settled 2026-10-23: only the incipient one.** See §2.
2. ~~The event date property.~~ **Settled 2026-10-24: `schema:startDate`.** See §7 and `ONTOLOGY_PLAN.md` §4.
3. ~~Where exactly the item id is allocated.~~ **Settled 2026-11-05:** on the profile form's submit, as `max(vad:itemId) + 1` over the tree. A re-submit of the same work finds its record and keeps the id; `provenance_gate` refuses a duplicate id, DI or second incipient record on the way to the SOT. Two dashboards allocate independently, which is harmless because QA's shadow is a separate SOT.
4. ~~The one undated work.~~ **WITHDRAWN 2026-10-27: there is no such work** — the subject was a `skos:ConceptScheme`. All 223 works are dated. See §6.
5. ~~`vad:Provenance`'s parent.~~ **Settled 2026-10-24: under a new `vad:ArtEvent`.** See `ONTOLOGY_PLAN.md` §3.
6. ~~Whether `vad:ArtworkOwner` goes under `vad:ArtsPersonRole`.~~ **Settled 2026-10-23: yes.** See `ONTOLOGY_PLAN.md` §6.
7. ~~Whether digital works get an object provenance as well as a file provenance.~~ **Settled 2026-10-23: a digital work gets a `vad:FileProvenance` and nothing else.** Its storage class therefore describes a folder rather than a container, which is what `rdfs:comment "abstract container for original work"` is for. If a digital sculpture ever gets a physical rendition, that rendition is **a new work** with its own object provenance and its own DI — a storage facility, presumably — related to the digital work by `the:tag`. No new machinery.

## 11. The artist's preparatory tasks

**✅ ALL FOUR DONE, and the backfill they gated shipped on 2026-11-02**: 222 provenance records and 3 `vad:StorageSolution`s generated into a staging folder, distributed to production, re-seeded into the shadow and refreshed into both instances. Coverage is 222 of 222 production works, one record each, validated against the production tree. `vad:itemId` 1–222; DIs unique, grammatical, and agreeing with the storage class the work's type resolves to. See `PROJECT_PLAN.md`'s Current position block for what validating against production rather than QA caught — three QA-only works that would have shipped dangling `vad:hasArtwork` references, and one production work (`finwin`) that fell through both batches.

The storage map as built: `digital` ← LindenmayerSystemImage, GenerativeArt, DigitalPainting; `blender` ← BlenderComposition; the blank default ← Watercolor, Drawing. `vad:EggTempera` is in no solution and so falls through to the blank class, which is the designed outlier behaviour of §2 rather than a gap.

The tasks as agreed 2026-10-23, in this order:

1. **All the ontology work, in the order `ONTOLOGY_PLAN.md` §11 gives it** — which includes stripping the 16 materialized ancestor chains and resolving `vad:PaintApplicationImage`, because those gate the hierarchy change.
2. **Retype the six `schema:startDate` literals** from `^^xs:dateTime` to `^^xs:date`, and **stage the deletion of `provenance.ttl`** (§6). Splitting, the `mailto:` IRIs and the property rename are all done.
3. Distribute to SOT.
4. Refresh the dashboard.

Four notes on carrying that out.

**Hand-editing `.ttl` inside the sandbox is safe, and that is specific to text.** Law 12's prohibition exists because a hand-placed *binary* gets no `.ptr` sidecar and is therefore invisible to the git-derived manifest — the record converges while the bytes never do. A `.ttl` is ordinary git content under `git_content_extensions`, so git sees the edit directly, the manifest picks it up, and promotion previews and gates it like any other change. The deletion of the aggregate file is likewise part of the channel and will appear in the preview. This is also the deferred **vocabulary authoring surface** item in `PROJECT_PLAN.md` showing its cost: every task above is hand work because nothing in the dashboard can author an ontology change.

**All six existing provenance records are transfer records, not incipient ones** (as of 2026-10-27; it was two). No owner among the five is the artist, so under §2 none of them carries a DI — correctly. The six works they belong to each still need an *incipient* provenance added, with the artist as owner, to hold the DI. So the backfill is not uniformly one provenance per work: **those six works get two**. The works are Sea Turtle Diving, Watering Hole, Window Detail, Deadvlei, On Pierpont Meadow Pond and Raven Cliffs Falls — all `vad:Watercolor`, all present and `vad:CreativeWork`-typed, referential integrity confirmed.

**Their dates will not equal the works' `dateCreated`, and that is correct.** `2023-11-09` and `2022-11-09` are transfer dates. The rule "the event date is implied by the work's `dateCreated`" applies to the incipient record only; a transfer record's `schema:startDate` is the date of the transfer, which is what these already hold. Renaming the property is all that is needed.

**Refresh is destructive, so distribute first.** `POST /refresh` (and `GET|POST /api/refresh`) discards work in progress, pulls the SOT into QA, adopts it as the baseline and reloads the ontology and registries. `GET /refresh` is the read-only preview — it reports what a refresh would destroy and then asks. Step 3 before step 4 is therefore not just tidy ordering; reversing it loses the edits.

### 11a. Making the edits in the old dashboard and importing

The intended route is: edit outside the sandbox in the old dashboard, distribute to the production SOT, then bring the changes into the new dashboard by refresh. **This works, with one hazard that needs an extra step and two checks.**

Six of the seven tasks are edits *within* files — the ontology terms, the undated work, the 16 triple-typed works, the two `mailto:` IRIs, the property rename. A re-seed overwrites a file wholesale, so all of those arrive intact. `shadow_sot.qa_only` is deliberately empty, so nothing is held back from a re-seed either.

**The hazard is the one task that deletes a file.** Splitting `provenance.ttl` removes the aggregate and adds four `{guid}.ttl` files. `seed_shadow_sot.py` converges a `ChangeManifest(adds=…)` with **no deletes**, so a re-seed brings the four new files into the shadow and **leaves the aggregate there**. The subsequent shadow→QA sync then gives QA *both*: every provenance subject present in two files, which breaks the one-named-subject rule — the same shape that stopped Edit Record opening a DTS-processed entity.

The fix uses only the ordinary channel, and the order matters:

1. edit and distribute from the old dashboard to production;
2. `python scripts/seed_shadow_sot.py` — the shadow now holds the four new files *and* the stale aggregate;
3. refresh the QA instance (`POST /refresh`, or `sync_shadow_to_qa.py --adopt`) — QA now holds both;
4. **delete `ttl/provenance/provenance.ttl` in QA and promote.** Deletions are part of the channel and this is the only way to remove something from the shadow;
5. `python scripts/gate_baseline.py`.

The **production instance (:8102) needs none of that** — it syncs against the real bucket, and sync brings the tree into line with the target including deletions, so a plain `/api/refresh` is enough and arrives clean in one step. Only the shadow-backed QA instance has the adds-only problem. `verify_shadow.py --compare` will correctly report the aggregate as drift in the window between steps 2 and 4.

**Check one: the old dashboard has no gates.** It writes directly, so nothing parses, SHACL-validates or checks referential integrity on the way to production. `gate_baseline.py` after the sync is the first time these edits are checked at all — worth running rather than assuming, because a malformed ontology edit surfaces later as a promotion that fails with no failing gate to explain it.

**Check two: the domain choices in `ONTOLOGY_PLAN.md` §5 now have a UX consequence as well as an entailment one.** A refresh reloads the ontology *and the registries*, and form widgets are derived from the schema. A new property declared `rdfs:domain rdfs:Resource` can therefore surface on forms where it does not belong. Keep the domains narrow — `vad:StorageSolution`, `vad:Provenance`, `vad:FileProvenance` — and the new terms stay invisible until something is built to use them.
