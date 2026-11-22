# ONTOLOGY_PLAN.md — changes to the CWVA model

**Status: proposal for review. Nothing here is implemented.** This document holds the `ttl/model` changes agreed in discussion on 2026-10-23/24. They are mostly independent of, and **precede**, the provenance feature — `PROVENANCE_PLAN.md` depends on §3, §4, §5 and §6 here and does not restate them. Rick's design; the analysis, the counts and the objections are mine. Measurements are against the QA store, which includes some test data production does not have. **Every decision here is settled as of 2026-10-24**; what remains is the work in §11.

Two things in here are **not part of the lift**: the `vad:ArtistInMedia` rename (§8), which was attempted and postponed and now has its own document, and the `vad:ArtEvent` subclasses (§9), which are a future phase.

## 1. The rule for deciding a hierarchy change

Adopted 2026-10-24, because the door that opens onto one reorganization opens onto many.

**Adopt a hierarchy change when it makes the model stop saying something false, or when it lets a query be written that could not be written before. Decline one whose argument is only that it is more principled.**

The `vad:ArtDomain` change in §2 passes that test: `ArtsPersonRole rdfs:subClassOf vad:Art` asserted that a person's role *is* a kind of art, and `ArtProduction` inside it asserted that a tube of paint is. Those are wrong statements in a published model. A generic upper layer of abstract wrapper classes (§10) passes neither half of the test, which is why it is not adopted.

## 2. The `vad:ArtDomain` hierarchy change

**Settled 2026-10-24.** A new root `vad:ArtDomain` — "The domain encompassing art, its realization, interpretation, participants, institutions, and associated activities" — and `vad:Art` is **collapsed away**, with `vad:VisualArts` becoming a direct branch of the domain. The single-root invariant is preserved: `vad:ArtDomain` replaces `vad:Art` as the one root, and the model has never had two.

```
ArtDomain                                    NEW root
├── VisualArts                               vad:Art COLLAPSED AWAY
│   └── ArtRealization                       stays: these ARE the works
│       ├── ArtForm            (77)
│       └── CreativeWork       (2)            210 direct instances
├── ArtProduction          (146)             MOVED out of ArtRealization
│   ├── ArtMaterial        (74)
│   ├── Technique          (25)
│   ├── Tool               (23)
│   ├── Process            (20)
│   └── DigitalLanguage                      MOVED out of Vocabulary (dissolved)
├── VisualAnalysis         (40)              MOVED out of VisualArts
├── ArtEvent                                 NEW (§3)
│   └── Provenance
│       └── FileProvenance
├── Aesthetics                               MOVED out of Art
├── ArtMarket              (5)               MOVED out of Art
├── ArtsPersonRole         (13)              MOVED out of Art
│   └── ArtworkOwner                         NEW (§6)
├── ArtworkCollection      (9)               MOVED out of Art
└── StorageSolution                          NEW (§5)
```

**`ArtRealization` is split rather than moved.** Moving it wholesale, as first proposed, would have taken `ArtForm` and `CreativeWork` with it — the chain is `Watercolor → PaintingForm → VisualArtForm → ArtForm → ArtRealization` — so every artwork type and all **210 records directly typed `vad:CreativeWork`** would have left `vad:Art`. `vad:artist` declares `rdfs:domain vad:Art` with 40 triples in use, so RDFS would then have entailed those works back into `vad:Art` while the asserted hierarchy denied it, leaving the model stating two different things. Lifting `ArtProduction` out instead achieves the intent at the same edit cost, and the existing comments already draw the line: `ArtRealization`'s "Through a creative process manifesting an idea in a visual form" is about the manifested thing, while `ArtProduction`'s "All of the materials, processes, techniques, and factors involved in creating visual art" plainly is not art.

**`vad:Vocabulary` is dissolved, and `DigitalLanguage` moves to `ArtProduction`.** The ambivalence about this class resolved once the subtree was read: `vad:Vocabulary` was defined as "The specialized terms used to discuss art" — discourse, which would have argued for `ArtDomain` — while its only descendants are `DigitalLanguage` ("Codes and symbols used in digital art creation") and `LsysRules` ("Production rules for Lindenmayer systems"), which are generative notation and belong under `ArtProduction`. Once the children leave, nothing is left: the subtree has **zero instances** throughout, and terminology already has a home in `vad:DigitalSculptureTerm → SculptureTerm → FormalAnalysis → VisualAnalysis`, which carries "Terminology applied to the creation or appreciation of digital sculpture" — exactly what `vad:Vocabulary`'s own definition described. A class with no instances, no children, and a definition another branch already serves is not earning its place.

### Collapsing `vad:Art`

**Settled 2026-10-24.** With `vad:ArtDomain` above it, `vad:Art` has nothing left to do: it would hold a single child (`VisualArts`), which would hold a single child (`ArtRealization`), and a level that holds one thing is a synonym rather than a structure — the same objection that rules out the upper layer in §10. `vad:ArtDomain` is the general container now, and **`vad:VisualArts` is what this ontology is actually about**, so it should be the top of the subject matter rather than a tier down from a generality the model never uses.

The collapse is cheap, and measurably so. Nothing outside the model references `vad:Art` at all — no Python, no config, no shape file, no HTML. Inside the model, seven triples point at it, and four of them resolve themselves:

| reference | disposition |
|---|---|
| `Aesthetics rdfs:subClassOf vad:Art` | already moving to `vad:ArtDomain` |
| `ArtMarket rdfs:subClassOf vad:Art` | already moving to `vad:ArtDomain` |
| `ArtsPersonRole rdfs:subClassOf vad:Art` | already moving to `vad:ArtDomain` |
| `ArtworkCollection rdfs:subClassOf vad:Art` | already moving to `vad:ArtDomain` |
| `VisualArts rdfs:subClassOf vad:Art` | becomes `rdfs:subClassOf vad:ArtDomain` |
| **`vad:artist rdfs:domain vad:Art`** | **must be re-pointed — 40 triples in use** |
| **`vad:hasNFT rdfs:domain vad:Art`** | **must be re-pointed — 33 triples in use** |

**Both become `rdfs:domain vad:VisualArts`. Settled 2026-10-24** — an artist produces visual art, and an NFT is minted against one. These two are the part of the collapse that would otherwise **fail silently**: a domain naming a class that no longer exists still parses, still serializes, and entails membership of nothing, so no gate reports it and the entailment simply stops happening.

**And the 16 records in §7 must be stripped first.** They are directly typed `vad:Art` as well as `vad:VisualArts`; removing the class before stripping them leaves 16 records typed with a class declared nowhere, which is exactly the `vad:PaintApplicationImage` defect in §6, self-inflicted.

One small loss to accept knowingly: `vad:Art`'s gloss — "The expression or application of human creative skill and imagination" — disappears with it. `vad:ArtDomain`'s comment describes the *domain*, not art, so the definition is not inherited. That is the right trade for a model scoped to the visual arts, but it is a deletion rather than a move.

## 3. `vad:ArtEvent`, and `vad:Provenance` moving under it

**Settled 2026-10-24.** This supersedes an earlier resolution to leave `vad:Provenance rdfs:subClassOf vad:ContextualAnalysis` alone, which rested on the art history being sound — provenance research *is* contextual analysis — and on the is-a/is-about looseness it carried being consistent with the rest of the model. `vad:ArtEvent` is better than either option on the table then, because it makes the subsumption true of the *instances*: an art event is an occurrence, and a provenance record documents an occurrence.

```turtle
vad:ArtEvent
  rdf:type owl:Class ;
  rdfs:label "Art Event" ;
  rdfs:subClassOf vad:ArtDomain, schema:Event ;
  rdfs:isDefinedBy <http://visualartsdna.org/model/> ;
  rdfs:seeAlso <https://en.wikipedia.org/wiki/Visual_arts> ;
  rdfs:comment "Any documented occurrence, action, or milestone that impacts the physical state, historical record, or conceptual existence of a work of art." ;
.

vad:Provenance
  rdf:type owl:Class ;
  rdfs:label "provenance" ;
  rdfs:subClassOf vad:ArtEvent ;
  rdfs:isDefinedBy <http://visualartsdna.org/model/> ;
  rdfs:seeAlso <https://en.wikipedia.org/wiki/Provenance> ;
  rdfs:seeAlso vad:ContextualAnalysis ;
  rdfs:comment "Any documented transaction, transition, or milestone that alters the ownership, legal title, custody, or physical location of a work of art." ;
.
```

**`rdfs:subClassOf vad:ArtDomain`, not `vad:Art`.** An earlier draft of this plan said `vad:Art`, correctly for the hierarchy as it stood — the model had exactly one root and a class declared with no parent would have become the second. With `vad:ArtDomain` adopted, an art *event* is not art, and `ArtEvent` is a direct branch of the domain. **A declaration with no `rdfs:subClassOf` at all is still wrong**, for the original reason: 306 `vad:` classes and one root is an invariant worth keeping.

**Keep the contextual-analysis relationship as a reference, not a subsumption.** `rdfs:seeAlso vad:ContextualAnalysis` preserves the art-historical point while the parent says what an instance *is*. That resolves the is-a/is-about distinction in the right direction rather than papering over it, and it makes an explanatory `skos:scopeNote` unnecessary, because `vad:ArtEvent` says it.

**`schema:Event` alignment adopted. Settled 2026-10-24.** `vad:ArtEvent` carries two parents: `vad:ArtDomain, schema:Event`. `rdfs:subClassOf` is not single-valued, so this is legal, and it is the standard way to align a local class to an external one. It is also categorically different from multiple inheritance *within* `vad:` — the model stays a single-parent tree internally, and the second parent is an alignment statement rather than a reclassification. The single-inheritance SHACL constraint in `PROVENANCE_PLAN.md` §5 is scoped to `vad:ArtForm` subclasses and does not apply.

Not `owl:equivalentClass`: that would assert every `schema:Event` is an art event, which is false.

This is **one decision with §4**, and it is what makes `schema:startDate` honest. Using schema.org's properties without its classes is the asymmetry §10 names as the model's real interoperability deficit — 306 local classes and not one external alignment, while the data has been borrowing `schema:dateCreated` and `foaf:name` all along. This is the first class-level alignment in the model, and the cheapest one available.

**Do not add an `owl:imports` for schema.org.** An `rdfs:subClassOf` to an external IRI needs no import; nothing in the pipeline resolves external IRIs, and the SHACL and vocabulary gates do not look outside the store. Importing schema.org would pull a large vocabulary into every parse for no benefit. The model's header comment lists only SKOS, and that stays true.

## 4. The event date: `schema:startDate`

**Settled 2026-10-24.** `vad:ArtEvent` carries `schema:startDate`, inherited by `vad:Provenance`, `vad:FileProvenance` and every future subclass in §9. It comes with the `schema:Event` alignment in §3 rather than being declared locally, so there is no new `vad:` term for it.

This replaces `schema:datePublished`, which was always uncomfortable on a provenance — published what? — and would have become actively misleading once `PublicationEvent` existed as a sibling class, where `datePublished` reads as a publication rather than a transfer.

**What it means on each record.** For the **incipient** provenance, `schema:startDate` is the work's `schema:dateCreated` — the work entered the artist's own custody when it was made. For a **transfer** provenance it is the date of the transfer. The custody chain is ordered by `schema:startDate`. The DI's `<year>` component still comes from the **work's** `schema:dateCreated` rather than from the event, because that is the authoritative creation year and the two agree for the incipient record anyway.

**The declared range has to serve every subclass, and already does not.** `schema:startDate` is `rdfs:range xsd:date` in `schemaSupplement.ttl`, which fits the provenance records and not the proof records, whose dates are `xs:dateTime` (§14). One inherited property means one declared range across every event type, and §9's subclasses will widen the spread further. The resolution recommended in §14 is to drop the `rdfs:range` and constrain per subclass in SHACL, which is this project's standing policy anyway.

**Two properties the alignment also brings, free and not used yet.** `schema:endDate` is meaningless for a transfer, which is instantaneous, but it is exactly what `ExhibitionEvent` will want — part of why the alignment pays beyond this feature. And `schema:location` is available if a provenance ever wants to say where an event happened, as distinct from where the work is stored.

**Consequence for the task list:** `PROVENANCE_PLAN.md` §11 task 5 renames `schema:dateCreated` to **`schema:startDate`** on the two existing provenance records, which already hold transfer dates (2023-11-09, 2022-11-09) and are therefore already correct values under the new reading. One precedent worth knowing: `work:7fa9876c-…` carries `schema:datePublished` equal to its `schema:dateCreated`, which is the semantics this adopts, under the name it does not.

## 5. New terms for provenance and the Disposition Identifier

Required by `PROVENANCE_PLAN.md`. Following the house style in `ttl/model/cwva.ttl` — `rdf:type`, `rdfs:label`, `rdfs:isDefinedBy <http://visualartsdna.org/model/>`, `rdfs:seeAlso`, `rdfs:comment`.

| term | kind | domain | range |
|---|---|---|---|
| `vad:StorageSolution` | `owl:Class` | — | — |
| `vad:storageClass` | `owl:DatatypeProperty` | `vad:StorageSolution` | `xsd:string` |
| `vad:hasWorkType` | `owl:ObjectProperty` | `vad:StorageSolution` | `rdfs:Class` |
| `vad:FileProvenance` | `owl:Class`, `rdfs:subClassOf vad:Provenance` | — | — |
| `vad:fileLocation` | `owl:ObjectProperty` | `vad:FileProvenance` | `rdfs:Resource` |
| `vad:dispositionId` | `owl:DatatypeProperty` | `vad:Provenance` | `xsd:string` |
| `vad:itemId` | `owl:DatatypeProperty` | `vad:Provenance` | `xsd:integer` |

**`vad:StorageSolution rdfs:subClassOf vad:ArtDomain`. Settled 2026-10-24.** A storage solution is an infrastructural fact about where art lives: it is not visual art, production, analysis, a market, an event or a collection, so it is a direct branch of the domain. `vad:ArtworkCollection` was the alternative considered, and rejected because that branch's tenants — `Oeuvre`, `Edition`, `Series`, `Portfolio`, `Catalog`, `ArtExhibition` — are curatorial groupings rather than physical containers, and a box would be an odd sibling.

**`vad:hasWorkType` points at a class, not an instance.** That is ordinary RDF, but it means SHACL `sh:class` is the wrong constraint — it would demand the object be an *instance* of the named class. The check is `sh:nodeKind sh:IRI` plus a SPARQL constraint that the object is `rdfs:subClassOf+ vad:ArtForm`. Easy to get wrong in a way that validates.

**`rdfs:domain` and `rdfs:range` entail** (CLAUDE.md law; only SHACL rejects). Declaring `rdfs:domain vad:Provenance` on `vad:dispositionId` means anything carrying a disposition id *is* a provenance, which is wanted here. Where entailment is not wanted the existing convention is `rdfs:domain rdfs:Resource`, as `vad:hasArtistProfile` does. Each domain above is a choice to make deliberately, not a formality — and §8 has a worked example of getting it wrong.

## 6. Terms already in use but undeclared

These are in production data today and appear nowhere in the ontology. Pre-existing debt, and this is the moment to close it, because every one is load-bearing for the provenance feature.

| term | kind | used in |
|---|---|---|
| `vad:ArtworkOwner` | `owl:Class`, `rdfs:subClassOf vad:ArtsPersonRole` (the data also types owners `foaf:Person`) | both owner records |
| `vad:hasArtwork` | `owl:ObjectProperty` | both provenance records |
| `vad:hasArtworkOwner` | `owl:ObjectProperty` | both provenance records |
| `vad:hasPrivacyRestriction` | `owl:DatatypeProperty`, range `xsd:boolean` | both owner records |

**`vad:ArtworkOwner` under `vad:ArtsPersonRole`. Settled 2026-10-23.** An owner is a role a person holds with respect to a work, which is what that branch is for.

**`vad:hasPrivacyRestriction` is documentary only** — it records an intention, and nothing in the system enforces it. That is already a deferred item in `PROJECT_PLAN.md`, and the declaration's `rdfs:comment` should say so, so nobody reads it as access control. §9 is where it stops being adequate.

**A fifth undeclared term, with a different cause.** `vad:PaintApplicationImage` is declared nowhere, yet one record is typed with it — `work:7fa9876c-…` ("finwin", a logo, created 2022-10-03). Unlike the four above it is not load-bearing machinery; it is a type somebody wrote once. It matters for provenance because it is not under `vad:ArtForm`, so the storage-class map cannot reach that work at all: it falls to the blank class and can never be mapped to anything else. Resolve it by **retyping the record** or by **declaring the class under `vad:ArtForm`** — the first is likely right, since nothing else uses it.

## 7. Data entanglements that gate the hierarchy change

**Sixteen records carry materialized ancestor chains from an old RDFS reasoner run.** They are directly typed `vad:Art`, `vad:VisualArts`, `vad:ArtRealization`, `vad:ArtForm`, `vad:VisualArtForm`, `vad:PaintingForm` *and* `vad:Watercolor` — the whole ancestry, asserted. That is why they were first reported as "triple-typed"; the remnant is deeper than three types.

They are the only data the hierarchy change touches, because **nothing is typed `ArtDomain`, `ArtProduction`, `Aesthetics`, `ArtMarket`, `ArtsPersonRole`, `ArtworkCollection`, `Vocabulary`, `DigitalLanguage` or `LsysRules`** — those moves are pure ontology edits with no instances to migrate. So **strip the 16 back to their leaf type first** and the hierarchy change has no data consequence at all. This is a hard prerequisite for collapsing `vad:Art` (§2), not merely tidiness: those 16 records assert `vad:Art` directly, and deleting a class still named by 16 `rdf:type` triples manufactures the §6 defect on purpose.

It is also the right fix on its own terms: a source file should assert one type and let the ontology say the rest.

## 8. Postponed: `vad:ArtistProfile` → `vad:ArtistInMedia` — see `ARTIST_IN_MEDIA.md`

**POSTPONED 2026-10-28, with no date.** The rename was settled on 2026-10-24, brought forward on 2026-10-28 to ride with §12, analysed in full, applied to the dashboard code, and then reverted.

**The reason is scheduling, not modelling.** The old Groovy server is still load-bearing until the dashboard replaces it, and the rename breaks it in several places — all of them silently, since every reference there is a hardcoded IRI inside a SPARQL or SHACL string, so a mismatch returns no rows rather than an error. The worst is the gallery home page going empty with nothing logged. It also required a production server upgrade, which was not the expectation when it was brought forward.

The model argument is unaffected and still holds: `vad:ArtistProfile rdfs:subClassOf vad:ArtsPersonRole` says a *document about a role* is a role, and this is the one piece of the 2026-10-28 is-a/is-about cleanup left undone — `vad:ArtEvent` (§3) was the other half.

**`ARTIST_IN_MEDIA.md` holds everything**: the names and why they are the right ones, the measured blast radius on both sides, what must NOT be renamed with the terms and why (the recorded scenarios), the four sites that fail *silently* with mutation results for each, the three rollout strategies with the reason each was accepted or rejected, and the checklist for the next attempt. The code half is `5daa34f`, reverted and ready to re-apply.

One thing was kept from the reverted work: `tests/ux/test_profile_cards.py::test_a_PROFILE_record_DOES_rebuild_the_registry`, written against the old term. It closes a gap that was never contingent on the rename — nothing asserted that a profile arriving through the approve path rebuilds the registry, so a stale string there would have left a profile form serving the shape it had before, silently.

## 9. Future: `vad:ArtEvent` subclasses

Proposed for a later release: `CreationEvent`, `ModificationEvent`, `ExhibitionEvent`, `PublicationEvent`, `ValuationEvent`, `LossOrRecoveryEvent`. Nothing to build now; three observations worth recording while they are cheap.

**`LossOrRecoveryEvent` is the home for the terminal case** that `PROVENANCE_PLAN.md` §9 defers to phase x — a work destroyed or discarded after being entered. It should never have been a provenance (a provenance alters custody; destruction ends the object), and now it does not have to be.

**`CreationEvent` already exists, inlined on the work record.** `schema:dateCreated`, `vad:hasArtistProfile`, the materials and the techniques are a creation event flattened onto the work, and the incipient provenance's rule — its date implied by the work's `dateCreated` — is that same event borrowed. When `CreationEvent` becomes a record there is a duplication decision: either the work keeps the flattened properties and the event is redundant, or the properties move and every work record changes. Worth knowing in advance rather than discovering it then.

**`ValuationEvent` is sensitive data heading for a public bucket.** Appraisals and insurance valuations would converge through the ordinary channel like everything else, and `vad:hasPrivacyRestriction` (§6) is documentary only. If valuations become records, that is the point at which a privacy flag has to mean something, or valuations have to be local-only in the sense `evidence/` is (`LOCAL_ONLY_DIRS` in `promotion/unit.py`, which takes two exclusions, not one). A real decision, not a hypothetical.

## 10. Not adopted: a generic upper ontology

Considered 2026-10-24 and declined: a rigorous upper layer — `Entity → CreativeDiscipline → Art`, `CreativeActivity → ArtRealization`, `IntellectualDiscipline → Aesthetics`, `EconomicSystem → ArtMarket`, `Role → ArtsPersonRole`, `Collection → ArtworkCollection`.

**The payoff of an upper ontology is interoperability, and a home-grown one has none.** DOLCE, BFO, SUMO and CIDOC-CRM earn their keep because other people's data already uses them, so alignment makes two datasets joinable. `vad:Entity`, `vad:Role` and `vad:Collection` would be new local vocabulary nobody else uses — the appearance of rigour without the payoff it exists for. Worth weighing against where the model stands: of 306 classes, the only non-`vad:` superclass reference anywhere in it is SKOS, three times. There is no external class alignment at all.

**As drafted it is seven classes holding six.** Every new upper class has exactly one child. A level that holds one thing is a synonym rather than a structure, and "Aesthetics is an intellectual discipline" is already stated in its `rdfs:comment`, where it costs nothing and misleads nobody.

**If interoperability is the real goal, the answer is CIDOC-CRM, and it is additive.** This project sits squarely in its domain, and the §9 subclass list is independently rediscovering its event model — approximate correspondences: `E5 Event`/`E7 Activity` ≈ `ArtEvent`, `E12 Production` ≈ `CreationEvent`, `E10 Transfer of Custody` and `E8 Acquisition` ≈ `Provenance`, `E11 Modification` ≈ `ModificationEvent`, `E78 Curated Holding` ≈ `ArtworkCollection`, `E39 Actor` ≈ `ArtsPersonRole`, `E22 Human-Made Object` ≈ `CreativeWork`, `E53 Place` ≈ what a `StorageSolution` points at. That convergence is a good sign about the modelling. It is also the cheapest rigour available: `vad:Provenance rdfs:subClassOf crm:E10_Transfer_of_Custody` moves nothing, breaks no consumer, and makes the data joinable with museum data. Alignment is one triple per class, and only the classes worth it need one.

A related asymmetry worth naming: the **properties** in use are already interoperable — `schema:dateCreated`, `schema:creator`, `schema:datePublished`, `foaf:name`, `foaf:mbox` — while the **classes** are entirely local. That gap, not the absence of an upper layer, is the real interoperability deficit.

### What CIDOC-CRM alignment would actually buy

Asked 2026-10-24. Four benefits, ranked by whether they pay now, and one redirection.

**1. A design reference. This is the one worth using immediately, and it is free.** CRM has had thirty years of argument about exactly the questions this week produced — is-a versus is-about, where a custody record sits, whether an event or an object is the anchor. The `vad:ArtEvent` model in §3 arrived independently at CRM's central commitment, that the event is the thing you model and the object is a participant. CRM already encodes the answers to the next ten of those questions, so reading it while §9's subclasses are designed catches mistakes before they are in 221 records. A worked example: `vad:hasArtworkOwner` is single-valued, so a transfer provenance records who holds the work but not who they received it from — recoverable by ordering the chain, which works and is cheaper, where CRM's `E8 Acquisition` splits `P22 transferred title to` and `P23 transferred title from` and makes it explicit and order-independent. Not a defect in the current design; an illustration of what the reference surfaces for free.

**2. Harvester-readiness, which is optionality rather than a benefit.** CRM underlies EDM and therefore Europeana, and the Linked Art profile over it is what Getty, Yale, the Rijksmuseum and the NGA publish. Alignment lowers the cost of a future submission from "write a bespoke mapping" to "point at the endpoint". It does **not** cause discovery — aggregators ingest what is submitted to them. So this is a publication feature that becomes valuable the day a submission is contemplated, and worth nothing before.

**3. Nothing internally.** There is no reasoner, and the gates do not resolve external IRIs. A CRM alignment is inert inside the dashboard, which means it should be judged as a publication decision and not an architecture one.

**4. The practical target is Linked Art, not raw CRM.** Raw CRM is verbose by design: a date becomes an `E52 Time-Span` with `P82a`/`P82b`, a dimension an `E54 Dimension` with an `E58 Measurement Unit`. The QA store already holds **1,273 blank nodes against 22,499 triples**, and faithfully preserving nested blank nodes has been a bug class twice (one level deep was not enough; a profile template round-tripped 29 of 78 triples). *Remodelling* in CRM would multiply that. **Aligning** — `rdfs:subClassOf` to a CRM class, as §3 now does for `schema:Event` — avoids it entirely, and is the only version of this worth considering.

**The redirection: the alignment with the better ratio is probably not CRM at all.** The store holds **947 `skos:Concept`s** and already carries **245 external `skos:*Match` triples** — so the habit exists. But they point at encyclopaedias: Wikipedia 192, DBpedia 28, CAMEO 18, Tate 2, and **Getty 4, AAT 2, VIAF 0, ULAN 0**. Wikipedia is good for a human reader and weak for machine interoperability with cultural-heritage systems. The 18 CAMEO matches show the right instinct already applied — a conservation-science vocabulary for materials. Re-pointing some of that effort at **Getty AAT** would convert locally-defined concepts into globally-identified ones, one concept at a time, with no hierarchy change, no migration and no consumer breakage. It is also a job the DTS pipeline could *propose* rather than one done by hand, which puts it closer to the grain of what is already built than a class alignment is.

**Timing, and why it differs from everything else in this document.** Class alignment is one triple per class, additive, reversible, and breaks no consumer — so unlike the hierarchy changes it does **not** get more expensive with time. The argument for doing §2 and §3 now was that 221 records were about to be written against them; the opposite applies here. **Recommendation: use CRM as a reference while §9 is designed, do not spend on class alignment yet, and if one external-alignment project is wanted, make it AAT on the thesaurus.** The AAT item is recorded as a deferred item in `PROJECT_PLAN.md`, beside the thesaurus-hierarchy and concept-demotion revisits it shares scope with.

**Two costs specific to this project.** The 16 records in §7 carry materialized ancestor chains, so every upper-layer change makes more of them stale. And the model is published: reshuffling ancestry changes the behaviour of anyone's subsumption query against visualartsdna.org. Additive alignment has neither cost.

## 11. Task sequence

**✅ ALL EIGHT DONE.** Steps 1–7 were distributed 2026-10-27 and refreshed into both deployments; step 8's domain opening followed on 2026-11-01 ("cwva.ttl with domain CreativeWork fixes distributed"), and §14's `vad:ProofEvent` plus `vad:merklePath` went out with the proof records on 2026-11-02. `vad:ArtistProfile` → `vad:ArtistInMedia` (§8) remains postponed — see `ARTIST_IN_MEDIA.md` — and §9's event subclasses are still future work.

The ontology work, in order. `PROVENANCE_PLAN.md` §11 holds the provenance-specific data tasks and the route by which all of it reaches the deployments; the two lists interleave at the distribution step.

1. **Strip the 16 materialized ancestor chains** back to the leaf type (§7). First, because it is the only data the hierarchy change touches, and because collapsing `vad:Art` with those `rdf:type` triples still asserted would leave 16 records typed with a class declared nowhere.
2. **Resolve `vad:PaintApplicationImage`** — retype `work:7fa9876c-…`, or declare the class under `vad:ArtForm` (§6).
3. **The `vad:ArtDomain` hierarchy change** (§2): the moves, dissolving `vad:Vocabulary`, collapsing `vad:Art`, and re-pointing `vad:artist` and `vad:hasNFT`'s domains.
4. **Declare `vad:ArtEvent`** with `rdfs:subClassOf vad:ArtDomain, schema:Event`, and **reparent `vad:Provenance`** under it (§3). `schema:startDate` arrives with the alignment (§4); no local date term is declared.
5. **Declare the seven new provenance/DI terms** (§5), `vad:StorageSolution rdfs:subClassOf vad:ArtDomain` among them.
6. **Declare the five terms already in use** (§6).
7. Distribute, refresh, and run `scripts/gate_baseline.py` — see `PROVENANCE_PLAN.md` §11a, which has the hazard in the shadow re-seed and the reason the gates matter here.

8. **Open the domain on 13 work-annotation properties, keep it on 7** (§12) — found after distribution, so it is a second pass rather than part of the lift. `vad:hasComposition` and `vad:hasElement` are already done.

Deferred to their own phases: §8 (the rename) and §9 (the event subclasses).

## 12. A property domain must not mistype a non-work subject

Found by Rick 2026-10-27, after the lift was distributed and cwva QA refreshed: roughly sixty entities were showing as `vad:CreativeWork`. Nothing in the lift caused it — it is pre-existing, and the lift's `rdf:type` cleanup is what made it visible.

**The cause.** An AI criticism records what it discusses, so it carries `vad:hasComposition`. That property declares `rdfs:domain vad:CreativeWork`, and `rdfs:domain` **entails** — so every entity using it is a creative work. Measured: **58 of the 164 entities**, all via `vad:hasComposition` alone, and none of them carries `vad:CreativeWork` explicitly.

The underlying modelling fact is that the property is used in **two senses**: on a work, `vad:hasComposition` says the painting was composed that way; on a criticism, it says the criticism is *about* that composition. One property, two readings, and a domain can only describe one of them.

**`rdfs:domain vad:ArtForm` does not fix it, and Rick reached the same conclusion unprompted.** `vad:ArtForm` and `vad:CreativeWork` are siblings under `vad:ArtRealization`, so the domain would simply entail the entity is an `vad:ArtForm` instead — and since `ArtForm` is "Category or channel of artistic expression", that reads worse: a criticism would be an art *category*. It swaps one false entailment for another.

**The fix is to leave the domain open.** Either omit `rdfs:domain` or declare `rdfs:domain rdfs:Resource`; the two are semantically identical, since everything is an `rdfs:Resource`. The model already contains one of each pattern for exactly this reason — `vad:hasArtistProfile rdfs:domain rdfs:Resource` (its subjects include a `skos:ConceptScheme`, §8) and `vad:hasProcess` with no domain at all, already used on 15 entities without incident. **A slight preference for the explicit `rdfs:Resource`**, because it reads as a deliberate choice and discourages a later reader from "helpfully" adding a domain back; bare omission records nothing.

This is also the standing policy arriving from another direction: conformance belongs in SHACL, not in an ontology that will never meet a reasoner. A shape can say "on a `vad:CreativeWork`, `vad:hasComposition` must …" without entailing anything about a criticism.

### Scope — widened by Rick 2026-10-28

`vad:hasComposition` was the property caught in the act, but it is not the only one at risk. A criticism makes judgements about a work, and the concepts that come out of that could legitimately connect any of the *material* and *technical* properties to the entity — a criticism that discusses the paper, the paint, the surface or the technique. Fixing only the one that happened to fire would leave the rest waiting.

So the boundary is drawn by a principle rather than by current usage: **a property keeps `rdfs:domain vad:CreativeWork` only if nothing but a work can carry it.** That is the properties about the work *as a physical or published object*; everything about its materials and making opens up, because a criticism can reference those.

**Keeps the domain (7).** `vad:background`, `vad:workOnSite`, `vad:status`, `vad:inspiredByWork`, `vad:image3d`, `vad:hasRendition`, and `vad:hasCriticism`.

**Opens to `rdfs:Resource` (12).** `vad:hasAdditive`, `vad:hasPaint`, `vad:hasPaper`, `vad:hasPerspective`, `vad:hasPrinciple`, `vad:hasProcessStep`, `vad:hasProtectiveFinish`, `vad:hasSurface`, `vad:hasTechnique`, `vad:hasTool`, `vad:hasVisualImagery`, `vad:hasWatercolorPaint`. **All twelve were distributed 2026-10-29.**

**`vad:fileFormat` is RETIRED instead of opened. Settled 2026-10-31.** It was the thirteenth on this list and the only one never done, and it closes by deprecation rather than by a domain change: a file extension tells a sufficient story, so the term is marked deprecated in the model and never written again. **The 19 existing triples on 16 records stay.** They are all on works, so the `rdfs:domain vad:CreativeWork` that was going to be opened entails nothing wrong, and leaving the data alone costs nothing.

```turtle
vad:fileFormat
  owl:deprecated true ;
  rdfs:comment "Deprecated 2026-10-31: a file extension tells a sufficient story. Never written for new records; retained because 19 existing triples use it. For a media type, schema:encodingFormat is the term." ;
.
```

**This is not a reversal of §8's refusal to deprecate**, and the difference is worth naming because it will look like drift. There, deprecation was proposed as a **bridge** — `owl:equivalentClass` keeping a renamed term's old queries working — and Rick rejected it correctly: without a reasoner the equivalence helps nobody, so it breaks the same people while looking considerate. Here deprecation is a **label**: the term and its data both stay, nothing is being redirected, and the audience is a human reading the published model. A label works where a bridge does not.

So this list is complete, and §12 needs nothing further.

**Already done.** `vad:hasComposition` and `vad:hasElement` were opened in the staged model on 2026-10-27, which clears the 58 entities.

Two notes on carrying it out.

**`vad:hasCriticism` is an ADDITION, not a retention.** It has no `rdfs:domain` today, only `rdfs:range vad:ArtCriticism`. Giving it `rdfs:domain vad:CreativeWork` entails that anything carrying a criticism is a creative work — true, and consistent with the keep-list principle, but it is a new assertion rather than one being left alone.

**Nothing in the system reads these domains, so this is entailment-only.** No `RDFS.domain` or `rdf-schema#domain` reference anywhere in `src/`; the sole SHACL shape targets `vad:ArtistProfile` by class; the `domain` keys in the configs are the sovereign `work:` namespace, unrelated. The entry forms take their labels and help text from the ontology's `rdfs:label` and `rdfs:comment` (`WORK_FIELD_PROPERTIES`), never from a domain. So no form changes, no template changes, no gate changes, and no data migration.

**One consequence for the model's readability.** `rdfs:domain rdfs:Resource` goes from a single use — `vad:hasArtistProfile`, the exception — to roughly fifteen. It stops being an exception and becomes the norm for work-annotation properties, so it is worth one `rdfs:comment` or `skos:scopeNote` somewhere saying *why*: an open domain here is a deliberate refusal to entail, not an omission. The seven that keep `vad:CreativeWork` then read as the deliberate ones.

### Why it has to be a second pass

The lift is already distributed to the SOT and cwva QA is refreshed, so this is an ontology-only edit on top of it: fifteen property declarations, no data migration, nothing to backfill. The 58 entities need no change — they stop being entailed `vad:CreativeWork` the moment the domain opens, because the type was never written into any record. It will, however, want a **cwva server refresh** to take effect, since the entailment lives in the inference model rather than in the files, which is also how to verify it: the count of entities typed `vad:CreativeWork` should go from 58 to 0.

## 13. Debt: `vad:hasCriticism` is misnamed

**Recorded 2026-10-29 as cwva-side debt.** Not urgent, and not a deletion.

The property was proposed for deletion on the grounds that `the:tag` already relates a work to its criticism, so this would never be used. It is **in use on 50 triples**, and it is not that relationship:

- **subjects** are AI criticism entities — 48 typed `the:AI, the:Entity, skos:Concept, rdfs:Resource`, 2 typed `the:AI` alone
- **objects** are `skos:Concept`s — "Observational Fidelity", "Structural detail as subject"
- **none of the 50** is duplicated by `the:tag`, in either direction

So it records *which critical concepts a criticism raises*. That is a real statement nothing else in the store carries, and `the:tag` relates work↔criticism instead — a different edge. Deleting it would lose all 50.

**What is wrong is the name.** `vad:hasCriticism` on a criticism entity pointing at a concept reads backwards: it sounds like work→criticism and it is criticism→concept. `vad:raisesConcept` says what the triples assert; `vad:raisesCriticalConcept` is longer and less ambiguous against the thesaurus's general sense of "concept". Rick to choose.

**It is DTS output, not an orphan.** A first pass at this entry said nothing referenced the property; that was wrong. `vad:hasCriticism` is what **TCAP** writes when it places a criticism-flavoured concept: `concepts/tcap_navigation.py` chooses a property by matching `rdfs:range` against the concept's effective type, and `the:Criticism` resolves through `rdfs:range vad:ArtCriticism`. `tests/concepts/test_tcap_navigation.py:151` asserts exactly that, `tests/workflows/test_annotate_work.py` lists it beside `vad:hasComposition` as a tie candidate, and `tests/dts/test_reset.py` requires `dts.reset` to remove it. So the 50 triples are DTS stage-2 tagging output, and the property is in the DTS lifecycle rather than waiting for a surface.

**Blast radius.** 50 data triples; the declaration in `cwva.ttl`; and **9 references across 4 dashboard test files**. Nothing in the dashboard's `src/`, `config/` or `html/`, and nothing in cwva-py's code, `res/` or documents.

**TCAP survives the rename untouched**, because it selects on `rdfs:range`, never on the property's name — so navigation keeps working the moment the renamed property keeps `rdfs:range vad:ArtCriticism`. What has to move with the name is the four test files, which hardcode it.

**DEFERRED by Rick 2026-10-31, pending a review of the TCAP modelling as a whole.** The name is misleading but not wrong, and a rename decided in isolation would be guessing at what the model should say.

**The ordering is right, not merely cautious.** TCAP selects a property by matching `rdfs:range` against a concept's effective type, so the property's name is *downstream* of its range and the range is TCAP's business. Renaming first would settle the cheap half while the half that governs behaviour stayed open — and if the review then changed `rdfs:range vad:ArtCriticism`, `the:Criticism` would stop resolving and DTS would silently place nothing where it places 50. Reviewing the model first puts the decisions in dependency order.

Rename rather than delete, whenever that review happens. `skos:historyNote` recording the old name, per §7 of `ARTIST_IN_MEDIA.md`. One caution on the chosen name: TCAP's whole mechanism is range-driven, so a name that reads well is free — but **do not change `rdfs:range vad:ArtCriticism`** while renaming, or `the:Criticism` stops resolving and DTS silently places nothing where it used to place 50.

## 14. `vad:Proof` → `vad:ProofEvent`, under `vad:ArtEvent`

**Proposed by Rick 2026-10-30. Not implemented.** A proof is a blockchain anchor event with documentation, so it belongs in the event branch §3 opened, and the name should say so.

```turtle
vad:ProofEvent
  rdf:type owl:Class ;
  rdfs:label "Proof Event" ;
  rdfs:subClassOf vad:ArtEvent ;
  rdfs:isDefinedBy <http://visualartsdna.org/model/> ;
  rdfs:comment "The anchoring of an asset's hash in a blockchain, with the transaction that records it." ;
  skos:historyNote "Formerly vad:Proof, renamed 2026-10-30." ;
.
```

### The parent pays immediately

`vad:ArtEvent rdfs:subClassOf vad:ArtDomain, schema:Event` (§3), so **`schema:startDate` is inherited** — and a timestamp anchor is the one record type where an event date is the whole point. The 24 existing records carry two:

```turtle
vad:created    "2026-04-06T15:10:16"^^xs:dateTime      # this system wrote the record
vad:timestamp  "2026-04-06T08:22:25-04"^^xs:dateTime    # the blockchain transaction
```

**Settled 2026-10-31, after two wrong answers.** `vad:created` is **removed**, and `schema:startDate` is the **date part of `vad:timestamp`, read in the timestamp's own offset**. `vad:timestamp` itself is preserved exactly as the service reported it.

The two discarded answers are worth keeping, because each was wrong for a different reason.

*Map `vad:timestamp` to `schema:startDate`* — rejected by Rick: the timestamp is one of a tuple the external service reported, beside `vad:transaction` and `vad:rootHash`, and restating it as a schema.org property turns someone else's attestation into our own assertion. Anyone verifying the proof against the chain needs the service's timestamp in the service's terms, next to the transaction id that makes it checkable. **A fact an external system reported stays in the terms it reported it in** — the same instinct as `vad:fileLocation` being documentary (`PROVENANCE_PLAN.md` §3) and an editor preserving verbatim what its form does not own (`CE_DESIGN.md` §14.10).

*Map `vad:created` instead* — rejected by the data. **11 of the 24 records have `vad:created` BEFORE the event it records**, by up to 331 hours. It cannot be the event date because for nearly half the corpus it precedes the event. It is most likely the *submission* time — OriginStamp batches, and `FUNCTION_INVENTORY` #5 records an "OriginStamp key + 24 h wait" — but the other 13 run the other way, so the property means two different things across the corpus. That inconsistency, not its low usefulness, is the case for removing it. If a submission time is ever wanted it deserves a term that says so.

So: **remove `vad:created`**, and derive. The derived value is our own coarser claim about when the event happened, not a restatement of the service's instant, which is why it does not violate the rule above. It also needs no policy change — `schema:startDate` keeps its declared `rdfs:range xsd:date` (§4), nothing is truncated that matters, and the provenance constraint set on 2026-10-28 is untouched.

**Read the date in the timestamp's own offset, never in UTC.** `xsd:date` cannot carry a zone, so taking the UTC date would silently assert a UTC convention that nothing in the record states. The anchor at `2026-08-25T20:21:21-04:00` is `2026-08-26T00:21:21Z`, and the two disagree on the day. Rick's choice is the local reading throughout. **One systematic consequence, by design rather than accident: `schema:startDate` is the day BEFORE the UTC broadcast date for 22 of the 24**, because the service broadcasts just after midnight UTC. A consumer comparing `startDate` against a chain's UTC date will see a consistent one-day offset. Both statements are true about the same instant; only one of them can be a zoneless date.

### The 24 timestamps are wrong, and have to be corrected first

Found while settling the above, and the reason the derivation could not just be run.

**Every `vad:timestamp` is 12 hours early.** The OriginStamp certificate renders a 12-hour clock and the PM was lost in transcription. Confirmed against a block explorer by Rick: the Last Supper transaction reports `8/26/2026, 00:21:21 UTC`, so the record's `08:21:21-04:00` should read `20:21:21-04:00`. Every one of the 24 falls in hour 07 or 08 and **none is 13:00 or later**, which is what a 12-hour clock with a dropped meridiem looks like; `vad:created`, by contrast, spans 09 to 16 with 9 afternoon values, so it is a genuine 24-hour clock.

Verification of the whole set: with +12 hours and the correct US-Eastern offset, **22 of 24 land between 00:00Z and 00:59Z**. A sixty-minute window across thirteen months is not chance, and it independently confirms both the correction and Rick's reading that the platform broadcasts shortly after midnight UTC.

**Three offsets are also wrong for their date**, found by the same pass:

| record | stored | correct | why |
|---|---|---|---|
| `96442557…` (2026-08-25) | `-21:00` | `-04:00` | not a legal offset at all; XSD permits −14:00 to +14:00 |
| 2026-10-06, first | `-03:00` | `-04:00` | 6 October is EDT — US DST ends the first Sunday in November |
| 2026-10-06, second | `-03:00` | `-04:00` | same; UTC−3 is South America, so these were read off a display set elsewhere |

**Two records do not fit and need checking at the source:** both `2026-02-20T08:32:39-05:00`, which become `01:32:39Z` — an hour later than every other broadcast. The offset is right for February, so it is either a genuinely late batch or an hour's transcription error. They are the only pair that misses the window.

**`rdflib` accepts `-21:00` with `ill_typed=False`.** It parses, serializes, round-trips and passes the parse gate. An offset outside the legal range is invisible to every check in the system — the same shape as a relative IRI, or a date lexical form under an `xs:dateTime` datatype.

### The rename is the small half

**0 references.** No property anywhere points at a Proof instance, checked across the whole store, so the rename cannot break a reference. Each of the 24 records is alone in its own file, so retyping is 24 one-line edits.

**But `vad:Proof` was never one undeclared class — it is an undeclared sub-vocabulary of ten terms**, all `vad:`, none of them in the model:

`asset` · `assetOf` · `blockchain` · `created` · `dataHash` · `rootHash` · `service` · `sha256` · `timestamp` · `transaction`

So declaring `vad:ProofEvent` properly means declaring eleven terms and deciding what each asserts. One of those decisions needs the OriginStamp flow rather than the data: **`rootHash`, `dataHash` and `sha256` are three hashes** and the records show `sha256` equal to `dataHash` minus its `0x` prefix, with `rootHash` different — presumably the Merkle root the transaction commits to. Only someone who knows the service can say whether all three are worth keeping.

(`schema:description` is used on 12 of them, not a local `vad:description` — that term has zero triples and does not exist. Worth recording because it looked like a duplicate and is not.)

### `vad:assetOf` is kept, deliberately

The tempting consolidation was to widen `vad:hasArtwork`'s domain from `vad:Provenance` to `vad:ArtEvent` so every event subclass names the work it concerns through one edge, retiring `vad:assetOf`.

**Rejected by Rick, and the reasoning is about what the subject actually is.** A proof anchors an *asset* — maybe a JPEG, maybe a `.glb` — and reaches the work through it:

```turtle
work:3125376e a vad:ProofEvent ;
    vad:asset   <…/unmoored1.glb> ;
    vad:assetOf work:3c1955a5… .
```

Saying the proof `vad:hasArtwork` the work asserts the relationship a provenance asserts, which carries custody and ownership with it. The proof's object is the file; the work is what the file is *of*. `vad:assetOf` names that honestly and `vad:hasArtwork` would overstate it.

**The consequence, recorded so the query work is not surprised by it:** `ArtEvent` subclasses do not share one "the work this concerns" edge. A report answering *every event about work X* must union `vad:hasArtwork` and `vad:assetOf`, and each further subclass in §9 may add its own. That is the price of the distinction and it is a real one — but a wrong edge is more expensive than a union.

### A third ungated asset property

**`vad:asset` is not in `_ASSET_PROPERTIES`.** The asset gate watches `schema:image`, `vad:image3d`, `vad:qrcode` and `schema:contentUrl`, so these 24 references to real `.glb` and `.jpg` files are unchecked. All 24 resolve today; nothing would report it if one stopped.

This is the third instance of one pattern in two days — the document family was unarmed in `gate_baseline.py`, a zero-byte asset counted as resolved, and now an asset property nobody added to the set. **The gate's coverage is a hand-maintained list, and nothing tells anyone when a new file-valued property appears outside it.** A test that enumerates file-valued properties from the ontology and asserts each is either gated or deliberately excluded (as `schema:thumbnailUrl` already is, in a comment) would close the class rather than this instance. That belongs in `PROJECT_PLAN.md` rather than here.

**`vad:asset` joined `_ASSET_PROPERTIES` on 2026-10-31.** It is the asset reference that matters most of the five, because a proof's whole claim is about those exact bytes: a dangling one means the record attests to a file the system no longer holds. The class-level gap remains open in `PROJECT_PLAN.md` — this set is still a hand-kept list.

### Two facts about the model, established by verifying a real proof

**The batch invariant.** Proofs sharing a `vad:transaction` were anchored by one event, so they **must** share a `vad:rootHash` and a `vad:timestamp`. Across the 24 records: roots agreed in 10 of 10 batches, timestamps disagreed in two — and both disagreements were transcription errors. It is the cheapest validation rule available here and belongs in SHACL when the shapes are written.

**A proof record is not self-contained**, and should eventually be. The four stored values let a reader confirm that the file hashes to `vad:dataHash` and that the transaction commits to `vad:rootHash` — but **not that the one is inside the other.** That link is the Merkle path, and only OriginStamp has it: tested across all ten batches, the root is derivable from this project's own hashes in **zero** of them, because every batch held up to a couple of thousand other customers' leaves. Until the path is stored (the API item in `PROJECT_PLAN.md`), verification depends on the service continuing to exist, even though the blockchain record is permanent. A term for the path is a §14 item-2 decision.

`PROOF_WORKFLOW.md` carries how a proof gets MADE without anyone transcribing a value — the incipient record, the pending queue as a standing query, the two input adapters with the PDF scraper as the keyless baseline, and the three gates that make either adapter trustworthy. `PROOF_VERIFICATION.md` carries how a finished one is CHECKED, written for a reader ten years out with no context — including the one thing nobody can guess, that OriginStamp combines the **ASCII hex strings** rather than the raw digests, the opposite of Bitcoin's own tree.

### Checklist

1. Declare `vad:ProofEvent rdfs:subClassOf vad:ArtEvent`, with the `skos:historyNote`.
2. Decide the ten properties: which to keep, and what each asserts — the three hashes need the OriginStamp flow, not the data.
3. Declare the survivors, with domains that do not mistype a non-event subject (§12's lesson).
4. **Correct the 24 timestamps first** — +12 hours on every one, three offset fixes, and resolve the February pair at the source. The derivation cannot run before this, since it reads the date part.
5. **Remove `vad:created`** (11 of 24 precede their own event), and set `schema:startDate` to the date part of the corrected `vad:timestamp`, read in its own offset.
6. Retype the 24 records. One line each, each in its own file, nothing references them.
7. ~~Add `vad:asset` to `_ASSET_PROPERTIES` if it survives.~~ **DONE 2026-10-31**, with three tests, mutation-verified. The 25 staged records resolve 25 asset references with 0 absent, 0 malformed and 0 zero-byte.
8. Leave `vad:assetOf` alone, and leave `vad:hasArtwork rdfs:domain vad:Provenance` alone with it.
