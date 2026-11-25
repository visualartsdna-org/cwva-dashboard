"""Record authoring tools (Phase 4.5 port of inventory #1 RDF Entry).

`record.new_work` is the faithful port of the Groovy `ParseRDF.printTtl`
field→predicate mapping (`support/ParseRDF.groovy`), verified against a real
sample record. It builds the work TTL **with rdflib** rather than string
interpolation — the emitted graph is isomorphic to the oracle's output (parity
is graph-based, per the isomorphic-diff law), and it is injection-safe.

**Decomposition vs. the Groovy.** The monolithic Groovy entry did three things
in one POST: stamp/brand the image, generate a QR code, and write the TTL. The
dashboard splits these into composable registry tools (image branding is
inventory #7; QR is a separate utility) that a workflow orchestrates. This tool
owns **only the record TTL**: it takes an already-staged image filename and an
optional QR URL. It writes into a scratch working area (``dest_dir``); the
workflow's final step **places** finished artifacts into the QA content mirror
at their SOT-layout addresses via the placement map (``promotion/layout.py``,
CE_DESIGN §3.6). The four side effects decomposed out (gdoc download, proof,
image stamp, QR) land the same way — placements into the mirror during
composition, never a transport concern. The SOT write itself is a later
promotion unit (law 4), never this tool.

Scope: **deliberately hardcoded** to the current watercolor/drawing work model;
generalization (configurable field sets, vocabularies) is **deferred to a later
release** — faithful-first against the working oracle. See the constants block.
"""

from __future__ import annotations

import uuid
from functools import partial

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, RDFS, SKOS, XSD

from ..promotion.layout import Layout, MIRROR_LAYOUT
from .base import Tool, ToolError

# Records land at their SOT-layout address in the QA content mirror (§3.6),
# not an ad-hoc scratch path — so entry, the workflow-state queries, and
# convergence all agree on where content lives. This is the DEFAULT target's
# address; build_record_tools takes a Layout so the schema defaults follow
# whichever target the QA tree actually mirrors (B1).
_DATA_DIR = MIRROR_LAYOUT["work_ttl"]

__all__ = [
    "build_record_tools", "VAD", "THE", "SCHEMA",
    "work_namespace", "image_base", "documents_base", "qrcode_url",
    "video_description",
    "video_title", "video_thumbnail",
    "WORK_FIELD_PROPERTIES", "load_ontology_model",
]

# --- commons namespaces (CE_DESIGN §13.3): shared semantics, NEVER derived from
# a deployer's domain. Field mapping is from support/ParseRDF.groovy; the record
# field set is deliberately hardcoded (faithful-first, generalization deferred).
VAD = Namespace("http://visualartsdna.org/model/")
THE = Namespace("http://visualartsdna.org/thesaurus/")
SCHEMA = Namespace("https://schema.org/")

# --- sovereign, domain-derived (CE_DESIGN §13.2/§13.7): work: and the image
# base come from `domain` in config; these module-level values are the
# default-domain instances (the current CWVA deployment).
def work_namespace(domain: str) -> Namespace:
    return Namespace(domain.rstrip("/") + "/work/")


def image_base(domain: str) -> str:
    return domain.rstrip("/") + "/images/"


def documents_base(domain: str) -> str:
    """Documents base, sibling of the image base (Q4 / EntityEntry). Bare
    md/pdf names join here; full URLs are left as-is."""
    return domain.rstrip("/") + "/documents/"


def qrcode_url(guid: str, img_base: str) -> str:
    """The QR-code image URL is DERIVED, not user-supplied (D1 / ParseRDF):
    a QR JPEG named ``qrc_<guid>.jpg`` under the image base. Groovy pre-filled
    this readonly and generated the JPEG on submit; here it is computed and the
    JPEG generation is a decomposed side effect."""
    return f"{img_base}qrc_{guid}.jpg"


# Form field -> the RDF property that field actually writes.
#
# Kept beside `_new_work`, which is the code that emits these triples, so the
# two cannot drift: a field whose property moves here without moving there
# would label itself from the wrong term. This is what lets the FORM take its
# labels and help text from the ONTOLOGY — change an rdfs:label or rdfs:comment
# in the model and the form says the new thing, with no code change.
#
# `type` and `units` are deliberately included even though they are rendered as
# closed sets: their labels come from the model like everything else.
WORK_FIELD_PROPERTIES: dict[str, str] = {
    "type": str(RDF.type),
    "label": str(RDFS.label),
    "guid": str(SCHEMA.identifier),
    "description": str(SCHEMA.description),
    "location": str(SCHEMA.location),
    "note": str(SKOS.note),
    "recorded_date": str(SCHEMA.datePublished),
    "completed_date": str(SCHEMA.dateCreated),
    "has_paper": str(VAD.hasPaper),
    "has_artist_profile": str(VAD.hasArtistProfile),
    "qrcode": str(VAD.qrcode),
    "image": str(SCHEMA.image),
    "height": str(SCHEMA.height),
    "width": str(SCHEMA.width),
    "units": str(SCHEMA.unitCode),
    "image3d": str(VAD.image3d),
    "background": str(VAD.background),
    "depth": str(SCHEMA.depth),
    # Entity form. The ontology carries labels and comments for all of these
    # (`the:topic` -> "topic" / "The subject matter of the entity"), so the form
    # says what the model says and an ontology edit changes the form.
    "topic": str(THE.topic),
    "tags": str(THE.tag),
    "md_document": str(THE.mdDocument),
    "pdf_document": str(THE.pdfDocument),
    "wikipedia": str(THE.wikipedia),
    "images": str(SCHEMA.image),
    # `primary_site` (schema:sameAs) and `definition` (skos:definition) are
    # deliberately ABSENT. Mapping a field says "the model describes this", and
    # a mapped property with no rdfs:comment renders no hint at all — silence in
    # the model is meaningful, which is why `height` shows no "Height value."
    # under a field already captioned "height". Neither of these two is
    # described in the model, so they fall through to their schema description
    # and get real help text. Add them here the day the ontology describes them.
}

# NO module-level `WORK`. It was `work_namespace(DEFAULT_DOMAIN)` — one
# deployment's identity, reachable as a default by anything that forgot to bind
# the configured one. The namespace is now threaded from config through
# `build_record_tools`, so a caller cannot mint a record under the wrong
# sovereign namespace by omission.

# units → (schema:unitCode, unit name for the label), from ParseRDF.groovy.
_UNITS = {
    "cm": ("CTM", "cm"),
    "inch": ("INH", "inches"),
    "meter": ("MTR", "meters"),
    "pixel": ("E37", "pixels"),
}


def _prefixes(work_ns: Namespace) -> dict:
    # work: is sovereign (per-domain); vad:/the:/schema:/skos: are commons.
    return {"vad": VAD, "work": work_ns, "the": THE, "schema": SCHEMA, "skos": SKOS}


#: The prefixes every record this deployment writes should declare.
#: `vad:` is the one that bites: an entity record has no `vad:` property when
#: `record.new_entity` writes it, so nothing binds the prefix — and when TCAP
#: later adds `vad:hasTensegrityPrinciple`, rdflib invents a name for the
#: namespace and the file reads `ns1:hasTensegrityPrinciple` (Rick, 2026-09-30:
#: "why ns1:, vad: is the common namespace for the model"). Valid RDF, and
#: unreadable to a person who knows the vocabulary.
def bind_standard(graph, work_ns: Namespace | None = None) -> None:
    """Declare this deployment's prefixes on a graph about to be written.

    ``work_ns`` is optional because only `work:` is sovereign; the commons
    prefixes are the ones that go missing, and a caller deep in a writer does
    not always have the domain to hand.
    """
    graph.bind("vad", VAD, override=True)
    graph.bind("the", THE, override=True)
    graph.bind("schema", SCHEMA, override=True)
    graph.bind("skos", SKOS, override=True)
    graph.bind("prov", "http://www.w3.org/ns/prov#", override=True)
    graph.bind("ops", "http://visualartsdna.org/operations/", override=True)
    if work_ns is not None:
        graph.bind("work", work_ns, override=True)


def _expand(curie: str, prefixes: dict) -> URIRef:
    """Expand a CURIE (``the:X``, ``work:Y``) to a URIRef; pass full IRIs through."""
    if "://" in curie:
        return URIRef(curie)
    prefix, _, local = curie.partition(":")
    ns = prefixes.get(prefix)
    if ns is None:
        raise ValueError(f"unknown prefix in {curie!r}")
    return ns[local]



def video_title(filename: str) -> str:
    """A display title from a video filename: ``LastSupperOrbit.mp4`` ->
    ``Last Supper Orbit``.

    Splits CamelCase, which is the convention the existing record follows. A
    filename that is not CamelCase is returned with its extension dropped and
    separators spaced — ``my-video.mp4`` becomes ``my video`` rather than
    something invented. The derivation is a convenience, and being wrong here
    costs a wrong label, not a wrong reference.
    """
    import re

    stem = str(filename).rsplit("/", 1)[-1]
    stem = stem.rsplit(".", 1)[0] if "." in stem else stem
    stem = re.sub(r"[_\-]+", " ", stem)
    # Boundaries: lower|digit -> Upper, and ACRONYM -> Word.
    stem = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", stem)
    stem = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", stem)
    return " ".join(stem.split())


def video_thumbnail(filename: str) -> str:
    """``LastSupperOrbit.mp4`` -> ``LastSupperOrbit_thumbnail.jpg``.

    The cwva-py convention. **The dashboard does not create this file** —
    cwva-py generates it on demand when the MP4 is loaded — so the name is
    written and the file is deliberately NOT gated (see asset_reference_gate).
    """
    stem = str(filename).rsplit("/", 1)[-1]
    stem = stem.rsplit(".", 1)[0] if "." in stem else stem
    return f"{stem}_thumbnail.jpg"


def video_description(work_label: str = "", type_local: str = "",
                      duration: str = "") -> str:
    """A plain description of the video, from what the record already says.

    Rick (2026-09-16): "something relatively generic, I'm more concerned about
    the video object metadata being missing than not being specific enough."

    So this states what is KNOWN — the work it belongs to, its class, how long
    it runs — and claims nothing about what the footage shows. Describing the
    content needs the file itself (AI backlog §10.7, frames sampled trusted-side)
    and the description is the user's to correct once §14.7 lands. A sentence
    that is merely unspecific can be improved; one that is confidently wrong
    about a work's own video has to be noticed first.

    Empty when there is nothing to say, because an empty property is better than
    a sentence with a hole in it.
    """
    what = f'the {_spaced(type_local)} "{work_label}"' if type_local and work_label \
        else (f'"{work_label}"' if work_label else "")
    if not what:
        return ""
    sentence = f"Video of {what}."
    running = _running_time(duration)
    return f"{sentence} {running}" if running else sentence


def _spaced(local: str) -> str:
    """`BlenderComposition` -> `Blender Composition`. Case is left alone: the
    ontology's own casing is the closest thing to an authority, and lowercasing
    would turn `Blender` — a proper noun — into a word."""
    import re

    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ",
                  str(local).rsplit("/", 1)[-1].rsplit("#", 1)[-1])


def _running_time(duration: str) -> str:
    """`PT34S` -> `Running time 34 seconds.` Unparseable or absent -> "".

    Only the shapes the probe actually emits are read. Inventing a general
    ISO-8601 duration parser to describe a turntable render would be answering a
    question nobody asked.
    """
    import re

    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?",
                     str(duration or "").strip())
    if not m or not any(m.groups()):
        return ""
    h, mi, s = (int(m.group(1) or 0), int(m.group(2) or 0), float(m.group(3) or 0))
    parts = []
    if h:
        parts.append(f"{h} hour{'s' if h != 1 else ''}")
    if mi:
        parts.append(f"{mi} minute{'s' if mi != 1 else ''}")
    if s:
        shown = int(s) if float(s).is_integer() else round(s, 1)
        parts.append(f"{shown} second{'s' if shown != 1 else ''}")
    return f"Running time {', '.join(parts)}." if parts else ""


def _new_work(
    fileops,
    *,
    work_ns,
    img_base,
    type,
    label,
    description,
    height,
    width,
    units,
    recorded_date,
    completed_date,
    has_paper,
    has_artist_profile,
    image,
    guid=None,
    location=None,
    note=None,
    dest_dir=_DATA_DIR,
):
    if units not in _UNITS:
        raise ValueError(f"units must be one of {sorted(_UNITS)}")
    guid = guid or str(uuid.uuid4())
    subj = work_ns[guid]

    prefixes = _prefixes(work_ns)
    g = Graph()
    for p, ns in prefixes.items():
        g.bind(p, ns)
    g.bind("xs", XSD)

    # A work is typed TWICE, and the second one is not redundant ancestry.
    # `vad:ArtForm` is "Category or channel of artistic expression" and
    # `vad:CreativeWork` is "Any finished original artistic or intellectual
    # creation" — SIBLINGS under `vad:ArtRealization`, so neither subsumes the
    # other and no leaf type ever entails the work is a work. The leaf says
    # what KIND of thing this is; `vad:CreativeWork` says THAT IT IS ONE.
    #
    # The Groovy oracle wrote only the leaf (see the parity test) and got the
    # other for free: its store is an inference model
    # (`rdf/util/DBMgr.groovy`, `createRDFSModel`), `vad:hasPaper` declares
    # `rdfs:domain vad:CreativeWork`, and a write-back from the inferred view
    # materialized it. That is where the 210 explicit triples in the store come
    # from. This dashboard has no reasoner, so what was free there has to be
    # asserted here — and relying on a property domain would make the type a
    # statement about annotation progress: 13 works carry no `vad:CreativeWork`
    # today, every one of them either entered here or left un-annotated
    # (Rick, 2026-10-27).
    g.add((subj, RDF.type, VAD[type]))
    g.add((subj, RDF.type, VAD.CreativeWork))
    g.add((subj, RDFS.label, Literal(label)))
    g.add((subj, SCHEMA.identifier, Literal(guid)))
    g.add((subj, SCHEMA.description, Literal(description)))
    if location:
        g.add((subj, SCHEMA.location, Literal(location)))
    if note:
        g.add((subj, SKOS.note, Literal(note)))
    g.add((subj, SCHEMA.datePublished, Literal(recorded_date, datatype=XSD.date)))
    g.add((subj, SCHEMA.dateCreated, Literal(completed_date, datatype=XSD.date)))
    g.add((subj, VAD.hasPaper, _expand(has_paper, prefixes)))
    g.add((subj, VAD.hasArtistProfile, _expand(has_artist_profile, prefixes)))
    # qrcode is derived, not supplied (D1); workOnSite is NOT written here —
    # updateWorkOnSite (#9) is the single writer of vad:workOnSite (Q2).
    g.add((subj, VAD.qrcode, URIRef(qrcode_url(guid, img_base))))
    g.add((subj, SCHEMA.image, URIRef(img_base + image)))  # required (Q3)

    unit_code, unit_name = _UNITS[units]
    for pred, value in ((SCHEMA.height, height), (SCHEMA.width, width)):
        bn = BNode()
        g.add((subj, pred, bn))
        g.add((bn, RDF.type, SCHEMA.QuantitativeValue))
        g.add((bn, RDFS.label, Literal(f"{value} {unit_name}")))
        g.add((bn, SCHEMA.unitCode, Literal(unit_code)))
        g.add((bn, SCHEMA.value, Literal(str(value), datatype=XSD.float)))

    path = f"{dest_dir.rstrip('/')}/{guid}.ttl"
    res = fileops.write_text(path, g.serialize(format="turtle"), make_parents=True)
    return {"path": res.path, "guid": guid, "uri": str(subj), "triples": len(g)}



def _add_video(g, subj, img_base, filename, *, description=None, duration=None,
               upload_date=None, work_label="", type_local=""):
    """Attach ``schema:video`` as a schema.org VideoObject blank node.

    Shaped after the one such record in production. Three of its properties are
    DERIVED rather than asked for, because each is already determined by the
    file:

    - ``rdfs:label``/``schema:name`` from the filename's CamelCase.
    - ``schema:thumbnailUrl`` by the cwva-py naming convention. **The dashboard
      does not create this file** — cwva-py renders it on demand when the video
      loads — so the URL is written for a file that legitimately does not exist
      yet, and the asset gate deliberately does not check it.
    - ``schema:uploadDate`` today, this being the day it entered the record.

    ``duration`` is read from the file by the trusted layer (see
    :mod:`cwva_dashboard.media`) — this tool cannot exec — and omitted when
    neither probed nor typed, since a wrong duration is worse than no duration.
    """
    from datetime import date

    bn = BNode()
    g.add((subj, SCHEMA.video, bn))
    # schema:VideoObject only. rdfs:Resource is entailed of every node, so
    # asserting it adds nothing a reasoner would not already have — and the one
    # such record in production does not carry it.
    g.add((bn, RDF.type, SCHEMA.VideoObject))

    title = video_title(filename)
    g.add((bn, RDFS.label, Literal(title)))
    g.add((bn, SCHEMA.name, Literal(title)))
    # Typed beats derived, always. Absent one, say what the record knows rather
    # than leave a VideoObject with no description at all — Rick's concern is
    # the metadata being MISSING, not its being unspecific.
    described = description or video_description(work_label, type_local, duration)
    if described:
        g.add((bn, SCHEMA.description, Literal(described)))
    g.add((bn, SCHEMA.thumbnailUrl, URIRef(img_base + video_thumbnail(filename))))
    g.add((bn, SCHEMA.contentUrl, URIRef(img_base + filename)))
    g.add((bn, SCHEMA.uploadDate,
           Literal(upload_date or date.today().isoformat(), datatype=XSD.date)))
    if duration:
        g.add((bn, SCHEMA.duration, Literal(duration, datatype=XSD.duration)))


def _new_digital(
    fileops,
    *,
    work_ns,
    img_base,
    type,
    label,
    description,
    note,
    height,
    width,
    depth,
    units,
    recorded_date,
    completed_date,
    has_artist_profile,
    image,
    guid=None,
    image3d=None,
    background=None,
    video=None,
    video_description=None,
    video_duration=None,
    video_upload_date=None,
    dest_dir=_DATA_DIR,
):
    """Faithful port of support/ParseDigitalRDF.printTtl. Digital works add an
    optional vad:image3d (.glb) and vad:background, and a third dimension
    (schema:depth); note is required; no hasPaper. Proof/QR/image stamping side
    effects are decomposed out. qrcode is derived (D1); workOnSite is not
    written here (Q2); image is required (Q3).

    **vad:fileFormat is deliberately NOT written (dropped 2026-09-06).** The
    Groovy form had it and the port carried it faithfully — it was even
    tightened to a strict enum (F2) on the evidence of the active data. But
    cwva-py never reads it: every file-format decision at serving time comes
    from the file extension and its mimetype. It was a display-only literal
    restating what the filename already says, and a field the user had to get
    right for no consequence. Old records keep theirs, harmlessly; new records
    omit it. A faithful port is faithful to what the system DOES, and this
    property was never doing anything."""
    if units not in _UNITS:
        raise ValueError(f"units must be one of {sorted(_UNITS)}")
    # A 3D object is displayed against a background, so a work that has one and
    # names no background is incomplete. Conditional on another field, so it
    # cannot be a `required` entry in the schema — but it belongs HERE and not
    # only in the route: a rule the form enforces and the tool does not is a
    # rule the agent does not have, and the agent will author these records too.
    if image3d and not background:
        raise ToolError(
            "missing_required",
            "background is required when a 3D object is given: a 3D work is "
            "displayed against a background image.",
        )
    guid = guid or str(uuid.uuid4())
    subj = work_ns[guid]

    prefixes = _prefixes(work_ns)
    g = Graph()
    for p, ns in prefixes.items():
        g.bind(p, ns)
    g.bind("xs", XSD)

    # Dual-typed for the reason spelled out in `_new_work`. The digital form
    # makes it plainer: there a CreativeWork entailment would have depended on
    # `vad:background` or `vad:image3d`, both OPTIONAL, so a Blender
    # composition with neither was a work that nothing said was a work — which
    # is four of the thirteen.
    g.add((subj, RDF.type, VAD[type]))
    g.add((subj, RDF.type, VAD.CreativeWork))
    g.add((subj, RDFS.label, Literal(label)))
    g.add((subj, SCHEMA.identifier, Literal(guid)))
    g.add((subj, SCHEMA.description, Literal(description)))
    g.add((subj, SKOS.note, Literal(note)))
    g.add((subj, SCHEMA.datePublished, Literal(recorded_date, datatype=XSD.date)))
    g.add((subj, SCHEMA.dateCreated, Literal(completed_date, datatype=XSD.date)))
    g.add((subj, VAD.hasArtistProfile, _expand(has_artist_profile, prefixes)))
    g.add((subj, VAD.qrcode, URIRef(qrcode_url(guid, img_base))))
    g.add((subj, SCHEMA.image, URIRef(img_base + image)))  # required (Q3)
    if image3d:
        g.add((subj, VAD.image3d, URIRef(img_base + image3d)))
    if background:
        g.add((subj, VAD.background, _expand(background, prefixes)))
    if video:
        _add_video(
            g, subj, img_base, video,
            description=video_description,
            duration=video_duration,
            upload_date=video_upload_date,
            work_label=label, type_local=type,
        )

    unit_code, unit_name = _UNITS[units]
    for pred, value in ((SCHEMA.height, height), (SCHEMA.width, width), (SCHEMA.depth, depth)):
        bn = BNode()
        g.add((subj, pred, bn))
        g.add((bn, RDF.type, SCHEMA.QuantitativeValue))
        g.add((bn, RDFS.label, Literal(f"{value} {unit_name}")))
        g.add((bn, SCHEMA.unitCode, Literal(unit_code)))
        g.add((bn, SCHEMA.value, Literal(str(value), datatype=XSD.float)))

    path = f"{dest_dir.rstrip('/')}/{guid}.ttl"
    res = fileops.write_text(path, g.serialize(format="turtle"), make_parents=True)
    return {"path": res.path, "guid": guid, "uri": str(subj), "triples": len(g)}


def _doc_url(s: str, docs_base: str) -> str:
    """Resolve an md/pdf document reference to a full documents-base URL (Q4).

    Real data is uniformly ``{domain}/documents/<name>.<ext>``. A bare name (or
    bare-with-subpath) joins the documents base; a value that already carries a
    scheme is left as-is. This replaces EntityEntry.prefixProtocol, whose
    condition (``!has('http://') || !has('https://')``) was effectively always
    true and prepended the documents path even to full URLs — and the earlier
    dashboard port `_prefix_protocol`, which prepended only ``http://`` and so
    produced ``http://name.md`` instead of the documents-base URL the data shows.
    """
    return s if "://" in s else docs_base + s.lstrip("/")


def _as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _new_entity(
    fileops,
    *,
    work_ns,
    img_base,
    docs_base,
    type,
    label,
    topic,
    definition,
    recorded_date,
    guid=None,
    md_document=None,
    pdf_document=None,
    primary_site=None,
    wikipedia=None,
    images=None,
    tags=None,
    notes=None,
    dest_dir=_DATA_DIR,
):
    """Port of support/EntityEntry.groovy handleQueryParams TTL build.
    Entity/criticism/document instances: subject work:<guid>, `a the:<type>`,
    always `skos:inScheme the:entities`; the deprecated
    `the:conceptsExtracted` is no longer written.

    Two Groovy fields are DELIBERATELY absent (2026-09-07):

    - **`the:document`**, the Google Docs source link written as a bnode with a
      "gdoc source" label. Deprecated: those reference links are not dependable
      enough to record. Its download side effect was already decomposed out,
      being network I/O outside the sanctioned effects (law 11).
    - **`the:dbpedia`**. The wikipedia link covers the same referent in a
      human-readable form, and a dbpedia URI can go in `primary_site`
      (`schema:sameAs`) if one is ever wanted.

    Old records keep both properties; neither is gated, so nothing downstream
    changes."""
    guid = guid or str(uuid.uuid4())
    subj = work_ns[guid]

    prefixes = _prefixes(work_ns)
    g = Graph()
    for p, ns in prefixes.items():
        g.bind(p, ns)
    g.bind("xs", XSD)

    g.add((subj, RDF.type, THE[type]))
    g.add((subj, RDFS.label, Literal(label)))
    for value in _as_list(topic):
        g.add((subj, THE.topic, _expand(value, prefixes)))
    g.add((subj, SKOS.definition, Literal(definition)))

    if md_document:
        g.add((subj, THE.mdDocument, URIRef(_doc_url(md_document, docs_base))))
    if pdf_document:
        g.add((subj, THE.pdfDocument, URIRef(_doc_url(pdf_document, docs_base))))
    if primary_site:
        g.add((subj, SCHEMA.sameAs, URIRef(primary_site)))
    if wikipedia:
        g.add((subj, THE.wikipedia, URIRef(wikipedia)))
    for name in _as_list(images):
        g.add((subj, SCHEMA.image, URIRef(img_base + name)))
    for tag in _as_list(tags):
        g.add((subj, THE.tag, _expand(tag, prefixes)))
    for note in _as_list(notes):
        g.add((subj, SKOS[note.get("type", "note")], Literal(note["text"])))

    g.add((subj, SCHEMA.datePublished, Literal(recorded_date, datatype=XSD.date)))
    # `the:conceptsExtracted` is NOT written (Rick, 2026-10-02: "should be
    # removed going forward"). It was the pre-DTS workflow boolean, and DTS's
    # six stamps replaced it on 2026-09-30 — "follow the new audit stamp
    # rules". A new entity carried `false` forever after, which the browser
    # renders as `derived: false` (the ontology labels it "derived"), sitting
    # one row above DTS's own `ops:derived` and contradicting it.
    #
    # GOING FORWARD only. The 85 records that carry it keep it: "I'm not
    # concerned with its historical use, it can remain in past records." The
    # `concepts_extracted_false` standing query therefore still names the
    # legacy entities nobody ran extraction over — a fixed set now rather than
    # a shrinking one — and `migrate_status_shape.py` does not touch it.
    g.add((subj, SKOS.inScheme, THE.entities))

    path = f"{dest_dir.rstrip('/')}/{guid}.ttl"
    res = fileops.write_text(path, g.serialize(format="turtle"), make_parents=True)
    return {"path": res.path, "guid": guid, "uri": str(subj), "triples": len(g)}


def _s(desc, **extra):
    return {"type": "string", "description": desc, **extra}


def _num(desc):
    return {"type": "number", "description": desc}


def _s_array(desc, **extra):
    return {"type": "array", "description": desc, "items": {"type": "string"}, **extra}


# --- affordance closed sets (Groovy extraction §"Closed sets"; affordance step 4)
# STRICT `enum` = truly closed & real-data-verified (dispatch-enforced). The set
# whose members a user picks and nothing outside is valid.
_UNITS_ENUM = ["cm", "inch", "meter", "pixel"]
_ENTITY_TYPES = [  # real asserted entity types all fall inside this list (verified)
    "AI", "Article", "Artist", "Collection", "Concept", "Entity", "Image",
    "Operation", "Organization", "Posting", "Series", "Study", "Work",
]
_NOTE_TYPES = ["note", "changeNote", "editorialNote", "example", "historyNote", "scopeNote"]

# Q9 RESOLVED: `type` is model-backed, not a hardcoded set. Its candidate set is
# the RDFS subclass closure of a per-form **type_root** in the ontology (Rick's
# decision): RDF Entry (painting) draws from vad:PaintingForm, RDF Digital
# (sculpture) from vad:SculptureForm — parent INCLUDED, so an abstract root is a
# valid fallback for a novel medium not yet modeled as a class (TeaBagPainting).
# Enforced at DISPATCH, not the promotion gate, because the per-form root is
# known when the tool is built but lost once records are just `a vad:X` in a
# manifest — and the candidate set is materialized into the schema `enum` at
# registry-build time (validator stays pure/store-free). Adding a work kind is
# then an ONTOLOGY edit (data, promoted through the gated exit) + a registry
# rebuild — zero record-tool code change. `type_root` and `allow_abstract_root`
# are per-form config (a future entry-form-design workflow generalizes them).
# The built-in fallback carries the Groovy-sourced preselections too, so a
# deployment without an `entry_forms` block still behaves like the form it is a
# port of (EXTRACTION: Watercolor checked for work, Q1 for digital). These are
# facts about the original, not deployment preferences.
_ENTRY_FORMS_DEFAULT = {
    "work": {
        "type_root": "vad:PaintingForm", "allow_abstract_root": True,
        "type_default": "Watercolor",
    },
    "digital": {
        "type_root": "vad:SculptureForm", "allow_abstract_root": True,
        "type_default": "BlenderComposition",
    },
}

# Fallback candidate sets, used ONLY when the ontology model is not loaded (fresh
# sandbox before the model is synced) — rendered as `x-enum-suggested` (not
# enforced) so entry still works, degrading to the current behavior.
_WORK_TYPES_SUGGESTED = ["Watercolor", "Drawing", "EggTempera", "PaintingForm"]
# Q6: canonical casing is 'Lindenmayer' (lower m), matching real data.
_DIGITAL_TYPES_SUGGESTED = ["BlenderComposition", "DigitalSculpture", "SculptureForm"]


def art_form_names(model) -> set | None:
    """Local names of ``vad:ArtForm`` and every class under it, or ``None`` when
    the model does not define it.

    **What a work IS, per the ontology.** The record pickers offer works and
    nothing else (Rick, 2026-09-18) — an entity, an artist and an artist profile
    are all records, and none of them is a thing to annotate. The test could
    have been a list of type names here; it is a query against the model because
    the model is where "this is a kind of art" is already written, and a list
    here would be a second answer to go stale against the first.

    ``None`` is not "everything". It means the store cannot classify anything —
    the ontology is missing — and the callers say so rather than falling back to
    a wider set the user did not ask for.
    """
    got = subclass_closure(model, VAD.ArtForm) if model is not None else None
    return set(got) if got else None


def subclass_closure(model, root, *, include_root=True):
    """The RDFS downward closure of ``root`` in ``model`` as sorted local names:
    every class ``X`` with ``X rdfs:subClassOf+ root``, plus ``root`` itself when
    ``include_root``. Computed by transitive walk (deterministic — RDFS closure),
    so it reproduces the materialized store's ``?s rdfs:subClassOf root`` result
    WITHOUT needing owlrl here. Returns ``None`` if ``root`` is absent from the
    model (→ caller falls back to the suggested set)."""
    from rdflib import URIRef
    from rdflib.namespace import RDFS

    root = URIRef(root)
    # root absent from the model entirely → cannot resolve
    if (root, None, None) not in model and (None, None, root) not in model:
        return None
    found, frontier = set(), {root}
    while frontier:
        nxt = set()
        for parent in frontier:
            for child in model.subjects(RDFS.subClassOf, parent):
                if isinstance(child, URIRef) and child not in found:
                    found.add(child)
                    nxt.add(child)
        frontier = nxt
    if include_root:
        found.add(root)
    return sorted(str(x).rsplit("/", 1)[-1].rsplit("#", 1)[-1] for x in found)


def load_ontology_model(model_dir):
    """Load the ontology model (``*.ttl`` under ``model_dir``) into one graph, or
    return ``None`` if the dir is absent/empty. Best-effort: the model may not be
    synced yet on a fresh sandbox, in which case type resolution falls back."""
    from pathlib import Path

    from rdflib import Graph

    base = Path(model_dir)
    if not base.is_dir():
        return None
    files = [f for f in base.rglob("*.ttl") if f.is_file()]
    if not files:
        return None
    g = Graph()
    for f in files:
        try:
            g.parse(str(f), format="turtle")
        except Exception:
            continue  # a broken model file is the parse gate's concern
    return g if len(g) else None


def _type_field(desc, model, form_cfg, suggested):
    """The `type` schema field: a strict `enum` resolved from the ontology when
    the model is loaded (subclass closure of the form's type_root), else an
    unenforced `x-enum-suggested` fallback.

    ``type_default`` (per-form config) preselects one member, restoring the
    Groovy form's ``checked`` radio — Watercolor for work, BlenderComposition
    for digital (EXTRACTION Q1). It is **validated against the resolved set**
    rather than trusted: a default naming a class the ontology does not have
    would preselect a value dispatch then rejects, which is the offered-set ≠
    enforced-set hole in miniature. An unresolvable default is dropped.
    """
    resolved = None
    form_cfg = form_cfg or {}
    if model is not None and form_cfg:
        root = form_cfg["type_root"]
        root_uri = VAD[root.split(":", 1)[1]] if root.startswith("vad:") else URIRef(root)
        resolved = subclass_closure(
            model, root_uri, include_root=form_cfg.get("allow_abstract_root", True)
        )
    default = form_cfg.get("type_default")
    if resolved:
        incl = "included" if form_cfg.get("allow_abstract_root", True) else "excluded"
        extra = {"enum": resolved}
        if default in resolved:
            extra["default"] = default
        return _s(
            f"{desc} Candidate set = subclasses of {form_cfg['type_root']} "
            f"(parent {incl}), resolved from the ontology.",
            **extra,
        )
    extra = {"x-enum-suggested": suggested}
    if default in suggested:
        extra["default"] = default
    return _s(f"{desc} Ontology not loaded — suggested set, unenforced.", **extra)




# --- uniqueness checks (entry-time advice; see the gate for enforcement) ------

# PREDICATE-AGNOSTIC on purpose. The first version of this asked only about
# schema:image, so when vad:image3d and schema:video arrived they were ingested
# with no collision check at all — a .glb or .mp4 could silently overwrite the
# asset of an already-published work. Enumerating properties here means every
# future asset property is a hole until someone remembers this query. Asking
# "does ANY record already point at this URI?" cannot fall behind the model.
#
# CASE-INSENSITIVE, which is a deliberate over-reach. As IRIs, `.../Sunset.jpg`
# and `.../sunset.JPG` are genuinely different — RFC 3986 path segments are
# case-sensitive — and on Linux and in a GCS bucket they are two files. On
# Windows and default macOS they are ONE, so ingesting the second overwrites the
# first work's image while an exact-match check reports nothing. CE targets
# Linux *and* Windows, so the answer must not depend on which one is running.
#
# The store already contains the case in point: `Sunset.jpg` ("Sunset") and
# `sunset.JPG` ("Just past 6 pm") are two different paintings.
#
# The cost of the over-reach is refusing a name that would have been legal on
# Linux; the remedy is a rename the user was going to be asked for anyway. The
# cost of under-reaching is a published work silently losing its picture.
# SELECT rather than ASK so the refusal can name the EXISTING spelling — with
# case the whole point, "already in use" without showing what it clashes with is
# a puzzle rather than a message.
_ASSET_TAKEN = """
SELECT ?o ?s WHERE { ?s ?p ?o . FILTER (isIRI(?o) && lcase(str(?o)) = %s) }
"""

_LABEL_TAKEN = """
SELECT ?s WHERE {
  ?s a <%s> ; <http://www.w3.org/2000/01/rdf-schema#label> ?l .
  FILTER (str(?l) = %s)
}
"""


def _owning_record(graph, node):
    """The NAMED subject a statement belongs to, walking up through blank nodes.

    A file reference is not always written on the record's own subject.
    ``schema:video`` hangs a ``schema:VideoObject`` blank node off the work and
    puts ``schema:contentUrl`` on *that*, so the subject of the statement
    holding the URL is a blank node with no identity to compare against.

    Excluding "the record being edited" by subject therefore matched nothing
    for those fields, and re-submitting a work after `Edit form` reported its
    own video as taken by another record — with no other record in sight and
    nothing the user could rename (Rick, 2026-09-27: "I'm in the same record
    just editing the record. I shouldn't need to rename anything.").

    Breadth-first so the nearest named ancestor wins, and the node itself is
    returned when nothing owns it — an orphaned blank node is not somebody
    else's record, but it is not this one either, so it still collides.
    """
    frontier, seen = [node], set()
    while frontier:
        cur = frontier.pop(0)
        if isinstance(cur, URIRef):
            return cur
        if cur in seen:
            continue
        seen.add(cur)
        frontier.extend(graph.subjects(None, cur))
    return node


def _check_uniqueness(fileops, img_base, image=None, files=None, label=None,
                      type=None, content_dir=None, exclude_subject=None):
    """Are any of these asset filenames already referenced, and is this label
    already used by a work of the same type?

    Two questions with **different severities**, answered together because they
    share one graph load:

    - ``files_taken`` is an **error**. Filename + image base form the URI a
      record points at, so a second work reusing a filename means the ingest
      overwrites the first work's asset and convergence pushes the new bytes to
      the same SOT path — silently replacing a published work's picture, mesh or
      video. The remedy is a rename, which only the user can do (the file lives
      in their drop folder).
    - ``label_taken`` is **advice**. Two watercolours may legitimately share a
      title; it is worth surfacing and never worth blocking. Reported with the
      colliding subjects so the user can judge.

    ``files`` is EVERY asset the submission would ingest, not just the image.
    The hazard belongs to the ingest, and the ingest copies in every file-ref
    field — so checking one of them left the others able to overwrite silently.

    Runs over the cached content graph, so an unchanged store costs a single
    `list_dir` rather than a read per record.
    """
    from rdflib.plugins.sparql import prepareQuery  # noqa: F401  (parity check)

    from .workflow_tools import _content_graph

    graph = _content_graph(fileops, content_dir or _DATA_DIR)
    out = {"files_taken": [], "taken_uris": {}, "label_taken": False,
           "label_matches": []}

    base = img_base
    names = [n for n in [image, *(files or [])] if n]
    # `exclude_subject` is the record being EDITED. Without it a record's own
    # file collides with itself and every edit is refused; with it, "already
    # spoken for" means "by someone else".
    skip = str(exclude_subject) if exclude_subject else None
    for name in dict.fromkeys(names):  # de-duplicated, order preserved
        uri = name if "://" in name else base + name
        rows = [r for r in graph.query(_ASSET_TAKEN % _sparql_str(uri.lower()))
                if skip is None
                or str(_owning_record(graph, r[1])) != skip]
        if rows:
            out["files_taken"].append(name)
            out["taken_uris"][name] = str(rows[0][0])

    if label and type:
        cls = VAD[type] if not type.startswith("http") else type
        rows = graph.query(_LABEL_TAKEN % (cls, _sparql_str(label)))
        out["label_matches"] = sorted(str(r[0]) for r in rows)
        out["label_taken"] = bool(out["label_matches"])

    return out



def _list_referents(fileops, referent, work_ns, content_dir=None):
    """Candidates for a CONTENT-sourced referent, e.g. background images.

    Separate from the `x-vocabulary` path because the referent is not a
    thesaurus concept: a background is an ordinary entity record (`a the:Image`
    with `the:topic the:Background`), independent of any work and reusable
    across many, so it lives in the record store. The conditions come from
    `referents.py` — the same ones the gate refuses the reference for failing.

    Runs over the cached content graph, so an unchanged store costs one
    `list_dir` rather than a read per record.
    """
    from ..referents import REFERENTS
    from .workflow_tools import _content_graph

    ref = REFERENTS.get(referent)
    if ref is None:
        raise ToolError("not_in_enum", f"unknown referent {referent!r}")

    graph = _content_graph(fileops, content_dir or _DATA_DIR)
    first_pred, first_obj = ref.conditions[0]
    out = []
    for s in graph.subjects(first_pred, first_obj):
        if not ref.satisfied_by(graph, s):
            continue
        label = graph.value(s, RDFS.label)
        local = str(s).rsplit("/", 1)[-1]
        out.append({
            "value": _curie_of(str(s), work_ns),
            "label": str(label) if label else local,
        })
    return {"candidates": sorted(out, key=lambda d: d["label"].lower())}


def _curie_of(uri: str, work_ns: Namespace) -> str:
    """Shorten a URI to a CURIE. `work:` comes from the CONFIGURED namespace —
    it was a literal here, which is one deployment's identity compiled into a
    string comparison: for anyone else it simply never matched, and the picker
    silently offered full URIs instead of CURIEs."""
    for prefix, ns in (("the", str(THE)), ("vad", str(VAD)), ("work", str(work_ns))):
        if uri.startswith(ns):
            return f"{prefix}:{uri[len(ns):]}"
    return uri



def _resolve_tags(fileops, tags, work_ns, content_dir=None, reference_dirs=None):
    """Does each `the:tag` reference point at something that exists, and what is
    it called?

    Tags are free text — there is no picker, because a tag may name any record
    or concept in the store — so a typo produces a reference to nothing and
    nothing downstream complains. The label is the useful half of the answer:
    `work:53bfd31d-…` tells a reviewer nothing, "Network-Art Aesthetic" tells
    them whether they tagged what they meant to.

    **Both stores are searched.** Real tags point at content records (175 of
    186 in the store) *and* at thesaurus concepts (`the:pigment`,
    `the:WatercolorCriticismScheme`), so looking in content alone reports every
    concept tag as missing.

    Advisory, never a refusal — see the route. Returns one entry per tag in the
    order given, so the review page can list them as typed.
    """
    from .workflow_tools import _content_graph

    graph = _content_graph(fileops, content_dir or _DATA_DIR)
    for d in reference_dirs or ():
        for triple in _content_graph(fileops, d):
            graph.add(triple)

    prefixes = _prefixes(work_ns)
    out = []
    for raw in _as_list(tags):
        value = str(raw).strip()
        if not value:
            continue
        uri = _expand(value, prefixes)
        found = (uri, RDF.type, None) in graph
        label = graph.value(uri, RDFS.label) or graph.value(uri, SKOS.prefLabel)
        out.append({
            "value": value,
            "uri": str(uri),
            "found": bool(found),
            # A resolvable referent with no label is real: `the:StillLifeBottle…`
            # is in the store and unlabelled. Fall back to the local name rather
            # than showing an empty cell, which reads as "not found".
            "label": str(label) if label else (str(uri).rsplit("/", 1)[-1] if found else ""),
            "types": sorted(
                str(t).rsplit("/", 1)[-1].rsplit("#", 1)[-1]
                for t in graph.objects(uri, RDF.type)
            ),
        })
    return {"tags": out, "missing": [t["value"] for t in out if not t["found"]]}


def _sparql_str(value: str) -> str:
    """A SPARQL string literal. Quoting matters: a label is user input going
    into a query, and an unescaped quote would be a syntax error at best."""
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'



def _content_referents() -> list[str]:
    from ..referents import CONTENT, names_for

    return names_for(CONTENT)


def build_record_tools(
    domain: str, *, model=None, entry_forms=None, layout=None,
    artist_profile: str | None = None,
) -> list[Tool]:
    """Record authoring tools bound to a deployer's ``domain`` (CE_DESIGN §13.7):
    ``work:`` and the image base derive from it; ``vad:``/``the:`` stay commons.

    ``model`` (an rdflib Graph of the ontology) and ``entry_forms`` (per-form
    ``type_root`` + ``allow_abstract_root`` config) make ``type`` a dispatch enum
    resolved from the ontology's class hierarchy; without them ``type`` falls
    back to an unenforced suggested set. Rebuild the registry to pick up an
    ontology change (CE v1: single user, restart is fine).

    ``layout`` is the active target's placement map (B1, CE_DESIGN §3.6): the
    ``dest_dir`` defaults must name where the QA tree *actually* keeps records,
    or entry writes to `content/ttl/data` while the sync populated `ttl/data`
    and the mirror silently becomes two trees."""
    _lay = layout or Layout.default()
    data_dir = _lay.dir("work_ttl")
    # The picker subtree follows the target too, or it lists a directory
    # that does not exist on a QA tree mirroring a differently-laid-out SOT.
    images_dir = _lay.dir("image")
    documents_dir = _lay.dir("document")
    work_ns = work_namespace(domain)
    img = image_base(domain)
    docs = documents_base(domain)
    forms = entry_forms or _ENTRY_FORMS_DEFAULT
    # The deployer's own artist-profile record. An overridable DEFAULT, not a
    # constant: single-user CE is not single-artist-profile forever
    # (the affordance design review, point 3). Config-sourced, since it is an
    # account-like identifier and those never live in code.
    _profile = {"default": artist_profile} if artist_profile else {}
    work_type = _type_field(
        "vad: painting work class local name.", model, forms.get("work"), _WORK_TYPES_SUGGESTED
    )
    digital_type = _type_field(
        "vad: digital work class local name (Q6 casing: 'Lindenmayer').",
        model, forms.get("digital"), _DIGITAL_TYPES_SUGGESTED,
    )
    _nw = partial(_new_work, work_ns=work_ns, img_base=img)
    _ne = partial(_new_entity, work_ns=work_ns, img_base=img, docs_base=docs)
    _nd = partial(_new_digital, work_ns=work_ns, img_base=img)
    return [
    Tool(
        name="record.check_uniqueness",
        description=(
            "Are any of these asset filenames already referenced by a record, and is "
            "this label already used by a work of the same type? A taken filename is "
            "an ERROR condition (ingest would overwrite an existing work's asset on "
            "convergence); the label answer is advice, never a block."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "image": _s("Image filename (or full URI) to check."),
                "exclude_subject": _s(
                    "Subject URI to ignore — the record being edited, so its "
                    "own files do not collide with themselves."
                ),
                "files": _s_array(
                    "Every asset filename the submission would ingest — image, "
                    "3D object, video. Checked together, since each one can "
                    "overwrite a published work's asset."
                ),
                "label": _s("Work label to check within `type`."),
                "type": _s("Work class local name, e.g. Watercolor."),
                "content_dir": _s("Records dir to search.", default=data_dir),
            },
            "required": [],
            "additionalProperties": False,
        },
        handler=partial(_check_uniqueness, img_base=img),
    ),
    Tool(
        name="record.resolve_tags",
        description=(
            "Resolve the:tag references to their labels, and report which point "
            "at nothing. Advisory: a tag may legitimately run ahead of the "
            "record it names."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "tags": _s_array("Tag CURIEs/IRIs to resolve."),
                "content_dir": _s("Records dir to search.", default=data_dir),
                "reference_dirs": _s_array(
                    "Extra dirs holding referents (the thesaurus).",
                    default=[_lay.dir("vocab_ttl"), _lay.dir("tags_ttl")],
                ),
            },
            "required": ["tags"],
            "additionalProperties": False,
        },
        handler=partial(_resolve_tags, work_ns=work_ns),
    ),
    Tool(
        name="record.list_referents",
        description=(
            "Candidates for a content-sourced reference field (e.g. background "
            "images), by the same conditions the promotion gate enforces."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "referent": _s(
                    "Referent name.", enum=sorted(_content_referents()),
                ),
                "content_dir": _s("Records dir to search.", default=data_dir),
            },
            "required": ["referent"],
            "additionalProperties": False,
        },
        handler=partial(_list_referents, work_ns=work_ns),
    ),
    Tool(
        name="record.new_work",
        description="Stage a non-digital work record (TTL) in the QA content tree (inventory #1).",
        input_schema={
            "type": "object",
            "properties": {
                "type": work_type,
                "label": _s("Work title (rdfs:label)."),
                "description": _s("Work description (schema:description).", **{"x-multiline": True}),
                "height": _num("Height value."),
                "width": _num("Width value."),
                "units": _s("Unit of measure.", enum=_UNITS_ENUM, default="inch"),
                "recorded_date": _s("schema:datePublished, ISO date (YYYY-MM-DD).", format="date"),
                "completed_date": _s("schema:dateCreated, ISO date (YYYY-MM-DD).", format="date"),
                "has_paper": _s(
                    "vad:hasPaper CURIE/IRI — a vad:WatercolorPaper concept.",
                    **{"x-vocabulary": "papers"},
                ),
                "has_artist_profile": _s(
                    "vad:hasArtistProfile CURIE or IRI, e.g. work:<guid>.", **_profile
                ),
                "image": _s(
                    "Image filename (schema:image = images base + name).",
                    **{"x-file-ref": images_dir},
                ),
                "guid": _s("Optional work GUID; minted if omitted."),
                "location": _s("Optional schema:location."),
                "note": _s("Optional skos:note.", **{"x-multiline": True}),
                "dest_dir": _s("Sandbox-relative content dir.", default=data_dir),
            },
            "required": [
                "type", "label", "description", "height", "width", "units",
                "recorded_date", "completed_date", "has_paper", "has_artist_profile",
                "image",
            ],
            "additionalProperties": False,
        },
        handler=_nw,
        redact=frozenset({"description", "note"}),
    ),
    Tool(
        name="record.new_entity",
        description="Stage an entity/criticism/document instance (TTL) in the QA content tree (inventory #3). Always sets inScheme the:entities.",
        input_schema={
            "type": "object",
            "properties": {
                "type": _s("the: entity class local name.", enum=_ENTITY_TYPES),
                "label": _s("Instance label (rdfs:label)."),
                # Named for the property it writes. It was `media` — the
                # Groovy's own name for the field — which put the word "media"
                # above a grid of topics and matched nothing in the record.
                "topic": _s_array(
                    "the:topic CURIEs/IRIs — TopicScheme concepts (one or more).",
                    **{"x-vocabulary": "topics"},
                ),
                "definition": _s("What this entity is (skos:definition).", **{"x-multiline": True}),
                "recorded_date": _s("schema:datePublished, ISO date (YYYY-MM-DD).", format="date"),
                "guid": _s("Optional GUID; minted if omitted."),
                # Pickers over the DROP FOLDER, not free text.
                #
                # The Groovy fetched these from Google Docs and wrote the
                # resulting filename in. That download cannot exist here: it is
                # network I/O outside the three sanctioned effects (law 11), and
                # the record would in any case name a document that never
                # reaches SOT. The CE shape is law 12 — the user drops the .md
                # (and .pdf) in the folder, the dashboard ingests it, and the
                # reference resolves because the file really converged.
                "md_document": _s(
                    "Optional the:mdDocument — a markdown file from the drop folder.",
                    **{"x-file-ref": documents_dir, "x-file-kind": "markdown"},
                ),
                "pdf_document": _s(
                    "Optional the:pdfDocument — a PDF from the drop folder.",
                    **{"x-file-ref": documents_dir, "x-file-kind": "pdf"},
                ),
                "primary_site": _s(
                    "Optional canonical URL for this entity elsewhere "
                    "(schema:sameAs)."
                ),
                "wikipedia": _s("Optional the:wikipedia IRI."),
                "images": _s_array(
                    "Optional image filenames (schema:image). Multi-valued: the "
                    "Groovy took a comma-separated list.",
                    **{"x-file-ref": images_dir, "x-file-kind": "image"},
                ),
                "tags": _s_array("Optional the:tag CURIEs/IRIs (durable instance links)."),
                "notes": {
                    "type": "array",
                    "description": (
                        "Optional notes: objects {type, text} → skos:<type>. "
                        "The type is a CLOSED set, enforced per element."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            # Enforced by validate_args, which now recurses into
                            # object items. It did not, and the description said
                            # so — but the form still offered exactly these six,
                            # so `skos:<anything>` was mintable by a caller that
                            # was not the form. Offered == enforced needs the
                            # enum to be real.
                            "type": _s("Note kind.", enum=_NOTE_TYPES, default="note"),
                            "text": _s("Note text.", **{"x-multiline": True}),
                        },
                        "required": ["text"],
                        "additionalProperties": False,
                    },
                },
                "dest_dir": _s("Sandbox-relative content dir.", default=data_dir),
            },
            "required": ["type", "label", "topic", "definition", "recorded_date"],
            "additionalProperties": False,
        },
        handler=_ne,
        redact=frozenset({"definition", "notes"}),
    ),
    Tool(
        name="record.new_digital",
        description="Stage a digital work record (TTL) in the QA content tree (inventory #2). Adds optional image3d/background/video and a depth dimension.",
        input_schema={
            "type": "object",
            "properties": {
                "type": digital_type,
                "label": _s("Work title (rdfs:label)."),
                "description": _s("schema:description.", **{"x-multiline": True}),
                "note": _s("skos:note (required for digital works).", **{"x-multiline": True}),
                "height": _num("Height value."),
                "width": _num("Width value."),
                "depth": _num("Depth value."),
                "units": _s("Unit of measure.", enum=_UNITS_ENUM, default="meter"),
                "recorded_date": _s("schema:datePublished, ISO date.", format="date"),
                "completed_date": _s("schema:dateCreated, ISO date.", format="date"),
                "has_artist_profile": _s(
                    "vad:hasArtistProfile CURIE or IRI.", **_profile
                ),
                "image": _s(
                    "Main image filename (schema:image).",
                    **{"x-file-ref": images_dir},
                ),
                "guid": _s("Optional GUID; minted if omitted."),
                "image3d": _s(
                    "Optional 3D object filename, glTF (.gltf) or GLB (.glb) "
                    "(vad:image3d).",
                    # Same SUBTREE as the stills — production keeps meshes in
                    # images/ — but a different KIND, so the picker offers 3D
                    # objects and not photographs. Without the kind every
                    # file-ref field showed the same image list.
                    **{"x-file-ref": images_dir, "x-file-kind": "model3d"},
                ),
                # A picker, not free text: backgrounds are a closed, queryable
                # set (entity records typed the:Image, topic the:Background),
                # independent of any work and shared across many. Sourced from
                # CONTENT rather than the thesaurus, hence its own annotation.
                # Optional in the schema because it is only required WHEN
                # image3d is given — a cross-field rule JSON Schema cannot
                # state, enforced in the handler instead.
                "background": _s(
                    "vad:background — a background image entity. Required when "
                    "a 3D object is given.",
                    **{"x-entity-ref": "backgrounds"},
                ),
                # schema:video, entirely optional: a digital work with no video
                # omits the property altogether rather than emitting an empty
                # VideoObject. Same images/ subtree again (production keeps the
                # MP4 beside the stills), its own KIND so the picker offers only
                # what the browser can play.
                "video": _s(
                    "Optional video filename — MP4, WebM or Ogg (schema:video).",
                    **{"x-file-ref": images_dir, "x-file-kind": "video"},
                ),
                "video_description": _s(
                    "Optional schema:description for the video.",
                    **{"x-multiline": True},
                ),
                # Normally probed from the file by the trusted layer; the field
                # exists so a deployment without ffmpeg can still state it, and
                # so a probed value can be corrected.
                "video_duration": _s(
                    "Optional video duration as an ISO-8601 xs:duration, e.g. "
                    "PT34S. Read from the file automatically when possible.",
                    format="duration",
                ),
                "video_upload_date": _s(
                    "Optional schema:uploadDate; defaults to today.",
                    format="date",
                ),
                "dest_dir": _s("Sandbox-relative content dir.", default=data_dir),
            },
            "required": [
                "type", "label", "description", "note", "height", "width", "depth",
                "units", "recorded_date", "completed_date",
                "has_artist_profile", "image",
            ],
            "additionalProperties": False,
        },
        handler=_nd,
        redact=frozenset({"description", "note"}),
    ),
    ]
