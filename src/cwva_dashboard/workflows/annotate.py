"""Concept annotation consumers (the annotation algorithm notes): #6 Annotate Work and #15
Annotate Document Instances. Both call the shared TCAP algorithm
(:func:`concepts.tcap_navigation.annotate`); they differ only in how they gather
``(subject, concepts)`` — an interactive picker vs. batch tag files.

Common step (:func:`_place`): run TCAP over the RDFS-materialized store, write the
surviving typed properties into the subject's TTL, and record any tie in the
hygiene ledger (a vocabulary defect → workflow-panel open item, never surfaced
as data). The store loads the ontology + thesaurus (+ data) from the QA content.
"""

from __future__ import annotations

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SKOS

from ..concepts.ledger import LEDGER_PATH, HygieneLedger
from ..concepts.tcap_navigation import annotate as tcap_annotate
from ..concepts.tcap_navigation import materialize_rdfs
from ..promotion.layout import Layout, MIRROR_LAYOUT
from ..tools.base import Tool
from ..tools.record_tools import (SCHEMA, THE, VAD, art_form_names,
                                  bind_standard, work_namespace)

__all__ = [
    "annotate_work", "promote_markdown_tags", "build_annotate_tools",
    "list_annotatable", "list_concept_schemes", "annotation_scheme_filter",
    "ANNOTATION_CONFIG_TOPICS",
]

# Ontology + thesaurus + data — the RDFS-materialized store TCAP navigates.
DEFAULT_STORE_DIRS = ["metacontent/model", "metacontent/vocab", MIRROR_LAYOUT["work_ttl"]]


def _load_store(fileops, dirs, content_dirs=()) -> Graph:
    """The RDFS-materialized store TCAP navigates.

    Reads through the SHARED per-file cache. This used to re-read every file
    itself — model, vocabulary and data, ~390 fileops on the real store — and a
    single annotation blew the 600-ops-per-minute quota before it placed
    anything. Third occurrence of that bug, after the workflow panel and
    updateWorkOnSite; the cache was built for it each time.

    `_content_graph` returns a FRESH graph assembled from cached per-file
    parses, so materializing into it does not poison the cache for other
    callers.

    **The records are included for one reason only**, and `content_dirs` says
    which dirs are records so that reason can be honoured cheaply. Navigation
    needs a concept's EFFECTIVE types, and one source of those is usage: a
    concept is a `vad:WatercolorPaint` because some record says
    `vad:hasWatercolorPaint <it>`. Nothing else a record says can affect where a
    concept lands — the subject's own types are never consulted — so from a
    record dir only the triples POINTING AT a concept are loaded.

    Measured on the real store (2026-09-18): 24.3s to materialize the whole
    thing, 10.8s for this, and navigation agreed on all 311 concepts in use.
    The remaining cost is `owlrl` over the ontology and thesaurus, which is
    inherent to materializing before navigating rather than deriving the few
    types a selection needs.
    """
    from ..tools.workflow_tools import _content_graph

    reduce = {str(d) for d in content_dirs}
    g = Graph()
    for d in dirs:
        usage_only = str(d) in reduce
        for s, p, o in _content_graph(fileops, d):
            if usage_only and not (isinstance(o, URIRef) and str(o).startswith(str(THE))):
                continue
            g.add((s, p, o))
    materialize_rdfs(g)
    return g


def _load_ledger(fileops, ledger_path) -> HygieneLedger:
    try:
        text = fileops.read_text(ledger_path)
    except (FileNotFoundError, NotADirectoryError):
        text = ""
    return HygieneLedger.from_ttl(text)


def annotation_properties(model: Graph) -> set:
    """The predicates a concept can land on: an ``owl:ObjectProperty`` with an
    ``rdfs:range``, which is exactly what TCAP matches a concept's type against.

    `the:tag`, `the:topic` and `the:document` are all deliberately range-less in
    the thesaurus ("rdfs:range removed to avoid any implications"), so none of
    them is an annotation — which is right: a tag is the user's own text and may
    point at anything. 64 properties qualify in the real ontology.
    """
    return {p for p in model.subjects(RDF.type, OWL.ObjectProperty)
            if model.value(p, RDFS.range) is not None}


def placed_annotations(subj_graph: Graph, subject: URIRef, props) -> list:
    """The concept references on this record that the annotation editor owns.

    The first version asked the placement rule itself — "would navigating this
    concept produce this very predicate?" — which is exact and needs the
    RDFS-materialized store. That store costs **25 seconds** to build on Rick's
    data (measured 2026-09-18), and asking it merely to tick boxes made opening
    the page take sixteen (his report). The property test gives the same answer
    for anything TCAP placed, because TCAP can only ever place a ranged object
    property, and it is the same test Edit Record uses to decide that a field is
    an annotation — so the ticks and the discards cannot disagree.
    """
    return [(pred, obj)
            for pred, obj in subj_graph.predicate_objects(subject)
            if pred in props and isinstance(obj, URIRef)
            and str(obj).startswith(str(THE))]


def _place(fileops, store: Graph, subject: URIRef, concepts, subject_path,
           ledger_path, replace: bool = False, props=(), scope=None) -> dict:
    """Shared #6/#15 step: navigate, write typed properties onto the subject's
    TTL, record ties. Returns a report.

    ``replace`` makes the given concepts the WHOLE of the record's annotation
    (Rick, 2026-09-18): "only the currently selected concepts are applied …
    any previous concepts that were not in the current selection are
    discarded." That is #6's contract, because #6 shows the current selection
    and a user unticking a concept means it to go. #15 stays additive — it
    consumes one queue file at a time and knows nothing about what another one
    contributed.

    ``scope`` is what replacement is allowed to touch: the concepts the PICKER
    OFFERED. Outside it, "not in the selection" says nothing about intent —
    the user was never shown a box to leave ticked. Without this, narrowing the
    picker to a few schemes silently deleted every annotation from the others.
    """
    result = tcap_annotate(store, subject, concepts)

    # merge placed typed properties into the subject record (incipient if absent)
    subj_graph = Graph()
    try:
        subj_graph.parse(data=fileops.read_text(subject_path), format="turtle")
    except (FileNotFoundError, NotADirectoryError):
        pass
    discarded = []
    if replace:
        keep = {URIRef(c) for c in concepts}
        scope = None if scope is None else {URIRef(c) for c in scope}
        for pred, obj in placed_annotations(subj_graph, subject, props):
            if obj in keep:
                continue
            if scope is not None and obj not in scope:
                # NOT OFFERED, so it cannot have been unticked. Rick's record
                # lost `vad:hasPaper the:FabrianoArtisticoGranaFinaColdPress`
                # this way (2026-09-18): the paper is in `ArtMaterialScheme`,
                # the picker was narrowed to two other schemes, and replacement
                # treated "absent from the selection" as "removed by the user".
                # A concept the form never showed is a concept the user had no
                # ability to keep.
                continue
            subj_graph.remove((subject, pred, obj))
            discarded.append({"property": str(pred), "concept": str(obj)})
    for triple in result.placed:
        subj_graph.add(triple)
    bind_standard(subj_graph)
    fileops.write_text(subject_path, subj_graph.serialize(format="turtle"), make_parents=True)

    # ties -> hygiene ledger (open item for structural repair)
    if result.ties:
        ledger = _load_ledger(fileops, ledger_path)
        for tie in result.ties:
            ledger.record_tie(
                str(subject), str(tie.concept), [str(t[1]) for t in tie.candidates]
            )
        fileops.write_text(ledger_path, ledger.to_ttl(), make_parents=True)

    return {
        "subject": str(subject),
        "path": subject_path,
        "placed": [{"property": str(p), "concept": str(o)} for (_s, p, o) in result.placed],
        "discarded": discarded,
        "ties": [
            {"concept": str(t.concept), "candidates": sorted(str(x[1]) for x in t.candidates)}
            for t in result.ties
        ],
        "unmatched": [str(c) for c in result.unmatched],
    }


def annotate_work(
    fileops,
    subject: URIRef,
    concepts,
    *,
    store_dirs=None,
    subject_path,
    ledger_path=LEDGER_PATH,
    replace: bool = True,
    props=(),
    content_dirs=(),
    scope=None,
) -> dict:
    """#6 interactive: the work's annotation IS the picker's selection. Concepts
    are already expanded/filtered to the thesaurus by the tool wrapper.

    Replacing by default is what makes #6 an editor rather than an append-only
    form: the page shows what is on the record, so unticking one has to mean
    something. `replace=False` keeps the old additive behaviour for a caller
    that wants it.
    """
    store = _load_store(fileops, store_dirs or DEFAULT_STORE_DIRS,
                        content_dirs=content_dirs)
    return _place(fileops, store, subject, concepts, subject_path, ledger_path,
                  replace=replace, props=props or annotation_properties(store),
                  scope=scope)


def _already_annotated(inst, subject) -> bool:
    """Has this entity's concept placement already been done, by either path?

    The pre-DTS flag, or a DTS run that reached tagging curation. Two eras of
    the same fact, and a workflow that knew only the older one would re-place
    what DTS placed.
    """
    from ..dts.state import read_stamps

    if (subject, THE.conceptsExtracted, Literal(True)) in inst:
        return True
    return "taggingCurated" in read_stamps(inst, subject)


def promote_markdown_tags(
    fileops,
    *,
    queue_dir: str = "conceptQueue",
    data_dir: str = None,
    store_dirs=None,
    evidence_dir: str = "evidence",
    ledger_path: str = LEDGER_PATH,
    reannotate: bool = False,
) -> dict:
    """#15 batch: read ``the:tag`` from the conceptQueue tag files, group by
    subject, and place the shared TCAP typed properties on each instance.

    The pipeline's authority over ``the:tag`` extends **exactly to the queue
    files it consumes** (the annotation algorithm notes §5) — instance-file ``the:tag`` triples are
    never read here. Three additions over the Groovy:

    - **skip-if-done**: instances with ``conceptsExtracted true`` (the pre-DTS
      flag) or a DTS ``taggingCurated`` stamp are skipped;
      after processing the flag is flipped ``false → true``.
    - **evidence**: the consumed tags are preserved in the non-converged
      ``evidence/`` area (QA git, never pushed to SOT — §3.4); the tag TTL itself
      never reaches SOT, only the typed-property placements do.
    - **ties** land in the hygiene ledger (via the shared step).
    """
    data_dir = data_dir or MIRROR_LAYOUT["entity_ttl"]
    store = _load_store(fileops, store_dirs or DEFAULT_STORE_DIRS)

    # gather tags by subject from the queue files only
    tags_by_subject: dict = {}
    try:
        entries = fileops.list_dir(queue_dir)
    except (FileNotFoundError, NotADirectoryError):
        entries = []
    for e in entries:
        if not (e.is_file and e.name.endswith(".ttl")):
            continue
        tg = Graph().parse(data=fileops.read_text(f"{queue_dir}/{e.name}"), format="turtle")
        for subj, tag in tg.subject_objects(THE.tag):
            tags_by_subject.setdefault(subj, []).append(tag)

    processed: list = []
    skipped: list = []
    for subject, tags in tags_by_subject.items():
        guid = str(subject).rsplit("/", 1)[-1]
        subject_path = f"{data_dir}/{guid}.ttl"

        inst = Graph()
        try:
            inst.parse(data=fileops.read_text(subject_path), format="turtle")
        except (FileNotFoundError, NotADirectoryError):
            pass
        # SKIP-IF-DONE reads two things now. `the:conceptsExtracted true` is
        # the pre-DTS flag and still marks the 59 records that carry it; a
        # DTS-tagged entity has no flag at all, because `record.new_entity`
        # stopped writing one (2026-10-02). Reading only the flag would make
        # this workflow re-place concepts DTS had already placed.
        if not reannotate and _already_annotated(inst, subject):
            skipped.append(str(subject))
            continue

        report = _place(fileops, store, subject, tags, subject_path, ledger_path)

        # The flag is NOT written back. Flipping `false -> true` here would
        # reintroduce a deprecated predicate onto records that no longer carry
        # it, one at a time, by a workflow nobody associates with it. A
        # record's state is its DTS stamps; the flag is only ever read now, and
        # only for the legacy population.
        updated = Graph().parse(data=fileops.read_text(subject_path), format="turtle")
        if (subject, THE.conceptsExtracted, None) in updated:
            updated.remove((subject, THE.conceptsExtracted, None))
            updated.add((subject, THE.conceptsExtracted, Literal(True)))
            fileops.write_text(subject_path, updated.serialize(format="turtle"))

        # preserve consumed tags as curation evidence (non-converged)
        ev = Graph()
        for tag in tags:
            ev.add((subject, THE.tag, tag))
        ev_path = f"{evidence_dir.rstrip('/')}/{guid}.ttl"
        fileops.write_text(ev_path, ev.serialize(format="turtle"), make_parents=True)

        report["conceptsExtracted"] = True
        report["evidence"] = ev_path
        processed.append(report)

    return {"processed": processed, "skipped": skipped}


def _expand(term: str, work_ns) -> URIRef:
    if "://" in term:
        return URIRef(term)
    prefix, _, local = term.partition(":")
    if prefix == "the":
        return THE[local]
    if prefix == "work":
        return work_ns[local]
    raise ValueError(f"unknown prefix in {term!r}")


def list_annotatable(fileops, work_ns, data_dir: str, art_forms=None) -> list[dict]:
    """Works the picker offers: ``work:`` subjects typed as a ``vad:ArtForm``.

    A type test is what separates a WORK from an ENTITY — 240 and 136 of them in
    the real store, disjoint. Entities are annotated by the batch path (#15)
    from their queue tags, not by hand here, so offering them would invite a
    user to do #15's job one record at a time.

    The test was "carries any `vad:` type", which also admitted the artist and
    the artist profile once the bootstrap forms started writing them — both
    `vad:` typed, neither a thing anyone annotates. It is now the ontology's own
    answer: the downward closure of `vad:ArtForm` (Rick, 2026-09-18). With no
    model to ask, nothing is offered — see `art_form_names`.

    Reads the SHARED cached graph: annotation is reached from a page that also
    polls the workflow panel, and a private re-read of 240 records is how
    updateWorkOnSite blew the ops quota.
    """
    from ..tools.workflow_tools import _content_graph

    g = _content_graph(fileops, data_dir)
    out = []
    for subj in set(g.subjects(RDFS.label, None)):
        uri = str(subj)
        if not uri.startswith(str(work_ns)):
            continue
        types = {str(t).rsplit("/", 1)[-1].rsplit("#", 1)[-1]
                 for t in g.objects(subj, RDF.type)}
        if not (art_forms and types & art_forms):
            continue
        published = g.value(subj, SCHEMA.datePublished)
        out.append({
            "value": f"work:{uri[len(str(work_ns)):]}",
            "label": str(g.value(subj, RDFS.label)),
            # The picker's date order — the date the USER gave the work, not
            # when the sandbox last wrote the file (Rick, 2026-09-18).
            "published": str(published) if published else "",
        })
    return sorted(out, key=lambda d: (d["label"].lower(), d["value"]))


# The topics whose CONJUNCTION marks an Operation as configuring this workflow
# (Rick, 2026-09-10). Neither is a single-purpose marker — both are ordinary
# topics a person would reach for — and it is carrying both that means
# "dashboard / annotation". `the:Thesaurus` alone is worn by six Operations in
# the store, so the pair is doing real discriminating work.
#
# The alternative was a purpose-built concept like `the:annotationSchemes`,
# which would appear as a checkbox on the Entity form and mean nothing to anyone
# filling one in.
ANNOTATION_CONFIG_TOPICS = (THE.Thesaurus, THE.Annotation)


def annotation_scheme_filter(fileops, data_dir: str, vocab: Graph) -> dict:
    """Which ConceptSchemes the annotation picker should offer, per the store.

    **Configuration as DATA, not config.** The choice of schemes is curation: it
    belongs with the content, where it syncs between a workstation and a hosted
    instance and is editable through the Entity form — `dashboard.rson` does
    neither (CE_DESIGN §13.4a is the same argument from the other side).

    An Operation carrying BOTH marker topics contributes its `the:tag` values.
    Semantics chosen so the record can only ever narrow, never break:

    - **No such record → no filter.** The picker offers everything, which is
      what it did before this existed, so a fresh deployment needs no setup and
      absence can never silently empty the picker.
    - **Several records → the union of their tags.** Deterministic and additive;
      the page names which records contributed, so a surprising list has a
      visible cause. Picking "the most recent" would make the answer depend on a
      date nobody thinks of as load-bearing.
    - **A tag that is not a ConceptScheme is ignored and reported.** `the:tag` is
      general-purpose, so a record may legitimately carry tags meaning other
      things; silently treating one as a scheme would drop concepts with no
      explanation.
    """
    from ..tools.workflow_tools import _content_graph

    data = _content_graph(fileops, data_dir)
    allowed: set = set()
    sources: list = []
    not_schemes: list = []
    for subj in set(data.subjects(RDF.type, THE.Operation)):
        topics = set(data.objects(subj, THE.topic))
        if not all(t in topics for t in ANNOTATION_CONFIG_TOPICS):
            continue
        tags = set(data.objects(subj, THE.tag))
        if not tags:
            continue
        sources.append({
            "uri": str(subj),
            "label": str(data.value(subj, RDFS.label) or subj),
        })
        for t in tags:
            if (t, RDF.type, SKOS.ConceptScheme) in vocab:
                allowed.add(str(t))
            else:
                not_schemes.append(_curie(str(t)))
    return {
        "allowed": allowed,
        "sources": sorted(sources, key=lambda d: d["label"].lower()),
        "not_schemes": sorted(set(not_schemes)),
    }


def list_concept_schemes(fileops, store_dirs, data_dir: str | None = None) -> list[dict]:
    """Every ``skos:ConceptScheme`` that has concepts, each with its members.

    **All of them, not a curated few.** The Groovy filtered to six schemes named
    in the source; the store has 17 holding 856 concepts, so that list silently
    hid five schemes' worth of vocabulary from the picker — and it is exactly the
    kind of one-deployment constant that has no business in code. A deployer who
    wants fewer narrows it in config; the default hides nothing.
    """
    from ..tools.workflow_tools import _content_graph

    g = Graph()
    for d in store_dirs:
        for triple in _content_graph(fileops, d):
            g.add(triple)

    narrowing = (
        annotation_scheme_filter(fileops, data_dir, g) if data_dir
        else {"allowed": set(), "sources": [], "not_schemes": []}
    )
    allowed = narrowing["allowed"]

    schemes = []
    for scheme in set(g.subjects(RDF.type, SKOS.ConceptScheme)):
        if allowed and str(scheme) not in allowed:
            continue
        members = []
        for c in set(g.subjects(SKOS.inScheme, scheme)):
            label = g.value(c, RDFS.label) or g.value(c, SKOS.prefLabel)
            if label is None:
                continue
            members.append({"value": _curie(str(c)), "label": _picker_label(g, c, label)})
        if not members:
            continue
        schemes.append({
            "value": _curie(str(scheme)),
            "label": str(g.value(scheme, RDFS.label) or _curie(str(scheme))),
            "concepts": sorted(members, key=lambda d: d["label"].lower()),
        })
    return {
        "schemes": sorted(schemes, key=lambda d: d["label"].lower()),
        "narrowed_by": narrowing["sources"],
        "tags_not_schemes": narrowing["not_schemes"],
    }


def _picker_label(g: Graph, concept, label) -> str:
    """A concept's label, with its brand's abbreviation when it has a brand.

    `Ultramarine` is two different paints, `the:UltramarineDD` and
    `the:UltramarineLCS`, and four colours in the palette share a label this way.
    Two identical checkboxes cannot be told apart (Rick, 2026-11-05), so they read
    `Ultramarine (DD)` and `Ultramarine (LCS)`. Restores `AnnotateWork.groovy`'s
    `schema:brand/skos:altLabel`. Derived from the data, not a scheme name: a mixed
    colour has no brand and keeps its plain label.
    """
    brands = sorted(
        str(alt) for brand in g.objects(concept, SCHEMA.brand)
        for alt in g.objects(brand, SKOS.altLabel)
    )
    return f"{label} ({brands[0]})" if brands else str(label)


def _curie(uri: str) -> str:
    return uri.replace(str(THE), "the:") if uri.startswith(str(THE)) else uri


def build_annotate_tools(domain, *, layout=None, model=None) -> list[Tool]:
    """``layout`` is the active target's placement map (B1): TCAP reads the model
    and vocabulary from where the QA tree actually holds them, which differs per
    target (`metacontent/model` on disk, `ttl/model` on the bucket)."""
    lay = layout or Layout.default()
    store_dirs_default = [lay.dir("model_ttl"), lay.dir("vocab_ttl"), lay.dir("work_ttl")]
    entity_dir = lay.dir("entity_ttl")
    work_dir = lay.dir("work_ttl")
    work_ns = work_namespace(domain)
    art_forms = art_form_names(model)
    # Resolved once, at registry build. Ticking the current concepts used to
    # build the materialized store — 25 seconds on the real data — which is what
    # made opening the page take sixteen.
    annot_props = annotation_properties(model) if model is not None else set()

    def _annotate_work(fileops, subject, concepts, store_dirs=None, subject_path=None,
                       ledger_path=LEDGER_PATH, replace=True):
        subj = _expand(subject, work_ns)
        # interactive path filter (the annotation algorithm notes §3): only thesaurus concepts.
        cpts = [c for c in (_expand(x, work_ns) for x in concepts) if str(c).startswith(str(THE))]
        if subject_path is None:
            guid = str(subj).rsplit("/", 1)[-1]
            subject_path = f"{work_dir}/{guid}.ttl"
        return annotate_work(
            fileops, subj, cpts,
            store_dirs=store_dirs or store_dirs_default,
            subject_path=subject_path, ledger_path=ledger_path, replace=replace,
            props=_props(fileops, store_dirs), content_dirs=(work_dir,),
            scope=_offered(fileops) if replace else None,
        )

    def _offered(fileops, store_dirs=None, data_dir=None):
        """The concepts the PICKER can show — the scope replacement may touch.

        Derived from the same call the picker renders from, so the offered set
        and the replaceable set are one answer to one question. A second
        listing here would be a second answer, and the day they disagreed an
        annotation would vanish with nothing on screen to explain it. That is
        not hypothetical: it is the bug this exists to fix.
        """
        listing = list_concept_schemes(
            fileops,
            store_dirs or [lay.dir("vocab_ttl"), lay.dir("tags_ttl")],
            data_dir=data_dir or work_dir,
        )
        return {_expand(c["value"], work_ns)
                for s in listing["schemes"] for c in s["concepts"]}

    def _props(fileops, store_dirs=None):
        """The annotation predicates, from the model if the registry was built
        with one and from the store if it was not.

        The fallback is not a nicety. Ticking and discarding must agree: with an
        empty set the page would tick NOTHING and the submit would discard
        EVERYTHING, which is a data-loss trap wearing the shape of an empty
        form. Both paths ask this, so there is one answer.
        """
        if annot_props:
            return annot_props
        return annotation_properties(_load_store(
            fileops, store_dirs or store_dirs_default, content_dirs=(work_dir,)))

    def _current_annotations(fileops, subject, store_dirs=None, subject_path=None):
        """What is on the record now, as the picker's own concept values.

        The annotation page needs this to open TICKED — a form that edits by
        replacement and shows an empty selection is a form whose Annotate button
        clears the record.
        """
        subj = _expand(subject, work_ns)
        if subject_path is None:
            subject_path = f"{work_dir}/{str(subj).rsplit('/', 1)[-1]}.ttl"
        inst = Graph()
        try:
            inst.parse(data=fileops.read_text(subject_path), format="turtle")
        except (FileNotFoundError, NotADirectoryError):
            return {"concepts": []}
        current = {o for _p, o in placed_annotations(
            inst, subj, _props(fileops, store_dirs))}
        offered = _offered(fileops)
        return {
            "concepts": sorted(f"the:{str(o)[len(str(THE)):]}"
                               for o in current if o in offered),
            # On the record, outside the schemes this picker shows. It has no
            # checkbox, so it cannot be ticked — and for the same reason it is
            # never discarded. Reported so the page can say so rather than
            # leaving the user to wonder where a concept went.
            "outside": sorted(f"the:{str(o)[len(str(THE)):]}"
                              for o in current if o not in offered),
        }

    return [
        Tool(
            name="concept.list_annotatable",
            description=("Works available for annotation: work: subjects typed "
                         "as a vad:ArtForm subclass."),
            input_schema={
                "type": "object",
                "properties": {
                    "data_dir": {"type": "string", "description": "Records dir.", "default": work_dir},
                },
                "required": [],
                "additionalProperties": False,
            },
            handler=lambda fileops, data_dir=work_dir: {
                "works": list_annotatable(fileops, work_ns, data_dir, art_forms)
            },
        ),
        Tool(
            name="concept.list_concepts",
            description="Thesaurus concepts grouped by concept scheme, for the annotation picker.",
            input_schema={
                "type": "object",
                "properties": {
                    "store_dirs": {
                        "type": "array",
                        "description": "Vocabulary dirs to read.",
                        "items": {"type": "string"},
                    },
                    "data_dir": {
                        "type": "string",
                        "description": "Records dir, for the scheme-narrowing Operation.",
                        "default": work_dir,
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
            handler=lambda fileops, store_dirs=None, data_dir=work_dir: (
                list_concept_schemes(
                    fileops,
                    store_dirs or [lay.dir("vocab_ttl"), lay.dir("tags_ttl")],
                    data_dir=data_dir,
                )
            ),
        ),
        Tool(
            name="concept.annotate_work",
            description="Annotate a work with picked thesaurus concepts via TCAP — most-specific typed properties, ties recorded for vocabulary repair (inventory #6).",
            input_schema={
                "type": "object",
                "properties": {
                    "subject": {"type": "string", "description": "Work CURIE/IRI, e.g. work:<guid>."},
                    "concepts": {
                        "type": "array",
                        "description": "Chosen thesaurus concepts (the: CURIEs/IRIs).",
                        "items": {"type": "string"},
                    },
                    "store_dirs": {
                        "type": "array",
                        "description": "Dirs to load into the TCAP store (ontology/thesaurus/data).",
                        "items": {"type": "string"},
                    },
                    "subject_path": {"type": "string", "description": "Override the work TTL path."},
                    "ledger_path": {"type": "string", "description": "Hygiene ledger path.", "default": LEDGER_PATH},
                    "replace": {
                        "type": "boolean",
                        "description": ("The given concepts become the WHOLE of the "
                                        "work's annotation; ones not listed are "
                                        "discarded. Default true — #6 is an editor."),
                        "default": True,
                    },
                },
                "required": ["subject", "concepts"],
                "additionalProperties": False,
            },
            handler=_annotate_work,
        ),
        Tool(
            name="concept.current_annotations",
            description=("The thesaurus concepts currently annotating a work — the "
                         "ones TCAP itself placed, as picker values."),
            input_schema={
                "type": "object",
                "properties": {
                    "subject": {"type": "string", "description": "Work CURIE/IRI."},
                    "store_dirs": {
                        "type": "array",
                        "description": "Dirs to load into the TCAP store.",
                        "items": {"type": "string"},
                    },
                    "subject_path": {"type": "string", "description": "Override the work TTL path."},
                },
                "required": ["subject"],
                "additionalProperties": False,
            },
            handler=_current_annotations,
        ),
        Tool(
            name="concept.promote_markdown_tags",
            description="Promote conceptQueue the:tag scaffolding to TCAP typed properties on entity instances; skip conceptsExtracted-done, flip false->true, preserve tags as evidence (inventory #15).",
            input_schema={
                "type": "object",
                "properties": {
                    "queue_dir": {"type": "string", "description": "Tag-file source dir.", "default": "conceptQueue"},
                    "data_dir": {"type": "string", "description": "Instance TTL dir (mirror)."},
                    "store_dirs": {"type": "array", "description": "TCAP store dirs.", "items": {"type": "string"}},
                    "evidence_dir": {"type": "string", "description": "Non-converged evidence dir.", "default": "evidence"},
                    "ledger_path": {"type": "string", "description": "Hygiene ledger path.", "default": LEDGER_PATH},
                    "reannotate": {
                        "type": "boolean",
                        "description": "Re-process instances already conceptsExtracted-true.",
                        "default": False,
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
            handler=lambda fileops, **kw: promote_markdown_tags(
                fileops,
                **{"data_dir": entity_dir, "store_dirs": store_dirs_default} | kw,
            ),
        ),
    ]
