# CWVA Ontology Restructuring — VisualAnalysis Handoff

**Date:** 2026-03-16
**Purpose:** Document the ontology and thesaurus restructuring that introduced `vad:VisualAnalysis` and resolved a multiple-triple result issue in the TCAP SPARQL query.

---

## Background

This restructuring originated as a debugging exercise for the TCAP SPARQL query (see: *Most Specific Property Query Handoff*), which was returning two triples instead of one for concepts in the watercolor criticism branch of the thesaurus. The root cause was a false `skos:broader` relationship in the thesaurus (`the:Composition skos:broader the:Criticism`), which made `the:Criticism` a transitive ancestor of compositional concepts, causing the query to find both `vad:hasComposition` and `vad:hasCriticism` as candidates.

The fix was structural: correcting the thesaurus hierarchy rather than patching the query logic.

---

## The Problem

`the:CrowdHingeBand` had the following ancestor chain via `skos:broader+`:

```
the:CrowdHingeBand
  → the:HumanActivityFrieze
    → the:HorizontalFriezeBanding
      → the:SpatialCompositionStrategy
        → the:Composition        (typed as vad:Composition)
          → the:Criticism        (typed as vad:ArtCriticism)
```

Because `skos:broader+` is transitive, Branch 2 of the TCAP query reached `the:Criticism` and found `vad:ArtCriticism`, producing `vad:hasCriticism` as a candidate. Since `vad:Composition` and `vad:ArtCriticism` are in unrelated class branches, neither eliminated the other in the cross-branch filter, and both triples survived.

The false claim was that composition is a kind of (or falls within) criticism. In practice a critic *uses* compositional vocabulary, but compositional analysis is not a subtype of criticism — they are parallel analytical tools.

---

## Ontology Changes

### New Classes

```turtle
vad:VisualAnalysis
  rdf:type owl:Class ;
  rdfs:label "Visual Analysis" ;
  rdfs:subClassOf vad:VisualArts ;
  rdfs:comment "Analytical frameworks applied to the examination of visual artworks." ;
  .

vad:FormalAnalysis
  rdf:type owl:Class ;
  rdfs:label "Formal Analysis" ;
  rdfs:subClassOf vad:VisualAnalysis ;
  rdfs:comment "Analysis applied directly to the formal and visual elements of a work." ;
  .

vad:ContextualAnalysis
  rdf:type owl:Class ;
  rdfs:label "Contextual Analysis" ;
  rdfs:subClassOf vad:VisualAnalysis ;
  rdfs:comment "Analysis that situates a work within historical, cultural, or provenance contexts." ;
  .
```

### New Property

```turtle
vad:hasVisualAnalysis
  rdf:type owl:ObjectProperty ;
  rdfs:domain vad:CreativeWork ;
  rdfs:label "has visual analysis" ;
  rdfs:range vad:VisualAnalysis ;
  rdfs:comment "Links a work to a visual analysis concept." ;
  .
```

### Modified Classes

| Class | Previous Parent | New Parent |
|---|---|---|
| `vad:Composition` | `vad:Vocabulary` | `vad:FormalAnalysis` |
| `vad:ArtHistory` | `vad:Art` | `vad:ContextualAnalysis` |
| `vad:ArtElements` | `vad:Vocabulary` | `vad:FormalAnalysis` |
| `vad:ArtPrinciples` | `vad:Vocabulary` | `vad:FormalAnalysis` |
| `vad:Perspective` | `vad:Vocabulary` | `vad:FormalAnalysis` |

`vad:ArtCriticism` remains a child of `vad:ArtHistory` — criticism is historically situated practice and that relationship is unchanged.

`vad:Provenance` moves under `vad:ContextualAnalysis` as a sibling of `vad:ArtHistory`.

### Resulting Class Hierarchy

```
vad:Art
  vad:VisualArts
    vad:Vocabulary
      vad:DigitalLanguage
    vad:ArtRealization
    vad:VisualAnalysis
      vad:FormalAnalysis
        vad:ArtElements
        vad:ArtPrinciples
        vad:Composition
        vad:Perspective
      vad:ContextualAnalysis
        vad:ArtHistory
          vad:ArtCriticism
        vad:Provenance
```

### Notes on vad:Vocabulary

With `vad:ArtElements`, `vad:ArtPrinciples`, `vad:Composition`, and `vad:Perspective` moved to `vad:FormalAnalysis`, the only remaining child of `vad:Vocabulary` is `vad:DigitalLanguage`. This is intentional: `vad:Vocabulary` now corresponds directly to the thesaurus as a controlled vocabulary, a clean structural correspondence.

### Notes on FormalAnalysis vs ContextualAnalysis

The distinction between `vad:FormalAnalysis` (tools applied to the work's surface) and `vad:ContextualAnalysis` (frameworks that situate the work in the world) is noted for ontology readers but not operationally significant in current data usage. `vad:ContextualAnalysis` anticipates future classes such as `vad:CulturalContext` and `vad:Iconography` when needed.

---

## Thesaurus Changes

### New Concept

```turtle
# No new concept required — the:Interpretation already exists and
# plays the VisualAnalysis role as the thesaurus root for this branch.
```

`the:Interpretation` is annotated as `vad:VisualAnalysis`:

```turtle
the:Interpretation
  a skos:Concept, vad:VisualAnalysis ;
  rdfs:label "Interpretation" ;
  skos:definition "The process of analyzing a work of art and assigning it meaning." ;
  .
```

### Modified Concept

```turtle
# Before
the:Composition
  skos:broader the:Criticism .

# After
the:Composition
  skos:broader the:Interpretation .
```

### Resulting Thesaurus Structure (affected branch)

```
the:Interpretation          (vad:VisualAnalysis)
  the:Criticism             (vad:ArtCriticism)
  the:Composition           (vad:Composition)
    the:SpatialCompositionStrategy
      the:HorizontalFriezeBanding
        the:HumanActivityFrieze
          the:CrowdHingeBand
  the:Evaluation
  the:Assessment
  the:TechnicalAssessment
  the:Opinion
  the:GalleryDescription
  the:Influences
  the:InterpretationSource
    the:GoogleGemini
```

`the:Criticism` and `the:Composition` are now siblings under `the:Interpretation`. A critic uses compositional vocabulary but compositional analysis is not a subtype of criticism — the sibling relationship correctly models this.

---

## Why the Query Fix Is Structural

The TCAP query was behaving correctly given what the thesaurus asserted. Patching the query to add a proximity tie-breaker would have masked the modeling error rather than correcting it. With `the:Composition` no longer a descendant of `the:Criticism`, the transitive path via `skos:broader+` never reaches `the:Criticism` from compositional concepts, and `vad:hasCriticism` is never a candidate. The query returns a single triple as expected with no changes to query logic.

---

## Impact on Work Instance Data

The immediate trigger for this work was decorating the watercolor *Saint Mark's* instance with `vad:hasComposition` and `vad:hasCriticism` properties via the TCAP pipeline. On reflection, this was the wrong direction:

- **Compositional concepts as conscious creative choices** by the artist → appropriate on the work instance
- **Compositional and critical concepts as analytical observations** by a critic → appropriate on the criticism instance, not the work

For criticism instances, the preferred approach is `the:tag` (a symmetric `owl:ObjectProperty` with no domain/range constraints) to connect concepts to criticism instances. Tags are queryable and serve as facets without asserting ontological commitment. TCAP promotion of tags to typed properties on criticism instances remains a future possibility as the criticism data grows.

---

## Related Documents

- SPARQL Most Specific Property Query Handoff (TCAP query logic and test cases)
- Ontology: CWVA v4.x
- Thesaurus: interpretation.ttl, watercolor criticism concepts
- Transcript: `/mnt/transcripts/2026-02-17-15-55-16-ontology-v4-integration-media-disambiguation.txt`
