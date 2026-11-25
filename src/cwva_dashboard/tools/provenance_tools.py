"""The incipient provenance: a work's first custody record, and its DI.

The provenance plan is the specification. Everything a record says is derived, so
none of it is typed at the form:

* the **item id** is `max(vad:itemId) + 1`, one global counter;
* the **storage class** comes from the `vad:StorageSolution` records, most
  specific work type winning, and no match is the blank class (§2);
* the **owner** is the artist of the work's profile: an incipient record is the
  artist's own custody, and a sale is a later transfer record with no DI;
* the **event date** and the DI's year are the work's `schema:dateCreated` (§7).

**An item id is spent once per work** (§10.3). A re-submit of a draft finds the
record it already wrote and keeps its id, so going back to fix a typo does not
burn a number. Two records never share one: `provenance_gate` refuses that on the
way to the SOT, because this tool can only see one tree.
"""

from __future__ import annotations

import string
import uuid
from urllib.parse import quote

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, RDFS, XSD

from ..promotion.layout import Layout
from .base import Tool, ToolError
from .record_tools import SCHEMA, VAD, work_namespace
from .workflow_tools import _content_graph

__all__ = ["build_provenance_tools", "disposition_id", "file_location_iri",
           "new_incipient", "read_record", "storage_class_for"]


def storage_class_for(types, solutions: Graph, model: Graph | None) -> str:
    """The storage class a work's types resolve to; "" is the blank class.

    Walks up from each type a level at a time, so the nearest solution wins. The
    model is optional because a direct match needs no hierarchy.
    """
    by_type = {}
    for solution in solutions.subjects(RDF.type, VAD.StorageSolution):
        for work_type in solutions.objects(solution, VAD.hasWorkType):
            by_type[work_type] = str(solutions.value(solution, VAD.storageClass) or "")

    best: tuple[int, str] | None = None
    for start in types:
        level, seen, depth = {start}, set(), 0
        while level:
            found = sorted(by_type[c] for c in level if c in by_type)
            if found:
                if best is None or (depth, found[0]) < best:
                    best = (depth, found[0])
                break
            seen |= level
            level = ({p for c in level for p in model.objects(c, RDFS.subClassOf)} - seen
                     if model is not None else set())
            depth += 1
    return best[1] if best else ""


def file_location_iri(text: str) -> str:
    """The IRI for a definitive file, from what a person would paste.

    `G:\\My Drive\\art\\a.blend` becomes `file:///G:/My%20Drive/art/a.blend`:
    three slashes, because `file://G:/` makes the drive letter a HOST, and
    percent-encoding, because a raw space is the value `URIRef` accepts and the
    Turtle serializer then refuses (the provenance plan §3). An IRI already
    given is kept, if it is one.
    """
    raw = str(text).strip().strip('"')
    if not raw:
        raise ToolError("bad_args", "file location is empty")
    if "://" in raw:
        scheme, _, rest = raw.partition("://")
        if not scheme.isalpha() or any(c in rest for c in '<>" {}|\\^`'):
            raise ToolError("invalid_iri", f"{raw!r} is not a usable IRI: encode spaces as %20, "
                            "or paste the folder path instead")
        return raw
    path = raw.replace("\\", "/")
    if len(path) > 2 and path[1] == ":" and path[0] in string.ascii_letters and path[2] == "/":
        return "file:///" + path[:2] + quote(path[2:], safe="/")
    if path.startswith("/"):
        return "file://" + quote(path, safe="/")
    raise ToolError("bad_args", f"{raw!r} is not a full path: start it with a drive letter "
                    "(G:\\...) or a slash")


def disposition_id(storage_class: str, year: str, item: int) -> str:
    """`[<storage-class>.]<year>.<item>`, §2's grammar."""
    return f"{storage_class}.{year}.{item}" if storage_class else f"{year}.{item}"


def _next_item(provenance: Graph) -> int:
    used = [int(o) for o in provenance.objects(None, VAD.itemId)
            if str(o).isdigit()]
    return max(used, default=0) + 1


def read_record(fileops, folder: str, guid: str) -> Graph:
    """One record's file, or an empty graph when there is no such file."""
    g = Graph()
    try:
        g.parse(data=fileops.read_text(f"{folder.rstrip('/')}/{guid}.ttl"), format="turtle")
    except FileNotFoundError:
        pass
    return g


def new_incipient(fileops, work: str, *, work_dir: str, provenance_dir: str,
                  work_ns: Namespace, model: Graph | None = None,
                  file_location: str = "") -> dict:
    """Write the incipient provenance for ``work`` (a guid), or rewrite its own.

    Refuses rather than guesses: a DI cannot be recomputed later, so a record
    built from a missing date or owner would be wrong for good.
    """
    subject = work_ns[str(work)]
    # The two files this needs, not the whole data folder: reading that on a cold
    # cache spends the per-minute file quota and fails the submit.
    data = read_record(fileops, work_dir, str(work))
    label = data.value(subject, RDFS.label)
    if label is None:
        raise ToolError("not_found", f"no work {work} in {work_dir}")

    created = str(data.value(subject, SCHEMA.dateCreated) or "")
    year = created[:4]
    if not (len(year) == 4 and year.isdigit()):
        raise ToolError(
            "no_date",
            f"{label} has no schema:dateCreated, and a DI's year comes from it.")

    profile = data.value(subject, VAD.hasArtistProfile)
    owner = None
    if profile is not None:
        owner = read_record(fileops, work_dir, str(profile).rsplit("/", 1)[-1]).value(
            profile, VAD.artist)
        if owner is None:  # a profile in an aggregate file: the slower answer
            owner = _content_graph(fileops, work_dir).value(profile, VAD.artist)
    if owner is None:
        raise ToolError(
            "no_owner",
            f"{label} has no artist profile naming an artist, and that artist "
            "is the owner of an incipient provenance.")

    provenance = _content_graph(fileops, provenance_dir)
    mine = next((s for s in provenance.subjects(VAD.hasArtwork, subject)
                 if (s, VAD.dispositionId, None) in provenance), None)
    item = (int(provenance.value(mine, VAD.itemId)) if mine is not None
            else _next_item(provenance))
    guid = (str(mine).rsplit("/", 1)[-1] if mine is not None else str(uuid.uuid4()))

    storage_class = storage_class_for(
        set(data.objects(subject, RDF.type)), provenance, model)
    di = disposition_id(storage_class, year, item)
    # §10.7: a work in a named class is a file, and the file is the artifact. In
    # all 222 production records this agrees with the class exactly.
    record_class = VAD.FileProvenance if storage_class else VAD.Provenance

    uri = work_ns[guid]
    g = Graph()
    for prefix, ns in (("schema", SCHEMA), ("rdfs", RDFS), ("vad", VAD),
                       ("work", work_ns), ("xs", XSD)):
        g.bind(prefix, ns)
    g.add((uri, RDF.type, record_class))
    g.add((uri, RDFS.label, Literal(str(label))))
    g.add((uri, VAD.hasArtwork, subject))
    g.add((uri, VAD.hasArtworkOwner, URIRef(str(owner))))
    g.add((uri, VAD.dispositionId, Literal(di)))
    g.add((uri, VAD.itemId, Literal(item)))
    g.add((uri, SCHEMA.startDate, Literal(created[:10], datatype=XSD.date)))
    # The definitive file, for a work that IS a file (§3). Converted before
    # anything is written, so a path that cannot be an IRI refuses the record
    # rather than producing one the serializer rejects later.
    ignored = ""
    if file_location and not storage_class:
        ignored = file_location  # an object's provenance names no file
    elif file_location:
        g.add((uri, VAD.fileLocation, URIRef(file_location_iri(file_location))))
    elif mine is not None:
        # Kept from the earlier submit: the one fact not derived here.
        for location in provenance.objects(mine, VAD.fileLocation):
            g.add((uri, VAD.fileLocation, location))

    path = f"{provenance_dir.rstrip('/')}/{guid}.ttl"
    written = fileops.write_text(path, g.serialize(format="turtle"), make_parents=True)
    return {
        "path": written.path, "uri": str(uri), "disposition_id": di, "item_id": item,
        "storage_class": storage_class, "is_file": bool(storage_class),
        "owner": str(owner), "new": mine is None,
        "has_location": (uri, VAD.fileLocation, None) in g,
        "file_location": str(g.value(uri, VAD.fileLocation) or ""),
        "location_ignored": ignored,
    }


def build_provenance_tools(domain: str, *, layout=None, model=None) -> list[Tool]:
    lay = layout or Layout.default()
    work_ns = work_namespace(domain)

    def _handler(fileops, work, file_location=""):
        return new_incipient(
            fileops, work, work_dir=lay.dir("work_ttl"),
            provenance_dir=lay.dir("provenance_ttl"), work_ns=work_ns, model=model,
            file_location=file_location,
        )

    def _classes(fileops, types):
        # What a form needs to know before anything is entered: does this kind
        # of work get a file provenance, so should it ask where the file is.
        solutions = _content_graph(fileops, lay.dir("provenance_ttl"))
        return {"classes": {t: storage_class_for({VAD[t]}, solutions, model)
                            for t in types}}

    return [Tool(
        name="provenance.storage_class",
        description=("The storage class each work type resolves to; an empty one "
                     "is the blank class, and a named one means a file provenance."),
        input_schema={
            "type": "object",
            "properties": {"types": {"type": "array", "items": {"type": "string"},
                                     "description": "vad: class local names."}},
            "required": ["types"],
            "additionalProperties": False,
        },
        handler=_classes,
    ), Tool(
        name="provenance.new_incipient",
        description=(
            "Write a work's incipient provenance and allocate its Disposition "
            "Identifier. Everything is derived from the work, its artist profile "
            "and the storage solutions. Calling it again for the same work keeps "
            "the item id."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "work": {"type": "string", "description": "The work's guid."},
                "file_location": {
                    "type": "string",
                    "description": ("The definitive file of a digital work, as a path "
                                    "(G:\\My Drive\\...) or an IRI. Ignored for an object."),
                },
            },
            "required": ["work"],
            "additionalProperties": False,
        },
        handler=_handler,
    )]
