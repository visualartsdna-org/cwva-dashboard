# Most Specific Property Query - Handoff Document

**Date:** 2026-02-19  
**Purpose:** Document the SPARQL query that finds the most specific object property to link a work to a SKOS concept, based on ontology class hierarchies and thesaurus broader relationships.

---

## Problem Statement

Given:
- An ontology with a class hierarchy (e.g., `vad:Technique` → `vad:PaintingTechnique` → `vad:WatercolorTechnique`)
- Properties defined with ranges at various levels of specificity (e.g., `vad:hasTechnique`, `vad:hasWatercolorTechnique`)
- A SKOS thesaurus with concepts in `skos:broader` hierarchies
- Concepts optionally annotated with ontology classes at various levels
- RDFS reasoning enabled (which infers types from property usage)

**Challenge:** Automatically determine the most specific property to use when linking a work to a concept.

**Complications:**
1. RDFS reasoning infers types on concepts when they are used as property objects (e.g., if `work:X vad:hasTechnique the:wash` exists, then `the:wash a vad:Technique` is inferred)
2. Concepts may have explicit types or inherit them via `skos:broader`
3. Must handle both cases: concepts with direct type annotations and concepts that rely on broader ancestors for typing

---

## Final Working Query

```sparql
CONSTRUCT {
  ?w ?op ?cpt .
} WHERE {
  BIND ($workUri AS ?w)
  BIND ($cpt AS ?cpt)
  
  {
    # Branch 1: Direct types on the concept
    ?cpt a ?rt .
    FILTER (?rt NOT IN (skos:Concept, rdfs:Resource))
    ?op rdfs:range ?rt .
    
    # Exclude if there's a more specific class type WITH A MATCHING PROPERTY
    FILTER NOT EXISTS {
      ?rt2 rdfs:subClassOf+ ?rt .
      ?cpt a ?rt2 .
      FILTER (?rt2 != ?rt)
      ?op2 rdfs:range ?rt2 .
    }
  }
  UNION
  {
    # Branch 2: Types from broader concepts
    ?cpt skos:broader+ ?rtc .
    ?rtc a ?rt .
    FILTER (?rt NOT IN (skos:Concept, rdfs:Resource))
    ?op rdfs:range ?rt .
    
    # Exclude if there's a more specific class type WITH A MATCHING PROPERTY
    FILTER NOT EXISTS {
      ?rt2 rdfs:subClassOf+ ?rt .
      ?rtc a ?rt2 .
      FILTER (?rt2 != ?rt)
      ?op2 rdfs:range ?rt2 .
    }
    
    # Exclude if there's a closer broader concept with the SAME type
    FILTER NOT EXISTS {
      ?cpt skos:broader+ ?rtc2 .
      ?rtc2 skos:broader+ ?rtc .
      ?rtc2 a ?rt .
    }
  }
  
  # Final filter: exclude if there's a more specific property from either branch
  FILTER NOT EXISTS {
    {
      ?cpt a ?rtX .
      ?opX rdfs:range ?rtX .
      ?rtX rdfs:subClassOf+ ?rt .
      FILTER (?rtX != ?rt)
    }
    UNION
    {
      ?cpt skos:broader+ ?rtcX .
      ?rtcX a ?rtX .
      ?opX rdfs:range ?rtX .
      ?rtX rdfs:subClassOf+ ?rt .
      FILTER (?rtX != ?rt)
    }
  }
}
```

---

## How It Works

### Branch 1: Direct Types on the Concept

```sparql
{
  ?cpt a ?rt .
  FILTER (?rt NOT IN (skos:Concept, rdfs:Resource))
  ?op rdfs:range ?rt .
  
  FILTER NOT EXISTS {
    ?rt2 rdfs:subClassOf+ ?rt .
    ?cpt a ?rt2 .
    FILTER (?rt2 != ?rt)
    ?op2 rdfs:range ?rt2 .
  }
}
```

1. Finds all types of the concept (explicit and RDFS-inferred)
2. Excludes generic types (`skos:Concept`, `rdfs:Resource`)
3. Finds properties with matching range
4. **Class specificity filter:** Excludes a type if:
   - The concept has a more specific subclass type
   - AND that subclass type has a property with it as range

### Branch 2: Types from Broader Concepts

```sparql
{
  ?cpt skos:broader+ ?rtc .
  ?rtc a ?rt .
  FILTER (?rt NOT IN (skos:Concept, rdfs:Resource))
  ?op rdfs:range ?rt .
  
  FILTER NOT EXISTS {
    ?rt2 rdfs:subClassOf+ ?rt .
    ?rtc a ?rt2 .
    FILTER (?rt2 != ?rt)
    ?op2 rdfs:range ?rt2 .
  }
  
  FILTER NOT EXISTS {
    ?cpt skos:broader+ ?rtc2 .
    ?rtc2 skos:broader+ ?rtc .
    ?rtc2 a ?rt .
  }
}
```

1. Traverses `skos:broader+` (one or more steps) to find ancestor concepts
   - **Important:** Uses `+` not `*` to exclude the concept itself (avoids inferred types from property usage)
2. Gets types on broader concepts
3. Finds properties with matching range
4. **Class specificity filter:** Same as Branch 1, applied to the broader concept
5. **Concept proximity filter:** Excludes a broader concept if there's a closer concept (between `?cpt` and `?rtc`) with the same type

### Final Cross-Branch Filter

```sparql
FILTER NOT EXISTS {
  {
    ?cpt a ?rtX .
    ?opX rdfs:range ?rtX .
    ?rtX rdfs:subClassOf+ ?rt .
    FILTER (?rtX != ?rt)
  }
  UNION
  {
    ?cpt skos:broader+ ?rtcX .
    ?rtcX a ?rtX .
    ?opX rdfs:range ?rtX .
    ?rtX rdfs:subClassOf+ ?rt .
    FILTER (?rtX != ?rt)
  }
}
```

Compares results across both branches and excludes a result if there exists a more specific type (from either branch) that has a matching property.

---

## Key Design Decisions

### Why `skos:broader+` instead of `skos:broader*` in Branch 2?

Using `*` (zero or more) would include the concept itself, which has inferred types from RDFS reasoning when the concept has been used as a property object. Using `+` (one or more) excludes the concept itself and only looks at explicitly typed ancestor concepts.

### Why check for matching property in class specificity filters?

Early versions filtered out any type that had a more specific subclass. This caused problems when the more specific subclass existed but had no corresponding property defined. The filter now requires:
```sparql
?op2 rdfs:range ?rt2 .
```
This ensures we only exclude a type if there's actually a more specific property available.

### Why `FILTER (?rt2 != ?rt)` in subclass checks?

RDFS reasoning can make `rdfs:subClassOf+` reflexive (a class is a subclass of itself). This filter ensures we only consider strictly more specific types.

---

## Test Cases

### Test Case 1: Concept with Explicit Type

**Data:**
```turtle
the:AzureBlueLCS a skos:Concept, vad:WatercolorPaint ;
    skos:broader the:watercolorPaint .

vad:hasWatercolorPaint rdfs:range vad:WatercolorPaint .
vad:hasPaint rdfs:range vad:Paint .
```

**Expected Result:** `vad:hasWatercolorPaint the:AzureBlueLCS`

**Why:** Branch 1 finds `vad:WatercolorPaint` directly on the concept. The class specificity filter excludes `vad:Paint` because `vad:WatercolorPaint` is more specific and has a matching property.

---

### Test Case 2: Concept Inheriting Type via Broader (Specific Property Exists)

**Data:**
```turtle
the:wash a skos:Concept ;
    skos:broader the:watercolorTechnique .

the:watercolorTechnique a skos:Concept, vad:WatercolorTechnique ;
    skos:broader the:paintingTechnique .

the:paintingTechnique a skos:Concept, vad:PaintingTechnique .

vad:hasWatercolorTechnique rdfs:range vad:WatercolorTechnique .
vad:hasTechnique rdfs:range vad:Technique .
```

**Expected Result:** `vad:hasWatercolorTechnique the:wash`

**Why:** 
- Branch 1 finds `vad:Technique` (inferred from existing property usage)
- Branch 2 finds `vad:WatercolorTechnique` on `the:watercolorTechnique`
- Final filter excludes Branch 1 result because Branch 2 found a more specific type with a matching property

---

### Test Case 3: Concept Inheriting Type via Broader (Specific Property Does NOT Exist)

**Data:**
```turtle
the:wash a skos:Concept ;
    skos:broader the:watercolorTechnique .

the:watercolorTechnique a skos:Concept, vad:WatercolorTechnique ;
    skos:broader the:paintingTechnique .

# vad:hasWatercolorTechnique does NOT exist
vad:hasTechnique rdfs:range vad:Technique .
```

**Expected Result:** `vad:hasTechnique the:wash`

**Why:**
- Branch 1 finds `vad:Technique` with `vad:hasTechnique`
- Branch 2 finds `vad:WatercolorTechnique` but no property has this as range
- Only `vad:hasTechnique` survives as there's no more specific alternative

---

## Ontology/Thesaurus Design Pattern

### Ontology

Define properties with ranges at varying levels of specificity:

```turtle
vad:hasTechnique rdfs:range vad:Technique .
vad:hasPaintingTechnique rdfs:range vad:PaintingTechnique .
vad:hasWatercolorTechnique rdfs:range vad:WatercolorTechnique .

vad:hasMaterial rdfs:range vad:ArtMaterial .
vad:hasPaint rdfs:range vad:Paint .
vad:hasWatercolorPaint rdfs:range vad:WatercolorPaint .
```

### Thesaurus

Annotate concepts with ontology classes at appropriate levels in the hierarchy:

```turtle
the:technique a skos:Concept, vad:Technique .

the:paintingTechnique a skos:Concept, vad:PaintingTechnique ;
    skos:broader the:technique .

the:watercolorTechnique a skos:Concept, vad:WatercolorTechnique ;
    skos:broader the:paintingTechnique .

the:wash a skos:Concept ;
    skos:broader the:watercolorTechnique .

the:flatWash a skos:Concept ;
    skos:broader the:wash .
```

**Key Point:** Not every concept needs a class annotation. Concepts inherit types from their broader ancestors. The query automatically finds the nearest typed ancestor.

---

## Benefits

| Benefit | Description |
|---------|-------------|
| **Flexibility** | Not every concept needs a class annotation - it inherits from broader concepts |
| **Precision** | Concepts with explicit types get the most specific property |
| **Graceful fallback** | If a specific property doesn't exist, falls back to a more general one |
| **Maintainability** | Add new specific properties to the ontology without changing existing data |
| **Consistency** | Same query works across all concept types and hierarchy depths |

---

## Performance Notes

Several query variations were tested and found to be inefficient (>1 minute execution time):

1. Using `skos:broader*` combined with `NOT EXISTS` containing another `skos:broader*`
2. Checking `?anySubject ?op ?rtc` to detect inferred types
3. Complex nested path expressions

The final query uses efficient patterns:
- Single `skos:broader+` traversals
- `NOT EXISTS` with simple triple patterns
- UNION to combine branches rather than complex conditionals

---

## Debugging Tips

If the query returns unexpected results, use this diagnostic query to see what each branch produces:

```sparql
SELECT ?rt ?op ?source ?rtc
WHERE {
  BIND (the:yourConcept AS ?cpt)
  
  {
    ?cpt a ?rt .
    FILTER (?rt NOT IN (skos:Concept, rdfs:Resource))
    ?op rdfs:range ?rt .
    BIND ("self" AS ?source)
    BIND (?cpt AS ?rtc)
  }
  UNION
  {
    ?cpt skos:broader+ ?rtc .
    ?rtc a ?rt .
    FILTER (?rt NOT IN (skos:Concept, rdfs:Resource))
    ?op rdfs:range ?rt .
    BIND ("broader" AS ?source)
  }
}
```

---

## Related Files

- Ontology: CWVA v4.0.0 with class hierarchies under `vad:ArtProduction`
- Thesaurus: SKOS concepts with `skos:broader` relationships and ontology class annotations

---

## Transcript Reference

Full development conversation: `/mnt/transcripts/2026-02-17-15-55-16-ontology-v4-integration-media-disambiguation.txt`
