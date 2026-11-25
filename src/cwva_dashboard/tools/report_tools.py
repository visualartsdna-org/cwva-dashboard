"""Reports over the records (the hub's Tools tab).

``report.registry`` — the register of one artist profile's works: title,
image, QR code, year, description, by title (inventory #19, the port of
CollectionReport.groovy). The Groovy hard-wired one profile and printed "by
Rick Spates"; here the profile is chosen and the artist is read from the data,
which a public release needs.

``report.certificate`` — a Certificate of Authenticity for one work: its
title, then everything its record says as Property / Value, then lines to sign
and date (inventory #20, the port of CertAuthenticity.groovy). Concepts read as
their names and a dimension as "15 inches", where the Groovy showed codes and
blank-node ids.

``report.storage`` — what is in one storage class, by Disposition Identifier:
the list to take to the boxes (Rick, 2026-11-19, once a one-off and now a
regular task). The default class is the blank one (``2026.159``, no prefix),
where the paper works go (the provenance plan §2).

Read-only, over the same cached graph the other readers use.
"""

from __future__ import annotations

import re

from rdflib import BNode, Graph, Literal, URIRef

from ..promotion.layout import Layout
from ..workflows.annotate import _picker_label
from .base import Tool, ToolError
from .workflow_tools import _content_graph

__all__ = ["build_report_tools", "storage_rows", "parse_di", "registry_profiles",
           "registry_rows", "certificate"]

_VAD = "http://visualartsdna.org/model/"
_DI = URIRef(_VAD + "dispositionId")
_HAS_ARTWORK = URIRef(_VAD + "hasArtwork")
_LABEL = URIRef("http://www.w3.org/2000/01/rdf-schema#label")
_IMAGE = URIRef("https://schema.org/image")
_QRCODE = URIRef(_VAD + "qrcode")
_DESC = URIRef("https://schema.org/description")
_CREATED = URIRef("https://schema.org/dateCreated")
_PROFILE = URIRef(_VAD + "hasArtistProfile")
_ARTIST = URIRef(_VAD + "artist")
_ARTIST_PROFILE = URIRef(_VAD + "ArtistProfile")
_FOAF_NAME = URIRef("http://xmlns.com/foaf/0.1/name")
_RDF_TYPE = URIRef("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")

# [ <storage-class> "." ] <year> "." <item>
_DI_RE = re.compile(r"^(?:(?P<cls>[A-Za-z][\w-]*)\.)?(?P<year>\d{4})\.(?P<item>\d+)$")


def parse_di(di: str):
    """``(class, year, item)``, class "" for the default; None if malformed."""
    m = _DI_RE.match(di.strip())
    if not m:
        return None
    return (m.group("cls") or "", int(m.group("year")), int(m.group("item")))


def _thumbnail(image: str) -> str:
    """The published server makes a small copy of every image under
    /thumbnails/; the report would otherwise pull every full-size image to
    show it 50 px wide."""
    return image.replace("/images/", "/thumbnails/", 1) if "/images/" in image else image


def storage_rows(graph: Graph, storage_class: str = "") -> list[dict]:
    rows = []
    for prov, di in graph.subject_objects(_DI):
        parsed = parse_di(str(di))
        if parsed is None or parsed[0] != storage_class:
            continue
        work = graph.value(prov, _HAS_ARTWORK)
        label = graph.value(work, _LABEL) if work is not None else None
        images = sorted(str(o) for o in graph.objects(work, _IMAGE)) if work is not None else []
        rows.append({
            "di": str(di), "year": parsed[1], "item": parsed[2],
            "work": str(work) if work is not None else "",
            "title": str(label) if isinstance(label, Literal) else "",
            "image": images[0] if images else "",
            "thumbnail": _thumbnail(images[0]) if images else "",
        })
    rows.sort(key=lambda r: (r["year"], r["item"]))
    return rows


def _artist_name(graph: Graph, profile) -> str:
    artist = graph.value(profile, _ARTIST)
    if artist is None:
        return ""
    name = graph.value(artist, _FOAF_NAME) or graph.value(artist, _LABEL)
    return str(name) if name is not None else ""


def registry_profiles(graph: Graph) -> list[dict]:
    """Every artist profile, with its artist and how many works it has."""
    out = []
    for p in set(graph.subjects(_RDF_TYPE, _ARTIST_PROFILE)):
        out.append({"profile": str(p), "label": str(graph.value(p, _LABEL) or p),
                    "artist": _artist_name(graph, p),
                    "count": sum(1 for _ in graph.subjects(_PROFILE, p))})
    return sorted(out, key=lambda r: (-r["count"], r["label"]))


def registry_rows(graph: Graph, profile: str) -> dict:
    p = URIRef(profile)
    if (p, _RDF_TYPE, _ARTIST_PROFILE) not in graph:
        raise ToolError("not_found", f"no artist profile {profile}")
    rows = []
    for w in set(graph.subjects(_PROFILE, p)):
        img = sorted(str(o) for o in graph.objects(w, _IMAGE))
        qr = graph.value(w, _QRCODE)
        created = graph.value(w, _CREATED)
        rows.append({
            "work": str(w), "title": str(graph.value(w, _LABEL) or ""),
            "image": img[0] if img else "", "thumbnail": _thumbnail(img[0]) if img else "",
            "qrcode": str(qr) if qr is not None else "",
            "year": str(created)[:4] if created is not None else "",
            "description": str(graph.value(w, _DESC) or ""),
        })
    rows.sort(key=lambda r: (r["title"].casefold(), r["work"]))
    return {"profile": profile, "label": str(graph.value(p, _LABEL) or profile),
            "artist": _artist_name(graph, p), "rows": rows, "count": len(rows)}


_SKOS_PREF = URIRef("http://www.w3.org/2004/02/skos/core#prefLabel")
_CREATIVE_WORK = URIRef(_VAD + "CreativeWork")
_THE_TAG = URIRef("http://visualartsdna.org/thesaurus/tag")
#: How the Groovy showed these two: images, not links.
_PICTURES = {str(_IMAGE): 50, str(_QRCODE): 100}
_GUID = re.compile(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})")


def _local(iri: str) -> str:
    return re.split(r"[/#]", iri.rstrip("/#"))[-1]


def _curie(graph: Graph, iri) -> str:
    try:
        return graph.namespace_manager.normalizeUri(iri)
    except Exception:
        return str(iri)


def _value(graph: Graph, prop: str, o) -> dict:
    """One cell: text, and a link or a picture where the Groovy had one."""
    if isinstance(o, Literal):
        return {"text": str(o)}
    if isinstance(o, BNode):
        # a dimension or an NFT node: its own label says it ("15 inches")
        label = graph.value(o, _LABEL)
        return {"text": str(label) if label is not None else
                ", ".join(f"{_local(str(p))}: {v}" for p, v in graph.predicate_objects(o)
                          if isinstance(v, Literal))}
    iri = str(o)
    if prop in _PICTURES:
        return {"text": iri, "href": iri, "image": iri, "width": _PICTURES[prop]}
    label = graph.value(o, _SKOS_PREF) or graph.value(o, _LABEL)
    if label is None:
        return {"text": _curie(graph, o), "href": iri}
    # "Ultramarine (DD)": two paints share a name, as on the Annotate page
    return {"text": _picker_label(graph, o, label), "href": iri}


def certificate(graph: Graph, work_ns: str, ident: str) -> dict:
    """``ident`` may be a guid, a work IRI or anything ending in a guid, as
    the Groovy form allowed."""
    m = _GUID.search(str(ident))
    if not m:
        raise ToolError("bad_args", "give the work's GUID")
    work = URIRef(work_ns + m.group(1))
    if (work, None, None) not in graph:
        raise ToolError("not_found", f"no work {m.group(1)}")
    rows = []
    types = [t for t in graph.objects(work, _RDF_TYPE)]
    shown = [t for t in types if t != _CREATIVE_WORK] or types
    rows.append({"property": "type", "values": [_value(graph, "", t) for t in sorted(shown)]})
    by_prop: dict[str, list] = {}
    for p, o in graph.predicate_objects(work):
        if p in (_RDF_TYPE, _THE_TAG):
            continue
        by_prop.setdefault(str(p), []).append(o)
    for p in sorted(by_prop, key=lambda x: (_local(x).casefold(), x)):
        vals = sorted(by_prop[p], key=str)
        rows.append({"property": _local(p), "values": [_value(graph, p, o) for o in vals]})
    label = graph.value(work, _LABEL)
    return {"work": str(work), "guid": m.group(1),
            "title": str(label) if label is not None else m.group(1), "rows": rows}


def build_report_tools(*, layout=None, work_ns: str = "") -> list[Tool]:
    lay = layout or Layout.default()
    dirs = list(dict.fromkeys(lay.dir(k) for k in ("work_ttl", "provenance_ttl")))

    def _storage(fileops, storage_class=""):
        cls = str(storage_class).strip()
        if cls and not re.fullmatch(r"[A-Za-z][\w-]*", cls):
            raise ToolError("bad_args", f"not a storage class: {cls!r}")
        g = Graph()
        for d in dirs:
            g += _content_graph(fileops, d)
        rows = storage_rows(g, cls)
        return {"storage_class": cls, "rows": rows, "count": len(rows)}

    # names for concepts (the thesaurus) and for classes (the model)
    label_dirs = list(dict.fromkeys(lay.dir(k) for k in ("vocab_ttl", "model_ttl")))

    def _certificate(fileops, guid):
        if not work_ns:
            raise ToolError("unavailable", "no work namespace configured")
        g = Graph()
        for d in [*dirs, *label_dirs]:
            g += _content_graph(fileops, d)
        for prefix, ns in (("vad", _VAD), ("the", "http://visualartsdna.org/thesaurus/"),
                           ("work", work_ns), ("schema", "https://schema.org/")):
            g.bind(prefix, ns, replace=True)
        return certificate(g, work_ns, guid)

    def _registry(fileops, profile=""):
        g = Graph()
        for d in dirs:
            g += _content_graph(fileops, d)
        if not str(profile).strip():
            return {"profiles": registry_profiles(g)}
        return registry_rows(g, str(profile).strip())

    return [
        Tool(
            name="report.certificate",
            description=("A Certificate of Authenticity for one work: its title and "
                         "everything its record says, as Property / Value."),
            input_schema={
                "type": "object",
                "properties": {
                    "guid": {"type": "string",
                             "description": "The work's GUID (or anything ending in it)."},
                },
                "required": ["guid"],
                "additionalProperties": False,
            },
            handler=_certificate,
        ),
        Tool(
            name="report.registry",
            description=("The register of one artist profile's works (title, image, "
                         "QR code, year, description, by title); with no profile, "
                         "the profiles to choose from."),
            input_schema={
                "type": "object",
                "properties": {
                    "profile": {"type": "string", "default": "",
                                "description": "The artist profile's IRI; blank lists them."},
                },
                "required": [],
                "additionalProperties": False,
            },
            handler=_registry,
        ),
        Tool(
            name="report.storage",
            description=("The works in one storage class, in Disposition Identifier "
                         "order: DI, title, image. Blank class = the default (paper)."),
            input_schema={
                "type": "object",
                "properties": {
                    "storage_class": {"type": "string", "default": "",
                                      "description": "e.g. blender; blank for the default."},
                },
                "required": [],
                "additionalProperties": False,
            },
            handler=_storage,
        ),
    ]
