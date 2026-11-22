"""Validation gates — certify conformance, not intent (CE_DESIGN §3.2, §3.5).

Three gates, run in order:

1. **parse** — every TTL compiles (syntactic correctness), attributed per file.
2. **SHACL** — the data graph conforms to the shapes (content completeness,
   referential integrity).
3. **SPARQL assertions** — ASK/SELECT queries whose expected result is fixed
   (e.g. "no work lacks a title" as an ASK that must be false, or a SELECT of
   violations that must be empty).

Gates return :class:`GateResult` objects that attach to the promotion unit.
They never police *intent* — that is the user's job via the browser + prompt
(§3.5). A gate asserts structure/semantics, never that the medium field says
what the user meant.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from rdflib import Graph, URIRef

from .. import referents as _referents
from ..sandbox.pointers import (
    DEFAULT_GIT_CONTENT_EXTENSIONS,
    Pointer,
    is_managed_binary,
    pointer_path_of,
    sha256_file,
)
from .unit import GateResult

__all__ = [
    "Assertion",
    "load_graph",
    "parse_gate",
    "shacl_gate",
    "provenance_gate",
    "sparql_assertions_gate",
    "pointer_gate",
    "asset_reference_gate",
    "vocabulary_reference_gate",
    "rdf_format",
]

# Asset-reference predicates: their object is meant to be an image asset under
# the instance's image base. Fixed commons namespaces (§13), so constant here.
_SCHEMA_IMAGE = URIRef("https://schema.org/image")
_VAD_IMAGE3D = URIRef("http://visualartsdna.org/model/image3d")
_VAD_QRCODE = URIRef("http://visualartsdna.org/model/qrcode")
# schema:contentUrl — the MP4 inside a schema:video VideoObject. Gated because
# the dashboard really does ingest that file, so a dangling one is the same
# defect as a dangling schema:image.
#
# **Only inside a VideoObject, though.** Seven records in the real store use
# schema:contentUrl on the WORK itself to name the site page the work appears on
# (`https://www.art.visualartsdna.org/`) — a perfectly good use of the property that is
# not a file reference at all. Gating the property unconditionally, as this did
# when it was added, would fail the asset gate on all seven the moment one was
# promoted. The property does not carry the meaning; the subject does.
_SCHEMA_CONTENT_URL = URIRef("https://schema.org/contentUrl")
_SCHEMA_VIDEOOBJECT = URIRef("https://schema.org/VideoObject")
# vad:asset — the file a vad:ProofEvent anchored, a .jpg or a .glb under the
# image base. Added 2026-10-31, having been missed since the proof records were
# written: 24 references to real files that no gate looked at. It is the asset
# reference that matters MOST, because the proof's whole claim is about those
# exact bytes — a dangling one means the record attests to a file the system no
# longer has.
#
# Found by adding the zero-byte class and watching it report nothing, which is
# the third instance of one pattern: this set is a hand-kept list, and nothing
# announces a new file-valued property that is not in it. See PROJECT_PLAN for
# the test that would close the class rather than this instance.
_VAD_ASSET = URIRef("http://visualartsdna.org/model/asset")

#: The shared commons: the model and the thesaurus. Their terms never derive
#: from a deployer's domain (CE_DESIGN §13), and neither do the images they
#: cite (a paint's swatch, from the reference thesaurus). Those belong to
#: whoever publishes the commons, so a collection is not required to hold them
#: (2026-11-21: the first distribution of the reference vocabulary, 64 swatch
#: images, could otherwise never pass).
_COMMONS = ("http://visualartsdna.org/model/", "http://visualartsdna.org/thesaurus/")
_ASSET_PROPERTIES = frozenset(
    {_SCHEMA_IMAGE, _VAD_IMAGE3D, _VAD_QRCODE, _SCHEMA_CONTENT_URL, _VAD_ASSET}
)
# property -> a type its SUBJECT must carry for the reference to be an asset
# reference at all. Absent from this map means "always an asset reference".
_ASSET_SUBJECT_TYPE = {_SCHEMA_CONTENT_URL: _SCHEMA_VIDEOOBJECT}

# DELIBERATELY NOT GATED: schema:thumbnailUrl.
#
# The video thumbnail is named by convention but RENDERED BY cwva-py on demand
# when the video first loads — no part of this system creates it, so at
# promotion time it correctly does not exist. Gating it would fail every video
# entry forever, and the only ways to "fix" that failure are to weaken the gate
# or to have the dashboard fabricate a file that is not its to make. It is
# recorded here so a later reader sees an omission that was decided rather than
# one that was missed. (Its shape is still covered: the URL is derived, not
# typed, so it cannot be malformed independently of contentUrl.)
_SCHEMA_THUMBNAIL_URL = URIRef("https://schema.org/thumbnailUrl")

# Document references (the entity form): the:mdDocument / the:pdfDocument. Same
# defect as a dangling image — the dashboard ingests these files from the drop
# folder, so a reference that does not resolve means the record reaches SOT
# naming a document that never converged.
#
# They need their OWN base and dir (documents are not under the image base), and
# they must NOT require `is_managed_binary`: `.md` is ordinary git content under
# the inverted policy, so it is present as a real file with no sidecar, while a
# `.pdf` is pointer-managed and present as a sidecar. Requiring "managed" would
# report every markdown reference as malformed.
_VAD_HAS_ARTWORK = URIRef("http://visualartsdna.org/model/hasArtwork")
_VAD_DI = URIRef("http://visualartsdna.org/model/dispositionId")
_VAD_ITEM = URIRef("http://visualartsdna.org/model/itemId")
_THE_MD_DOCUMENT = URIRef("http://visualartsdna.org/thesaurus/mdDocument")
_THE_PDF_DOCUMENT = URIRef("http://visualartsdna.org/thesaurus/pdfDocument")
_DOCUMENT_PROPERTIES = frozenset({_THE_MD_DOCUMENT, _THE_PDF_DOCUMENT})

# Vocabulary-reference properties → the (predicate, object) conditions their
# object must ALL satisfy to be a declared, valid referent.
#
# **Defined in `referents.py`, not here.** The picker's query and this gate's
# requirement are the two halves of "what the form offers is what the system
# enforces", and they used to be two hand-kept tables that agreed only by
# comment. Now there is one table and no agreement to maintain.
#
# `vad:background` is included as of 2026-09: it points at a content record
# rather than a thesaurus concept, so checking it means loading `content_dirs`
# — see the gate. It was previously skipped as an undefined "work: cross-
# reference"; a background now has a definite shape (`a the:Image` with
# `the:topic the:Background`), which makes it the same two-condition test as
# any other referent.
_RDF_TYPE = URIRef("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")
_VOCABULARY_REQUIREMENTS = _referents.REQUIREMENTS

# Turtle-family extensions we parse; the format is inferred per file.
_RDF_FORMATS = {
    ".ttl": "turtle",
    ".turtle": "turtle",
    ".nt": "nt",
    ".n3": "n3",
    ".trig": "trig",
    ".jsonld": "json-ld",
    ".rdf": "xml",
    ".xml": "xml",
}


def rdf_format(path) -> str | None:
    """The rdflib format for a path's extension, or None if it is not RDF."""
    return _RDF_FORMATS.get(Path(path).suffix.lower())


def _rdf_paths(paths) -> list[Path]:
    return [Path(p) for p in paths if Path(p).suffix.lower() in _RDF_FORMATS]


def load_graph(paths, *, into: Graph | None = None) -> Graph:
    """Parse the given RDF files into a single graph. Raises on the first parse
    error (use :func:`parse_gate` to collect errors per file instead)."""
    g = into if into is not None else Graph()
    for p in _rdf_paths(paths):
        g.parse(str(p), format=_RDF_FORMATS[Path(p).suffix.lower()])
    return g


def parse_gate(paths) -> GateResult:
    """Gate 1: every RDF file parses. Errors are attributed to their file so
    the agent can point the user at the offender."""
    rdf = _rdf_paths(paths)
    messages: list[str] = []
    bad: list[str] = []
    for p in rdf:
        try:
            Graph().parse(str(p), format=_RDF_FORMATS[p.suffix.lower()])
        except Exception as exc:  # rdflib raises a variety of parse errors
            bad.append(str(p))
            messages.append(f"{p}: {type(exc).__name__}: {exc}")
    ok = not bad
    summary = (
        f"parsed {len(rdf)} RDF file(s)"
        if ok
        else f"{len(bad)} of {len(rdf)} RDF file(s) failed to parse"
    )
    return GateResult(
        name="parse", ok=ok, summary=summary, messages=messages, details={"files": len(rdf)}
    )


def shacl_gate(data: Graph, shapes: Graph, *, inference: str = "none") -> GateResult:
    """Gate 2: SHACL conformance. Imported lazily so non-gate code paths do not
    pay pyshacl's import cost."""
    from pyshacl import validate

    conforms, _results_graph, results_text = validate(
        data,
        shacl_graph=shapes,
        inference=inference,
        advanced=True,
        meta_shacl=False,
        js=False,
        debug=False,
    )
    messages = [] if conforms else [ln for ln in results_text.splitlines() if ln.strip()]
    summary = "conforms to SHACL shapes" if conforms else "SHACL violations present"
    return GateResult(
        name="shacl", ok=bool(conforms), summary=summary, messages=messages
    )


@dataclass(frozen=True)
class Assertion:
    """A SPARQL conformance check. ``expect`` is one of:

    - ``"empty"`` / ``"nonempty"`` — SELECT/CONSTRUCT row presence.
    - ``"true"`` / ``"false"`` — ASK result.

    The natural pattern is a SELECT of violations expected ``empty``, or an ASK
    of a required condition expected ``true``.
    """

    name: str
    query: str
    expect: str = "empty"


def _assertion_holds(g: Graph, a: Assertion) -> tuple[bool, str]:
    result = g.query(a.query)
    if a.expect in ("true", "false"):
        got = bool(result.askAnswer)
        want = a.expect == "true"
        return got == want, f"ASK={got}, expected {want}"
    rows = list(result)
    n = len(rows)
    if a.expect == "empty":
        return n == 0, f"{n} row(s), expected 0"
    if a.expect == "nonempty":
        return n > 0, f"{n} row(s), expected >=1"
    raise ValueError(f"unknown expect {a.expect!r} in assertion {a.name!r}")


def sparql_assertions_gate(data: Graph, assertions) -> GateResult:
    """Gate 3: each assertion's result matches its expectation."""
    assertions = list(assertions)
    messages: list[str] = []
    failed = 0
    for a in assertions:
        try:
            holds, detail = _assertion_holds(data, a)
        except Exception as exc:
            holds, detail = False, f"{type(exc).__name__}: {exc}"
        if not holds:
            failed += 1
            messages.append(f"{a.name}: {detail}")
    ok = failed == 0
    summary = (
        f"{len(assertions)} SPARQL assertion(s) held"
        if ok
        else f"{failed} of {len(assertions)} SPARQL assertion(s) failed"
    )
    return GateResult(name="sparql", ok=ok, summary=summary, messages=messages)


def pointer_gate(
    content_root,
    manifest,
    *,
    git_content: frozenset[str] = DEFAULT_GIT_CONTENT_EXTENSIONS,
) -> GateResult:
    """Gate 4: every managed binary in the manifest matches its ``.ptr`` sidecar.

    The manifest translation (``binaries.content_manifest``) turns a changed
    ``<x>.ptr`` into a push of ``<x>``, trusting fileops to have kept the two in
    lockstep. That invariant was previously assumed everywhere and verified
    nowhere. This gate checks it at the single gated exit, where law 1 puts the
    check — recomputing sha256 for the manifest's paths only, not the tree.

    It **fails, it does not repair**. Divergence at the exit is a fault, not
    something to heal: healing belongs to ``reconcile()`` (rollback, pointer is
    truth) and ``rebuild_sidecars()`` (sync, binary is truth), on the paths where
    each direction is correct. With sidecars denied at Layer 1 a mismatch here
    should be unreachable through the tool surface, which is what makes it worth
    keeping — it now signals something genuinely anomalous rather than routine
    drift, and it guards the *next* way a sidecar goes stale.
    """
    root = Path(content_root)
    checked = 0
    messages: list[str] = []

    # Deletes are not checked: the binary is meant to be gone.
    for rel in sorted(set(manifest.adds) | set(manifest.modifies)):
        if not is_managed_binary(rel, git_content):
            continue
        binary = root / rel
        sidecar = pointer_path_of(binary)
        if not binary.exists():
            messages.append(f"{rel}: binary missing")
            continue
        if not sidecar.exists():
            messages.append(f"{rel}: no .ptr sidecar")
            continue
        try:
            want = Pointer.from_json(sidecar.read_text())
        except Exception as exc:
            messages.append(f"{rel}: unreadable sidecar ({type(exc).__name__})")
            continue
        actual, size = sha256_file(binary)
        checked += 1
        if actual != want.sha256:
            messages.append(f"{rel}: sha256 {actual[:12]}… != sidecar {want.sha256[:12]}…")
        elif size != want.size:
            messages.append(f"{rel}: size {size} != sidecar {want.size}")

    ok = not messages
    summary = (
        f"{checked} binary/binaries match their sidecar"
        if ok
        else f"{len(messages)} pointer inconsistency/inconsistencies"
    )
    return GateResult(name="pointer", ok=ok, summary=summary, messages=messages)


def _asset_bytes(asset: Path) -> int | None:
    """The asset's size, read from whichever artifact is actually present.

    The real file when it is there; otherwise the ``.ptr`` sidecar's recorded
    ``size``, because a pointer-managed binary is gitignored and the sidecar is
    all a target carries. ``None`` when neither can answer — a malformed or
    unreadable sidecar is the parse gate's business, not this one, and must not
    be reported here as an empty asset.
    """
    try:
        if asset.exists():
            return asset.stat().st_size
        ptr = pointer_path_of(asset)
        if ptr.exists():
            return int(json.loads(ptr.read_text())["size"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return None


def asset_reference_gate(
    graph: Graph,
    content_root,
    *,
    image_base: str,
    image_dir: str,
    document_base: str | None = None,
    document_dir: str | None = None,
    git_content: frozenset[str] = DEFAULT_GIT_CONTENT_EXTENSIONS,
    require_present: bool = True,
) -> GateResult:
    """Gate 5: every asset reference in ``graph`` resolves to a file present in
    the target — the image family (`schema:image`, `vad:image3d`, `vad:qrcode`,
    `schema:contentUrl`) and, when armed with a documents base/dir, the document
    family (`the:mdDocument`, `the:pdfDocument`).

    **"Present" means the reference resolves to a managed asset — a real file OR
    a `.ptr` sidecar (the tracked artifact for a pointer-managed binary) — never
    ``os.path.exists(<image path>)``.** Under the inverted binary policy the
    image itself is gitignored and the sidecar is what git tracks, so a naive
    file-exists check passes fixtures (real file staged) and fails on real
    pointer-managed content (only the sidecar present) — the intersection with
    the binary work, and the seam that fails on real content if gotten wrong.

    Findings are split into two classes, kept separate in ``details`` so one
    class never drowns the other (the shadow's first sync produces ~200 *absent*
    image refs because no images were cloned; a single *malformed* one must stay
    visible):

    - **malformed** — the object is not a well-formed ``{image_base}<name>``
      image reference (a bare filename, wrong host, non-image value). A data-
      *shape* defect, independent of what assets happen to be present. This is
      how the qrcode base-join bug (``URIRef("qrc_x.jpg")`` with no image-base
      join) surfaces. **Always fails the gate.**
    - **absent** — a well-formed reference whose asset is not present as a
      managed asset. A real dangling reference in normal operation
      (``require_present=True``, fails); the *expected known-partial* class when
      scanning an intentionally partial copy like the image-less shadow
      (``require_present=False``, reported but not fatal — see PROJECT_PLAN 4.6
      §5 first-sync checkpoint).
    - **empty** — a reference that resolves to a **zero-byte** asset. Added
      2026-10-29, because "resolves" meant "exists" and an empty file exists:
      `documents/CupsStudyCriticism.pdf` sat in production cited by
      `work:552759c6…` while the baseline read *504 resolved, 0 absent, 0
      malformed*. The only thing that noticed was `verify_shadow.py`, and only
      because someone hand-declared a ``known:`` for that one file.
      **REPORTED, NOT FATAL.** The known instance is in current content, so
      failing on it would stop every promotion until the record is fixed — a new
      gate class that halts work is the "weaken a gate to make a workflow pass"
      trap running backwards. Once that record is cleaned this becomes one line:
      add ``empty`` to ``fatal`` beside ``absent``.
      Size comes from the ``.ptr`` sidecar when the real bytes are absent, never
      from ``stat()`` on the asset path — under the inverted binary policy the
      binary is gitignored and the sidecar is the tracked artifact, so a
      ``stat()`` here would be the same naive mistake the presence check above
      exists to avoid.
    """
    root = Path(content_root)
    malformed: list[str] = []
    absent: list[str] = []
    empty: list[str] = []
    external: list[str] = []
    resolved = 0

    # (properties, base, dir, must-be-a-managed-binary). Documents join the
    # image family as a second group rather than more properties in the first:
    # they resolve against a different base and a different managed-ness rule.
    families = [(_ASSET_PROPERTIES, image_base, image_dir, True)]
    if document_base and document_dir:
        families.append((_DOCUMENT_PROPERTIES, document_base, document_dir, False))

    for _s, p, o in graph:
        family = next((f for f in families if p in f[0]), None)
        if family is None:
            continue
        # Context-dependent properties: schema:contentUrl is a file reference in
        # a VideoObject and a site link on a work. Wrong subject -> not ours.
        need_type = _ASSET_SUBJECT_TYPE.get(p)
        if need_type is not None and (_s, _RDF_TYPE, need_type) not in graph:
            continue
        _props, base, subdir, managed_only = family
        v = str(o)
        if str(_s).startswith(_COMMONS):
            # a commons term's image: counted if this collection has it,
            # reported otherwise, never required (see _COMMONS)
            name = v[len(base):] if v.startswith(base) else ""
            asset = root / subdir / name if name else None
            if asset is not None and (asset.exists() or pointer_path_of(asset).exists()):
                resolved += 1
            else:
                external.append(f"{p.split('/')[-1]} → {v}")
            continue
        # well-formed = under this family's base (and, for images, naming a
        # managed asset rather than some other kind of file)
        if v.startswith(base):
            name = v[len(base):]
            if name and (not managed_only or is_managed_binary(name, git_content)):
                asset = root / subdir / name
                if asset.exists() or pointer_path_of(asset).exists():
                    resolved += 1
                    if _asset_bytes(asset) == 0:
                        empty.append(f"{p.split('/')[-1]} → {name}")
                else:
                    absent.append(f"{p.split('/')[-1]} → {name}")
                continue
        malformed.append(f"{p.split('/')[-1]} → {v}")

    fatal = list(malformed)
    if require_present:
        fatal += absent
    ok = not fatal
    if ok:
        summary = f"{resolved} asset reference(s) resolve" + (
            f"; {len(absent)} absent (reported, not required)" if absent else ""
        ) + (
            # Named in the SUMMARY rather than only in details: a non-fatal
            # finding nobody reads is not a finding.
            f"; {len(empty)} ZERO-BYTE (reported, not required)" if empty else ""
        ) + (
            f"; {len(external)} cited by the shared model or thesaurus and not held "
            "here (reported, not required)" if external else ""
        )
    else:
        parts = []
        if malformed:
            parts.append(f"{len(malformed)} malformed")
        if require_present and absent:
            parts.append(f"{len(absent)} dangling")
        summary = f"{' + '.join(parts)} asset reference(s)"
    return GateResult(
        name="asset_reference",
        ok=ok,
        summary=summary,
        messages=fatal,
        details={"malformed": malformed, "absent": absent, "empty": empty,
                 "external": external, "resolved": resolved},
    )


def provenance_gate(data: Graph, qa_root, provenance_dir: str,
                    content_dirs=()) -> GateResult:
    """Provenance records being promoted, judged against the whole tree.

    What SHACL cannot see from one record (PROVENANCE_PLAN.md §5): an item id or
    DI used twice, a work with two incipient records, an item id disagreeing with
    its DI. And `vad:hasArtwork` must resolve: validating the 2026-11-02 backfill
    against production caught three records that would have shipped a dangling
    artwork, and only because someone checked by hand.

    Only records in this unit are judged, so old data cannot block new work.
    """
    subjects = [s for s in set(data.subjects(_VAD_HAS_ARTWORK, None))]
    if not subjects:
        return GateResult(name="provenance", ok=True, summary="no provenance in this unit")

    root = Path(qa_root)
    tree = Graph()
    for path in sorted((root / provenance_dir.strip("/")).glob("*.ttl")):
        tree.parse(str(path), format="turtle")

    def in_store(work) -> bool:
        # A record's file is named for its guid. A miss is then confirmed by
        # reading, since an aggregate can still hold a subject under another name.
        guid = str(work).rsplit("/", 1)[-1]
        if (work, None, None) in data or any(
                (root / d.strip("/") / f"{guid}.ttl").is_file() for d in content_dirs):
            return True
        for folder in content_dirs:
            for path in (root / folder.strip("/")).glob("*.ttl"):
                g = Graph()
                g.parse(str(path), format="turtle")
                if (work, None, None) in g:
                    return True
        return False

    messages = []
    for s in sorted(subjects, key=str):
        di, item = tree.value(s, _VAD_DI), tree.value(s, _VAD_ITEM)
        if (di is None) != (item is None):
            messages.append(f"{s}: a DI and an item id come together or not at all")
        if di is not None and item is not None:
            if str(di).rsplit(".", 1)[-1] != str(item):
                messages.append(f"{s}: item id {item} is not the end of DI {di}")
            for prop, value, name in ((_VAD_ITEM, item, "item id"), (_VAD_DI, di, "DI")):
                others = sorted(str(o) for o in tree.subjects(prop, value) if o != s)
                if others:
                    messages.append(f"{s}: {name} {value} is also on {', '.join(others)}")
            for work in tree.objects(s, _VAD_HAS_ARTWORK):
                rivals = sorted(str(o) for o in tree.subjects(_VAD_HAS_ARTWORK, work)
                                if o != s and (o, _VAD_DI, None) in tree)
                if rivals:
                    messages.append(f"{s}: {work} already has an incipient provenance: "
                                    f"{', '.join(rivals)}")
        if content_dirs:
            for work in tree.objects(s, _VAD_HAS_ARTWORK):
                if not in_store(work):
                    messages.append(f"{s}: its artwork {work} is not in the store")
    return GateResult(
        name="provenance", ok=not messages,
        summary=(f"{len(subjects)} provenance record(s) consistent with the tree"
                 if not messages else "provenance records conflict"),
        messages=messages,
    )


def vocabulary_reference_gate(
    data: Graph,
    qa_root,
    vocab_dirs,
    *,
    requirements: dict = _VOCABULARY_REQUIREMENTS,
    content_dirs=None,
) -> GateResult:
    """Gate 6: every vocabulary reference in the promoted RDF points at a
    declared concept satisfying **all** of that property's required conditions.

    ``requirements`` maps each checked property to a list of ``(predicate,
    object)`` the referent must all carry, matching that field's entry picker
    exactly (Q5): ``vad:hasPaper → [(rdf:type, vad:WatercolorPaper)]`` and
    ``the:topic → [(rdf:type, skos:Concept), (skos:inScheme, the:TopicScheme)]``.
    So a concept that is not actually a paper, or a concept not in the topic
    scheme, cannot slip in — enforcement is exactly what the picker offered.

    Referential integrity of a vocabulary reference is a **graph** fact (does the
    referent exist and carry the required type), unlike asset presence which is a
    filesystem fact — so this is a graph check (a SELECT of violations), not a
    filesystem check and not SHACL.

    **The reference graph must be loaded, or the gate is worse than useless.**
    The vocabulary lives in the QA tree (``vocab_dirs``), NOT in a work-entry's
    promotion manifest, so a naive check over the manifest alone would report
    *every* reference as dangling (nothing in the manifest types the concept).
    This gate loads ``vocab_dirs`` from ``qa_root`` and unions them with the
    manifest graph before checking — that loading is the whole point, and a test
    pins that omitting it turns every reference into a false positive.

    Cheap and conditional in two directions: if the manifest names no checked
    property, nothing is loaded at all; and each referent declares its SOURCE,
    so a manifest referencing only concepts never parses the record store.
    ``content_dirs`` is what `vad:background` needs — a background is an entity
    record, not a thesaurus concept — and if it is not supplied while a
    background is referenced, the referent cannot be found and the reference
    reports as dangling. That failure is loud by design: an unarmed gate that
    refuses everything gets fixed, while one that silently passes does not.
    """
    root = Path(qa_root)
    # Only pay for vocab loading if the manifest actually references a concept.
    referencing = [
        (s, p, o)
        for p in requirements
        for s, _, o in data.triples((None, p, None))
    ]
    if not referencing:
        return GateResult(
            name="vocabulary_reference", ok=True, summary="no vocabulary references",
            details={"dangling": [], "resolved": 0},
        )

    # Which stores hold the referents actually referenced here? A referent may
    # be a thesaurus concept (metacontent) or a content record (`vad:background`
    # is an entity, not a concept). Loading is per-source and LAZY: a manifest
    # that references only papers never pays to parse the record store, which
    # for a real deployment is hundreds of files.
    sources = set()
    for _s, p_, _o in referencing:
        ref = _referents.by_property(p_)
        sources.add(ref.source if ref else _referents.VOCABULARY)

    dirs = list(vocab_dirs) if _referents.VOCABULARY in sources else []
    if _referents.CONTENT in sources:
        dirs += list(content_dirs or [])

    # Load the reference stores and union with the manifest graph. The union is
    # a fresh graph; `data` is not mutated.
    reference = Graph()
    for d in dirs:
        base = root / d
        if not base.exists():
            continue
        for f in base.rglob("*"):
            if f.is_file() and rdf_format(f) is not None:
                try:
                    reference.parse(str(f), format=rdf_format(f))
                except Exception:
                    # A malformed vocab file is parse_gate's concern, not this
                    # gate's; skip it rather than crash the referential check.
                    continue
    combined = data + reference

    def _why_unmet(o) -> str | None:
        """The first requirement ``o`` fails, phrased for the report, or None."""
        for pred, obj in requirements[p]:
            if (o, pred, obj) not in combined:
                if pred == _RDF_TYPE:
                    return f"not a {obj.split('#')[-1].split('/')[-1]}"
                return f"missing {pred.split('#')[-1].split('/')[-1]} {obj.split('/')[-1]}"
        return None

    dangling: list[str] = []
    resolved = 0
    for s, p, o in referencing:
        why = _why_unmet(o)
        if why is None:
            resolved += 1
        else:
            dangling.append(f"{p.split('/')[-1]} → {o} ({why}, in {s.split('/')[-1]})")

    dangling = sorted(set(dangling))
    ok = not dangling
    summary = (
        f"{resolved} vocabulary reference(s) resolve"
        if ok
        else f"{len(dangling)} dangling vocabulary reference(s)"
    )
    return GateResult(
        name="vocabulary_reference",
        ok=ok,
        summary=summary,
        messages=dangling,
        details={"dangling": dangling, "resolved": resolved},
    )
