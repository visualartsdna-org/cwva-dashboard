"""Field-level editing of one instance's TTL (Rick's design, 2026-09-11).

**Editing is FILE-based, not instance-based.** A subject's triples are spread
across files — `work:abc` is described in `abc.ttl` and asserted to be on a site
in `workonsite_<site>.ttl` — so "edit this instance" has no single target. What
a user can coherently edit is one file.

That constraint turns out to be a feature. Because the editor renders
**everything in the file** and writes the whole file back, nothing can be
dropped by omission. A form-shaped editor would have to merge (the entry form
owns a minority of the predicates on a real work: 115 of 172 watercolours carry
something it does not know about), and a merge that forgets a predicate deletes
data silently. Here there is no field list to fall behind the data.

**What may be edited.** A file holding ONE named subject. Measured over the real
store: 326 of 334 data files qualify, and the 8 that do not are exactly the
aggregates and system output — `annotations.ttl`, `conceptQueue.ttl`,
`workonsite_*.ttl` and friends. So the rule is derived from the file rather than
kept in a list that drifts, and a newly generated aggregate is protected the day
it appears without anyone remembering to add it.

**Blank nodes.** Three kinds occur, and each gets the treatment its shape allows:

- **Labelled** (439 `schema:QuantitativeValue` dimensions, 1 other): rendered as
  their `rdfs:label` — "9 inches" — and parsed back into `schema:value` +
  `schema:unitCode` on save. The label is the whole content, so one field is
  faithful.
- **Unlabelled** (33 `vad:NFT`, 4 `measurementSystem`): READ-ONLY. Seven fields
  of NFT provenance have no faithful one-line summary, and inventing one would
  be a way to lose them.
- **Empty** (15 `the:document [ ]`, left by the Groovy's conditional emission):
  **dropped on save.** They carry nothing and only invite poking at.

The editor never silently loses structure it did not show: anything it cannot
render faithfully is preserved verbatim instead.
"""

from __future__ import annotations

import re

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SKOS, XSD

from .base import Tool, ToolError
# IMPORTED AT MODULE LEVEL, and that is load-bearing. Tool handlers run inside
# the Landlock-confined worker, which may read `sys.prefix` and /usr but NOT the
# project tree — an editable install lives outside both. So a first-party module
# imported lazily inside a handler is read from disk for the first time while
# confined, and the import fails with EACCES. Rick hit exactly that opening a
# record: "PermissionError: … property_map.py" (2026-09-16). Everything a tool
# handler can reach must be imported while the trusted parent is still building
# the registry.
from .property_map import COMPOSITE_VIDEO, PROPERTY_MAP

__all__ = ["build_edit_tools", "read_instance", "write_instance", "EDITABLE",
           "READ_ONLY", "WORKS", "ENTITIES", "group_of", "submitted_value"]

EDITABLE = "editable"
READ_ONLY = "read_only"

# The two groups the record picker offers. Named constants because the
# route, the tool schema and the toggle must agree on the spelling, and a
# fourth string literal is how an offered set stops matching an enforced one.
WORKS = "work"
ENTITIES = "entity"

# Literal datatype -> widget. The real store uses seven and no language tags, so
# the set is small by observation rather than by hope.
_WIDGETS = {
    str(XSD.date): "date",
    str(XSD.dateTime): "datetime",
    str(XSD.integer): "number",
    str(XSD.decimal): "number",
    str(XSD.float): "number",
    str(XSD.boolean): "boolean",
}

# Predicates worth a second look before changing. Not blocked — the user owns
# the data — but flagged, because these are the ones with consequences beyond
# the record.
_WARNINGS = {
    "https://schema.org/image":
        "Removing this does NOT delete the image from the SOT; it leaves it unreferenced.",
}

_RDF_TYPE = str(RDF.type)

#: How a field's SUB-fields are named in the form. A predicate is a URI and
#: never ends in `::<something>`, so one flat form namespace holds both without
#: a field ever colliding with a predicate. Used by a composite's own inputs
#: (the video description) and by one slot of a multi-valued file field.
_SUB = "::"

#: The file kinds a record cites BY NAME, where the name is the published URL. A
#: new version replaces the bytes and the name stays (Rick, 2026-11-05: "I'd
#: prefer not to rename an updated document").
DOCUMENT_KINDS = ("markdown", "pdf")

#: Prefixes a picker's option meaning "the drop-folder file with the name this
#: record ALREADY cites". The name alone cannot say it: the "unchanged" option
#: holds that same string, and a save cannot tell two equal strings apart. Only
#: `/edit/save` reads it, and it never reaches `write_instance`.
REPLACE_WITH = "replace::"


#: Characters `rdflib.term._is_valid_uri` refuses, and therefore the ones
#: that make a URIRef unserializable. Copied rather than imported: it is a
#: private name in rdflib, and the set is a spec constant, not a policy.
_INVALID_URI_CHARS = '<>" {}|\\^`'
# Predicates whose object NAMES something else — a profile, a background, a
# class. The CURIE is the system's handle for it and means nothing on screen
# (Rick, 2026-09-18: "these are the explicit values ... but are meaningless to
# the user"), so every one of them renders as a LABEL.
_PROFILE = "http://visualartsdna.org/model/hasArtistProfile"
_BACKGROUND = "http://visualartsdna.org/model/background"
_THE = "http://visualartsdna.org/thesaurus/"
_DATE_MODIFIED = URIRef("https://schema.org/dateModified")

# Predicates the editor shows but will not let you change, each with the reason
# said in the page rather than left to be inferred.
_SYSTEM_FIELDS = {
    _RDF_TYPE: (
        "The record's type is baked in: it decides which form created it, which "
        "gates apply, and how every reader interprets the rest of the record."
    ),
    str(_DATE_MODIFIED): (
        "Stamped by the editor on each save, newest last. A record's edit "
        "history is evidence, not a field."
    ),
    "https://schema.org/identifier": (
        "The record's GUID, and the tail of its URI. Changing it would orphan "
        "every reference to this work — tags, collections, the site's catalog "
        "links — while leaving them all looking valid."
    ),
    _PROFILE: (
        "The artist profile is baked in: it chose this form, these fields and "
        "their order, and it is how the work reaches its artist's branding. "
        "Changing it would describe the record with a template it was not made "
        "from."
    ),
    "http://visualartsdna.org/model/qrcode": (
        "Derived from the GUID at entry, and the QR image is generated to match. "
        "Editing the text cannot move the picture it points at."
    ),
}

def file_field_kinds(registry=None) -> dict:
    """predicate -> the inbox KIND that predicate's files come from.

    DERIVED from the record tools rather than listed: every form field carrying
    `x-file-ref` is joined to its predicate through `WORK_FIELD_PROPERTIES`. Add
    a file field to a form and the editor can offer it the same day, which is
    the point — "future associated files we decide to add to the mix" should not
    need a second table updated in step.

    `schema:video` is deliberately absent and cannot be derived: its file lives
    inside a blank node as `schema:contentUrl`, beside a thumbnail URL and a
    title that are COMPUTED from it. Swapping that file means recomputing three
    values together, which is a different operation from replacing a filename.
    Until that exists, the video file is read-only and says so.
    """
    from .fileops_tools import build_default_registry
    from .record_tools import WORK_FIELD_PROPERTIES

    reg = registry or build_default_registry(domain="http://example.invalid")
    out = {}
    for t in reg.schemas():
        if not t["name"].startswith("record.new_"):
            continue
        for fname, f in t["inputSchema"]["properties"].items():
            if "x-file-ref" not in f:
                continue
            pred = WORK_FIELD_PROPERTIES.get(fname)
            if pred:
                out[pred] = {"kind": f.get("x-file-kind", "image"),
                             "subtree": f["x-file-ref"]}
    return out


_UNIT_CODES = {  # label word -> schema:unitCode, from the entry form's own map
    "cm": "CTM", "inch": "INH", "inches": "INH",
    "meter": "MTR", "meters": "MTR", "pixel": "E37", "pixels": "E37",
}
_SCHEMA_VALUE = URIRef("https://schema.org/value")
_SCHEMA_UNITCODE = URIRef("https://schema.org/unitCode")
_SCHEMA_CONTENT_URL = URIRef("https://schema.org/contentUrl")
_SCHEMA_DESCRIPTION = URIRef("https://schema.org/description")

#: What a dimension's label accounts for. `rdfs:label "12 inches"` IS the
#: content of `schema:value 12` + `schema:unitCode "INH"`, and `rdf:type` is
#: entailed by the shape — so a node carrying only these can be edited through
#: its label without anything going unseen. 906 blank nodes in the real store
#: qualify. The other 43 do not: their label NAMES a structure ("Input Form
#: Spec", "gdoc source") rather than stating it, and offering those as a
#: one-line text box invites editing a whole form template through its title.
_LABEL_IS_CONTENT = {RDF.type, RDFS.label, _SCHEMA_VALUE, _SCHEMA_UNITCODE}

_SCHEMA_UPLOAD_DATE = URIRef("https://schema.org/uploadDate")
_SCHEMA_DURATION = URIRef("https://schema.org/duration")
_LABEL_RE = re.compile(r"^\s*(-?[\d.]+)\s+(\S+)\s*$")


def _curie(uri: str, prefixes: dict) -> str:
    for pfx, ns in prefixes.items():
        if uri.startswith(ns):
            return f"{pfx}:{uri[len(ns):]}"
    return uri


def _expand(value: str, prefixes: dict) -> URIRef:
    v = value.strip()
    if v.startswith("<") and v.endswith(">"):
        return URIRef(v[1:-1])
    if "://" in v:
        return URIRef(v)
    pfx, _, local = v.partition(":")
    if local and pfx in prefixes:
        return URIRef(prefixes[pfx] + local)
    return URIRef(v)


def _named_subjects(g: Graph) -> set:
    return {s for s in g.subjects() if not isinstance(s, BNode)}


def _is_editable(g: Graph) -> bool:
    """One named subject — see the module docstring. Derived, not listed."""
    return len(_named_subjects(g)) == 1


def read_instance(fileops, path: str, file_kinds: dict | None = None,
                  class_labels: dict | None = None, stores=(),
                  referents=None, annotation_props=()) -> dict:
    """The file's one subject, as fields a form can render.

    ``file_kinds`` (predicate -> {kind, subtree}) marks which fields name a FILE,
    so the UI can offer the drop folder instead of a free-text IRI.

    ``class_labels`` is the model's `rdfs:label` per class, resolved once when
    the registry was built — `vad:Watercolor` reads "Watercolor Painting".
    ``stores`` and ``referents`` are CALLABLES, invoked only when the record
    actually cites a reference: the stores return the content and vocabulary
    graphs (a record's own label, a concept's), the second the candidates a
    picker offers. Passing the work rather than the result keeps a record with
    no references from paying for the whole store.

    ``annotation_props`` are the predicates TCAP places concepts on. They are
    shown here and edited in Annotate Work (Rick, 2026-09-18) — the property a
    concept lands on is NAVIGATED from the ontology, so typing one in by hand
    is asserting an answer the system derives.
    """
    text = fileops.read_text(path)
    g = Graph()
    g.parse(data=text, format="turtle")
    prefixes = {p: str(n) for p, n in g.namespaces() if p}

    subjects = _named_subjects(g)
    if len(subjects) != 1:
        return {
            "path": path, "editable": False,
            "reason": (
                f"{len(subjects)} subjects in this file. Per-instance editing "
                "needs a file describing one thing; this is an aggregate or "
                "system output."
            ),
            "fields": [], "subject": "",
        }
    subject = next(iter(subjects))

    cache: dict = {}

    def label_of(uri: str) -> str:
        """The name a person would recognise: the model's for a class, the
        store's for a record, and the local name when neither has one."""
        if class_labels and uri in class_labels:
            return class_labels[uri]
        for i, source in enumerate(stores or ()):
            if i not in cache:
                cache[i] = source()
            found = cache[i].value(URIRef(uri), RDFS.label)
            if found:
                return str(found)
        return uri.rstrip("/").rsplit("/", 1)[-1].rsplit("#", 1)[-1]

    fields = []
    for pred in sorted(set(g.predicates(subject, None)), key=str):
        objects = list(g.objects(subject, pred))
        field = _field_for(g, pred, objects, prefixes, file_kinds or {},
                           label_of, referents, annotation_props)
        if field is not None:
            fields.append(field)
    group = group_of(g, subject)
    if group == ENTITIES:
        fields = sorted(fields + _absent_documents(g, subject, prefixes, file_kinds),
                        key=lambda f: f["predicate"])
    return {
        "path": path,
        "editable": True,
        "subject": _curie(str(subject), prefixes),
        "subject_uri": str(subject),
        # Which list this record belongs to, so the caller never has to trust
        # a `?kind=` it was handed. See `group_of`.
        "group": group,
        "fields": fields,
    }


def _absent_documents(g: Graph, subject, prefixes: dict, file_kinds) -> list:
    """Empty pickers for the documents this ENTITY does not cite yet.

    The editor otherwise renders only the predicates a file has, so a document
    left out at entry could never be added (Rick, 2026-11-05). This is the one
    exception to "changing and clearing, not creating", and it is narrow: the
    entity form offers these fields, and an unpicked one writes nothing.
    """
    absent = []
    for pred, spec in (file_kinds or {}).items():
        if spec["kind"] not in DOCUMENT_KINDS or (subject, URIRef(pred), None) in g:
            continue
        absent.append({
            "predicate": pred, "curie": _curie(pred, prefixes),
            "label": pred.rsplit("/", 1)[-1].rsplit("#", 1)[-1],
            "warning": _WARNINGS.get(pred, ""), "mode": EDITABLE, "kind": "file",
            "file_kind": spec["kind"], "subtree": spec["subtree"],
            "multiple": False, "items": [], "value": "",
        })
    return absent


def bnodes_of(objects) -> list:
    return [o for o in objects if isinstance(o, BNode)]


def _composite_shape(pred: str) -> str:
    """The property map's shape for this predicate, when it builds a whole node
    from one file. Empty for everything else — this module does not otherwise
    consult the map, and should not start guessing."""
    prop = PROPERTY_MAP.get(pred)
    return prop.shape if prop is not None and prop.shape == COMPOSITE_VIDEO else ""


def _structure_of(g: Graph, node, prefixes: dict, depth: int = 3) -> str:
    """A read-only blank node as one line, nesting included.

    It used to print `o2` directly, so a nested blank node read as its rdflib
    id — `ops:field=N7a3f9c…`, which tells a person nothing and looks like
    corruption. Nested nodes are rendered inline in braces instead, to a small
    depth, because the point of this field is to SHOW what is being preserved
    rather than to pretend it is not there.
    """
    if depth <= 0:
        return "{...}"
    parts = []
    for p2, o2 in sorted(g.predicate_objects(node), key=lambda t: str(t[0])):
        shown = (_structure_of(g, o2, prefixes, depth - 1)
                 if isinstance(o2, BNode)
                 else (_curie(str(o2), prefixes) if isinstance(o2, URIRef) else str(o2)))
        parts.append(f"{_curie(str(p2), prefixes)}={shown}")
    return "{" + "; ".join(parts) + "}" if depth < 3 else "; ".join(parts)


def _field_for(g: Graph, pred, objects, prefixes, file_kinds=None,
               label_of=None, referents=None, annotation_props=()) -> dict | None:
    name = _curie(str(pred), prefixes)
    base = {"predicate": str(pred), "curie": name,
            "label": str(pred).rsplit("/", 1)[-1].rsplit("#", 1)[-1],
            "warning": _WARNINGS.get(str(pred), "")}

    def shown(o) -> str:
        # A LABEL for anything that names something else, the plain text
        # otherwise. `rdf:type` read `vad:Watercolor` and now reads "Watercolor
        # Painting"; the profile reads its own name instead of a GUID.
        if not isinstance(o, URIRef):
            return str(o)
        return label_of(str(o)) if label_of else _curie(str(o), prefixes)

    if str(pred) in _SYSTEM_FIELDS:
        return {**base, "mode": READ_ONLY, "kind": "system",
                "reason": _SYSTEM_FIELDS[str(pred)],
                # `value` is what a PERSON reads; `uris` is what CODE resolves.
                # They separated the day the value became a label: the brander
                # was matching on `value` to find the record's profile, and a
                # label does not identify anything.
                "uris": [str(o) for o in sorted(objects, key=str)
                         if isinstance(o, URIRef)],
                "value": ", ".join(shown(o) for o in sorted(objects, key=str))}

    if (str(pred) in (annotation_props or ())
            and objects and all(isinstance(o, URIRef) and str(o).startswith(_THE)
                                for o in objects)):
        # AN ANNOTATION. Read-only here on purpose: the property a concept lands
        # on is navigated from the ontology (TCAP), so this field is an ANSWER,
        # and editing an answer by hand is how a record comes to disagree with
        # the model it was derived from. Annotate Work is where the question is
        # asked.
        return {**base, "mode": READ_ONLY, "kind": "annotation",
                "reason": "Annotations are edited in Annotate Work.",
                "uris": [str(o) for o in sorted(objects, key=str)],
                "value": ", ".join(shown(o) for o in sorted(objects, key=str))}

    if str(pred) == _BACKGROUND:
        # A CLOSED set, and the same one the entry form offers and the gate
        # checks (`referents.py`): a background is an ordinary record in the
        # store, so a free-text IRI here is a dangling reference waiting to
        # happen. Rick, 2026-09-18: "should only be edited with a select list
        # of backgrounds."
        current = [str(o) for o in objects if isinstance(o, URIRef)]
        return {**base, "mode": EDITABLE, "kind": "reference",
                "multiple": len(objects) > 1, "uris": current,
                "candidates": list(referents("backgrounds") if referents else []),
                "display": ", ".join(shown(o) for o in sorted(objects, key=str)),
                "value": ", ".join(_curie(u, prefixes) for u in current)}

    # A COMPOSITE node — `schema:video` — is one file wearing a whole node:
    # label, name and thumbnail are computed from the filename, uploadDate is
    # the day it arrived, duration is read from the file. It carries an
    # `rdfs:label`, so without this it fell into the labelled-blank-node branch
    # and rendered as a one-line text box. Two things followed (measured
    # 2026-09-14): the video file could not be changed at all, because the
    # filename lives in `schema:contentUrl` which that box never showed; and
    # editing the label left `schema:name` behind, so the node disagreed with
    # itself. The property map knows the shape — so ask it.
    spec = (file_kinds or {}).get(str(pred))
    composite = _composite_shape(str(pred))
    if composite and bnodes_of(objects):
        node = bnodes_of(objects)[0]
        content = g.value(node, _SCHEMA_CONTENT_URL)
        return {**base, "mode": EDITABLE, "kind": "file", "composite": composite,
                "file_kind": (spec or {}).get("kind", "video"),
                "subtree": (spec or {}).get("subtree", ""),
                "multiple": False,
                "value": str(content).rsplit("/", 1)[-1] if content else "",
                # THE PART OF A COMPOSITE THE USER OWNS (§14.7, deferred once).
                # Everything else on the node describes the FILE — label, name,
                # thumbnail, duration — and is recomputed when the file changes.
                # The description is the one thing a person says, and it was
                # preserved across a file swap but had nowhere to be typed, so
                # the only way to set it was to enter the work again.
                "parts": [{
                    "key": "description",
                    "name": f"{pred}{_SUB}description",
                    "label": "video description",
                    "kind": "textarea",
                    "value": str(g.value(node, _SCHEMA_DESCRIPTION) or ""),
                    "note": ("What the video is, in your words. Left empty, the "
                             "record describes it from what it knows."),
                }],
                "warning": ("Changing the FILE replaces the whole video "
                            "reference: its title, thumbnail and duration are "
                            "read from the file, not typed.")}

    bnodes = [o for o in objects if isinstance(o, BNode)]
    if bnodes:
        # Empty blank nodes are dropped by simply not offering them: the save
        # rebuilds from the fields, so anything unrendered and unpreserved goes.
        kept = [b for b in bnodes if list(g.predicate_objects(b))]
        if not kept:
            return None
        labels = [g.value(b, RDFS.label) for b in kept]
        # EDITABLE THROUGH THE LABEL only when the label IS the content. A
        # dimension qualifies: "12 inches" states the value and the unit, and
        # `rdf:type` is entailed by the shape. A node whose label NAMES a
        # structure does not — a profile's `ops:template` is labelled "Input
        # Form Spec", and offering that as a one-line text box invites editing
        # a whole form template through its title, then warns that it is not
        # "number unit" when you save. 906 real blank nodes are dimensions; the
        # 43 that are not were all being offered this way.
        if all(l is not None for l in labels) and all(
                set(g.predicates(b, None)) <= _LABEL_IS_CONTENT for b in kept):
            return {**base, "mode": EDITABLE, "kind": "bnode_label",
                    "multiple": len(kept) > 1,
                    "value": ", ".join(str(l) for l in labels)}
        # No faithful one-line form: show it, refuse to pretend it is editable.
        return {**base, "mode": READ_ONLY, "kind": "structure",
                "reason": ("This has no faithful one-line form, so it is shown "
                           "rather than risked."),
                "value": " | ".join(_structure_of(g, b, prefixes) for b in kept)}

    literals = [o for o in objects if isinstance(o, Literal)]
    if literals:
        dts = {str(o.datatype) if o.datatype else "" for o in literals}
        kind = _WIDGETS.get(next(iter(dts)), "text") if len(dts) == 1 else "text"
        multiline = any("\n" in str(o) or len(str(o)) > 80 for o in literals)
        return {**base, "mode": EDITABLE,
                "kind": "textarea" if (multiline and kind == "text") else kind,
                "datatype": next(iter(dts)) if len(dts) == 1 else "",
                # ARITY IS A PROPERTY OF THE DATA, not of the text. A single
                # value may legitimately contain commas — `schema:location
                # "Woodstock, GA"` — and splitting it made two literals out of
                # one address on 194 of 326 records, during a save that changed
                # nothing. A field that held one object writes back one object.
                "multiple": len(literals) > 1,
                "value": ", ".join(str(o) for o in literals) if len(literals) > 1
                         else str(literals[0])}

    spec = (file_kinds or {}).get(str(pred))
    if spec:
        # A FILE reference. Offered from the drop folder only — everything
        # already in the store got there by being associated with some record,
        # so pointing at one is a collision waiting to happen (and it passes
        # every gate, because the file genuinely exists). The remedy for a wrong
        # image is a NEW file, and the drop folder is where new files are.
        names = [str(o).rsplit("/", 1)[-1] for o in sorted(objects, key=str)]
        return {**base, "mode": EDITABLE, "kind": "file",
                "file_kind": spec["kind"], "subtree": spec["subtree"],
                "multiple": len(objects) > 1,
                # ONE SLOT PER FILE. A field holding two images rendered as a
                # single select whose only option was both names joined, so
                # choosing a replacement swapped BOTH for one — silently, and
                # the entity form writes a list of images, so this is reachable
                # the moment a record has two.
                # Only when there IS more than one: a single-valued field keeps
                # the predicate as its form name, so nothing that already works
                # has to learn a new spelling for the common case.
                "items": ([{"name": f"{pred}{_SUB}{i}", "value": n}
                           for i, n in enumerate(names)]
                          if len(names) > 1 else []),
                "value": ", ".join(names)}

    return {**base, "mode": EDITABLE, "kind": "iri", "multiple": len(objects) > 1,
            "value": ", ".join(_curie(str(o), prefixes) for o in objects)}


def _looks_like_reference(part: str, prefixes: dict) -> bool:
    """Is this fragment a reference in its own right — a CURIE or an absolute IRI?

    The question a comma-separated list of references has to answer, one part at
    a time. `work:abc` and `https://example.org/x` are references; the tail of a
    text-fragment URL (`-Joachim%20Patinier&text=…`) is not.
    """
    v = part.strip()
    if not v or any(c in v for c in _INVALID_URI_CHARS):
        return False
    if v.startswith("<") and v.endswith(">"):
        return True
    if "://" in v:
        return True
    pfx, sep, local = v.partition(":")
    return bool(sep and local and pfx in prefixes)


def _reference_parts(text: str, prefixes: dict) -> list:
    """Split a reference field on commas — but ONLY when every part is a
    reference.

    Arity is a property of the DATA for literals, because `schema:location
    "Woodstock, GA"` is one address and splitting it made two (see `_field`).
    Applying that same rule to IRIs had a different consequence: `the:tag`
    holding one value could never be given a second, and Rick's nine background
    CURIEs went in as ONE IRI with eight commas in it (2026-09-28). That is
    legal enough to parse and legal enough to serialize, so it was written,
    committed and converged to the real SOT before anything complained — the
    same shape of fault as a relative IRI.

    A comma is a legal URI character, so an unconditional split is not the
    answer either: 29 IRIs in the real store carry commas, all of them
    `#:~:text=` fragment links into Getty and Wikipedia. The discriminator is
    what the PARTS are. Every part a reference means the user typed a list;
    anything else means the comma belongs to the value, and the text is taken
    whole exactly as before.
    """
    if "," not in text:
        return [text]
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if len(parts) > 1 and all(_looks_like_reference(p, prefixes) for p in parts):
        return parts
    return [text]


def _checked(uri: URIRef, field: dict) -> URIRef:
    """Refuse an IRI that cannot be serialized, HERE rather than four steps on.

    `URIRef` accepts anything; the Turtle serializer does not, and the gap
    between them is where a record gets written that can be parsed and not
    re-written. Rick's `the:tag` list typed with spaces after the commas raised
    a bare serializer exception out of a save; typed without them it silently
    became one nine-GUID IRI. Both are the same defect — a value that is not an
    IRI reaching a field that only holds IRIs — and it belongs to the field the
    user can see and fix.
    """
    bad = [c for c in _INVALID_URI_CHARS if c in str(uri)]
    if bad and field.get("kind") == "file":
        # A file field holds file names picked from a list. "One per comma" is
        # the rule for a typed reference, and said here it reads as permission
        # to cite several documents (Rick, 2026-11-05).
        raise ToolError(
            "invalid_iri",
            f"{field.get('label') or field.get('curie', 'This field')}: "
            f"{str(uri)!r} is not a usable file reference — it contains "
            f"{' '.join(bad)!r}.",
        )
    if bad:
        raise ToolError(
            "invalid_iri",
            f"{field.get('label') or field.get('curie', 'This field')}: "
            f"{str(uri)!r} is not a valid IRI — it contains {' '.join(bad)!r}. "
            "References go in one per comma, as a CURIE (work:abc) or a full "
            "URL, with no spaces inside one.",
        )
    return uri


def _objects_from(field: dict, raw: str, prefixes: dict) -> list:
    """Parse one field's submitted text back into RDF objects.

    Comma separation applies to fields the DATA says are multi-valued, and to
    reference fields whose parts are each a reference — see `_reference_parts`
    for why those are two different rules rather than one.
    """
    kind, dt = field.get("kind"), field.get("datatype") or ""
    text = str(raw).strip()
    if not text:
        return []
    parts = ([p.strip() for p in text.split(",") if p.strip()]
             if field.get("multiple") else [text])
    if kind == "file":
        base = field.get("base") or ""
        return [_checked(URIRef(p if "://" in p else base + p), field)
                for p in parts]
    if kind in ("iri", "reference"):
        # A reference field splits on its own terms: a single-valued one can be
        # given a second value, which the literal rule cannot allow.
        parts = _reference_parts(text, prefixes)
        return [_checked(_expand(p, prefixes), field) for p in parts]
    if dt:
        return [Literal(p, datatype=URIRef(dt)) for p in parts]
    return [Literal(p) for p in parts]


def _same_number(literal, text: str) -> bool:
    try:
        return float(str(literal)) == float(text)
    except (TypeError, ValueError):
        return False


def _copy_subtree(new: Graph, old: Graph, node) -> None:
    """Copy a blank node's triples AND everything those triples reach.

    Preservation used to go exactly one level down — `for p2, o2 in
    old.predicate_objects(o)` — which is faithful for the two shapes the
    editor was written against: a `schema:QuantitativeValue` dimension and a
    `vad:NFT` node are flat. It is not faithful for anything deeper, and a
    profile's `ops:template` is: a list of `ops:field` blank nodes, each with
    its own properties, hung off a node that is itself blank.

    Measured on the real store (2026-09-28): a no-op save on an artist-profile
    record through the generic editor wrote back **29 of its 78 triples**. The
    file parsed, the gates passed, and the template was gone.

    **Preserving is the right answer, not refusing.** The editor's rule is that
    anything it cannot render faithfully is kept verbatim — and verbatim means
    the whole structure, however deep. Refusing the record would also block
    editing its label, which is a thing a person may legitimately want to do to
    a record whose internals they must not touch.

    Cycles terminate on `seen`: RDF permits a blank node to reach itself, and a
    profile template is a chain rather than a tree.
    """
    frontier, seen = [node], set()
    while frontier:
        cur = frontier.pop()
        if cur in seen:
            continue
        seen.add(cur)
        for p2, o2 in old.predicate_objects(cur):
            new.add((cur, p2, o2))
            if isinstance(o2, BNode):
                frontier.append(o2)


def _rebuild_bnode(new: Graph, old: Graph, subject, pred, label: str,
                   original: BNode | None) -> str:
    """Re-make a labelled blank node from its label. Returns "" or a warning.

    Everything the label does NOT carry — `rdf:type`, anything else hung on the
    node — is copied from the original, read out of the OLD graph. Reading it
    from the graph being built loses it silently, which is what happened the
    first time: `a schema:QuantitativeValue` vanished on every save.

    `schema:value` is only rewritten when the NUMBER actually changed. Deriving
    it unconditionally turned `"9"` into `"9.0"` on a no-op save — semantically
    equal, textually a diff, and a save that changes the file without the user
    changing anything is a save you cannot trust.
    """
    bn = BNode()
    new.add((subject, pred, bn))
    new.add((bn, RDFS.label, Literal(label)))
    derived = {RDFS.label, _SCHEMA_VALUE, _SCHEMA_UNITCODE}
    if original is not None:
        for p2, o2 in old.predicate_objects(original):
            if p2 not in derived:
                new.add((bn, p2, o2))
                # Whatever hangs off a carried property comes with it. A
                # dimension node is flat, but this branch is reached by any
                # labelled node, and a label is no promise of flatness.
                if isinstance(o2, BNode):
                    _copy_subtree(new, old, o2)

    orig_value = old.value(original, _SCHEMA_VALUE) if original is not None else None
    orig_unit = old.value(original, _SCHEMA_UNITCODE) if original is not None else None

    m = _LABEL_RE.match(label)
    code = _UNIT_CODES.get(m.group(2).lower()) if m else None
    if not (m and code):
        # Unparseable label: carry the old value/unit rather than drop them, and
        # say so. Dropping loses data; deriving nothing from an unreadable label
        # and staying quiet would leave the node disagreeing with its own label.
        if orig_value is not None:
            new.add((bn, _SCHEMA_VALUE, orig_value))
        if orig_unit is not None:
            new.add((bn, _SCHEMA_UNITCODE, orig_unit))
        return (
            f"{label!r} is not 'number unit' (e.g. '9 inches'), so its value and "
            "unit were left as they were"
        )

    new.add((bn, _SCHEMA_UNITCODE, Literal(code)))
    if orig_value is not None and _same_number(orig_value, m.group(1)):
        new.add((bn, _SCHEMA_VALUE, orig_value))  # unchanged: keep it verbatim
    else:
        new.add((bn, _SCHEMA_VALUE, Literal(m.group(1), datatype=XSD.float)))
    return ""


def _rebuild_composite(new: Graph, old: Graph, subject, pred, filename: str,
                       image_base: str, derived: dict, said: dict | None = None,
                       work_label: str = "", type_local: str = "") -> None:
    """Re-make a composite node (`schema:video`) around a new file.

    What is DERIVED is recomputed — label, name, thumbnail URL, contentUrl —
    because those describe the file and the file has changed. What the user
    SAID is carried over: the description they typed, and the uploadDate, which
    records when this work's video entered the record rather than when the file
    was last swapped.

    The duration is recomputed only when the trusted layer supplied one. Keeping
    a stale duration would be worse than having none: a player told the wrong
    length is a defect the record vouches for.
    """
    from .record_tools import _add_video

    originals = [o for o in old.objects(subject, pred) if isinstance(o, BNode)]
    original = originals[0] if originals else None
    keep_description = old.value(original, _SCHEMA_DESCRIPTION) if original else None
    # WHAT THE USER SAID WINS, including saying nothing: clearing the box falls
    # back to the description the record derives from what it knows, which is
    # the same rule entry applies ("typed beats derived"). There is no way to
    # have no description at all, and that is deliberate — the concern was
    # always that it be MISSING, never that it be unspecific.
    if said and "description" in said:
        keep_description = said["description"].strip() or None
    keep_upload = old.value(original, _SCHEMA_UPLOAD_DATE) if original else None
    old_content = old.value(original, _SCHEMA_CONTENT_URL) if original else None
    unchanged = (old_content is not None
                 and str(old_content).rsplit("/", 1)[-1] == filename)

    duration = derived.get("duration")
    if unchanged and not duration and original is not None:
        duration = old.value(original, _SCHEMA_DURATION)

    _add_video(
        new, subject, image_base, filename,
        description=str(keep_description) if keep_description else None,
        duration=str(duration) if duration else None,
        upload_date=str(keep_upload) if keep_upload else None,
        work_label=work_label, type_local=type_local,
    )


def submitted_value(field: dict, values: dict) -> str:
    """One field's submitted text, however the form spelled it.

    A multi-valued file field posts one name per SLOT, because a single select
    over two images could only offer both names joined and would swap both for
    whichever one was chosen. The slots are re-joined here into the comma list
    the field has always carried, so nothing downstream needs to know.
    """
    items = field.get("items")
    if not items:
        return values.get(field["predicate"], field["value"])
    picked = [str(values.get(it["name"], it["value"])).strip() for it in items]
    return ", ".join(p for p in picked if p)


def _mis_stored(field: dict, old, subject, pred, prefixes: dict) -> bool:
    """Does the file disagree with what its own rendering now parses to?

    The verbatim rule (below) protects an untouched field from being re-derived
    from its own display, which is where `"9"` becomes `"9.0"`. It also,
    inadvertently, protected a value that was WRONG: the Prestress Images
    collection holds nine background references as one IRI with eight commas in
    it, so opening that record and saving it preserved the defect, and only
    retyping the field could clear it.

    Narrow on purpose, and measured rather than assumed. It applies to
    reference fields only, where the round trip — IRI to CURIE and back — is
    exact: across both real stores, **2,828 of 2,829** reference fields re-parse
    to precisely the objects on disk, and the one that does not is the record
    this is for. So a disagreement here means the file is wrong, not that the
    rendering is lossy.
    """
    if field.get("kind") not in ("iri", "reference"):
        return False
    stored = sorted(str(o) for o in old.objects(subject, pred))
    try:
        reparsed = sorted(str(o) for o in _objects_from(field, field["value"], prefixes))
    except ToolError:
        return False  # unparseable is a refusal at the field, not a repair here
    return stored != reparsed


def write_instance(fileops, path: str, values: dict, file_kinds: dict | None = None,
                   image_base: str = "", documents_base: str = "",
                   derived: dict | None = None,
                   validate_only: bool = False) -> dict:
    """Rewrite the instance file from edited field values.

    Rebuilds the subject's triples from what was submitted, preserving anything
    the editor rendered READ-ONLY verbatim. The file is overwritten whole — safe
    precisely because the editor showed the whole file.

    ``validate_only`` does everything except the write, so the caller can learn
    the save would be refused BEFORE copying a file in for it. A refused save
    used to leave its file staged, where the next approval distributed it.
    """
    current = read_instance(fileops, path, file_kinds)
    if not current["editable"]:
        raise ToolError("not_editable", current["reason"])
    # Facts about a FILE that this tool cannot read for itself — the video
    # duration comes from ffprobe and the confined worker has no exec (law 2),
    # so the trusted layer probes and passes the answer in, exactly as the entry
    # route does. `{predicate: {"duration": "PT34S"}}`.
    derived = derived or {}

    old = Graph()
    old.parse(data=fileops.read_text(path), format="turtle")
    prefixes = {p: str(n) for p, n in old.namespaces() if p}
    subject = URIRef(current["subject_uri"])
    by_pred = {f["predicate"]: f for f in current["fields"]}

    new = Graph()
    for p, n in old.namespaces():
        new.bind(p, n)
    # Triples about anything other than the subject (there are none in an
    # editable file, but a bnode's own triples are re-added below).
    changed, dropped, warnings = [], [], []

    for pred_uri, field in by_pred.items():
        pred = URIRef(pred_uri)
        if field["mode"] == READ_ONLY:
            for o in old.objects(subject, pred):
                new.add((subject, pred, o))
                if isinstance(o, BNode):
                    _copy_subtree(new, old, o)
            continue

        if field.get("kind") == "file":
            # Which base a bare filename joins depends on where the file lives.
            field = {**field,
                     "base": documents_base if field.get("file_kind") in ("markdown", "pdf")
                     else image_base}
        # A field may arrive in SLOTS — one select per file of a multi-valued
        # file field — and the rest of the pipeline wants the one joined value
        # it has always had. Joined here, at the single point where submitted
        # text becomes a field's value, so the collision check, the untouched
        # comparison and `_objects_from` all see the same thing.
        raw = submitted_value(field, values)
        said = {part["key"]: str(values.get(part["name"], part["value"]))
                for part in field.get("parts") or []}
        parts_changed = any(
            said[part["key"]].strip() != str(part["value"]).strip()
            for part in field.get("parts") or []
        )
        if (str(raw).strip() == str(field["value"]).strip() and not parts_changed
                and not _mis_stored(field, old, subject, pred, prefixes)):
            # UNTOUCHED: copy the objects across exactly as they were, rather
            # than re-deriving them from their own rendering. Round-tripping a
            # value through a widget and back is where silent change comes from
            # — `"9"` becoming `"9.0"`, a label reconciled against a value the
            # user never saw. A save must change only what was edited.
            for o in old.objects(subject, pred):
                new.add((subject, pred, o))
                if isinstance(o, BNode):
                    _copy_subtree(new, old, o)
            continue
        if str(raw).strip() == str(field["value"]).strip() and not parts_changed:
            # MIS-STORED, and therefore not untouched. Said out loud at the
            # review, because a save the user thinks changed nothing has just
            # changed one field and they are about to distribute it.
            warnings.append(
                f"{field['curie']}: was stored as ONE reference containing "
                f"commas, and has been separated into "
                f"{len(_objects_from(field, raw, prefixes))}."
            )
        changed.append(field["curie"])
        if not str(raw).strip():
            dropped.append(field["curie"])
            continue

        if field["kind"] == "bnode_label":
            originals = [o for o in old.objects(subject, pred) if isinstance(o, BNode)]
            for i, label in enumerate([p.strip() for p in str(raw).split(",") if p.strip()]):
                note = _rebuild_bnode(new, old, subject, pred, label,
                                      originals[i] if i < len(originals) else None)
                if note:
                    warnings.append(f"{field['curie']}: {note}")
            continue

        if field.get("composite"):
            # The work's own label and type, because a cleared description is
            # DERIVED from them ("Video of the Blender Composition …") rather
            # than left absent. Taken from what was submitted where the user is
            # renaming the work in the same save, so the sentence does not
            # describe the record by the name it just stopped having.
            label_now = str(values.get(str(RDFS.label),
                                       old.value(subject, RDFS.label) or ""))
            types = [str(o).rsplit("/", 1)[-1].rsplit("#", 1)[-1]
                     for o in old.objects(subject, RDF.type)]
            _rebuild_composite(new, old, subject, pred, str(raw).strip(),
                               image_base, derived.get(str(pred)) or {},
                               said=said, work_label=label_now,
                               type_local=types[0] if types else "")
            continue

        for obj in _objects_from(field, raw, prefixes):
            new.add((subject, pred, obj))

    # Every save stamps `schema:dateModified`, newest last. It ACCUMULATES
    # rather than replacing: a record edited twice carries two stamps, which is
    # the edit history the file itself would otherwise not record — the QA git
    # has it, but the record travelling to SOT does not.
    #
    # Appended after the field loop so it cannot be edited away in the same
    # save that adds it, and typed xs:dateTime because `dateModified` takes a
    # moment, not a day.
    #
    # Sub-second precision is kept deliberately. Truncating to the second reads
    # better, but two saves within one second produce identical literals — and
    # RDF is a set, so the second edit would silently leave no trace. A stamp
    # that vanishes when you edit quickly is worse than an ugly one.
    from datetime import datetime, timezone

    new.add((subject, _DATE_MODIFIED,
             Literal(datetime.now(timezone.utc).isoformat(), datatype=XSD.dateTime)))

    # Empty blank nodes are simply never re-added: read_instance does not offer
    # them and nothing above preserves them.
    serialized = new.serialize(format="turtle")
    if validate_only:
        return {"path": path, "valid": True}
    res = fileops.write_text(path, serialized)
    return {
        "path": res.path,
        "subject": current["subject"],
        "changed": sorted(set(changed)),
        "cleared": sorted(set(dropped)),
        "warnings": warnings,
        "stamped": str(new.value(subject, _DATE_MODIFIED)),
        "triples": len(new),
    }


def build_edit_tools(*, layout=None, model=None, domain: str = "") -> list[Tool]:
    from ..promotion.layout import Layout
    from .record_tools import art_form_names

    lay = layout or Layout.default()
    data_dir = lay.dir("work_ttl")
    # Resolved once, at registry build, from the model the rest of the registry
    # was built with — not per call, and not from a list kept here.
    art_forms = art_form_names(model)
    # Every `rdfs:label` the model carries, so a class shows as "Watercolor
    # Painting" rather than `vad:Watercolor`. Resolved here, with the model in
    # hand, because the handler runs confined and has only the sandbox.
    class_labels = {}
    if model is not None:
        for subj, lab in model.subject_objects(RDFS.label):
            if isinstance(subj, URIRef):
                class_labels[str(subj)] = str(lab)

    # The predicates a concept can land on: an `owl:ObjectProperty` with an
    # `rdfs:range`, which is exactly what TCAP matches a concept's type against.
    # `the:tag` is deliberately range-less in the thesaurus ("removed to avoid
    # any implications"), so a tag is not swept up as an annotation — which is
    # right: a tag may point at anything and is the user's own text.
    annotation_props = set()
    if model is not None:
        for prop in model.subjects(RDF.type, OWL.ObjectProperty):
            if model.value(prop, RDFS.range) is not None:
                annotation_props.add(str(prop))

    vocab_dir = lay.dir("vocab_ttl")

    def _read(fileops, path, file_kinds=None, data_dir=data_dir):
        from .record_tools import _list_referents, work_namespace
        from .workflow_tools import _content_graph

        return read_instance(
            fileops, path, file_kinds, class_labels,
            # Records first, then the thesaurus: a concept's label lives in the
            # vocabulary, a profile's and a background's in the content.
            stores=(lambda: _content_graph(fileops, data_dir),
                    lambda: _content_graph(fileops, vocab_dir)),
            referents=lambda name: _list_referents(
                fileops, name, work_namespace(domain or ""), data_dir,
            )["candidates"] if domain else [],
            annotation_props=annotation_props,
        )

    return [
        Tool(
            name="record.read_instance",
            description=(
                "Read one instance TTL as editable fields. Refuses files holding "
                "more than one named subject (aggregates and system output)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Sandbox-relative .ttl."},
                    "file_kinds": {
                        "type": "object",
                        "description": "predicate -> {kind, subtree}; marks file fields.",
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            handler=_read,
        ),
        Tool(
            name="record.write_instance",
            description=(
                "Rewrite one instance TTL from edited field values. Preserves "
                "read-only structure verbatim and drops empty blank nodes."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Sandbox-relative .ttl."},
                    "values": {
                        "type": "object",
                        "description": "predicate URI -> submitted text.",
                    },
                    "file_kinds": {
                        "type": "object",
                        "description": "predicate -> {kind, subtree}; marks file fields.",
                    },
                    "image_base": {"type": "string",
                                   "description": "URL base a bare image name joins."},
                    "documents_base": {"type": "string",
                                       "description": "URL base a bare document name joins."},
                    "derived": {
                        "type": "object",
                        "description": (
                            "predicate -> facts read FROM the file by the trusted "
                            "layer, e.g. {schema:video: {duration: PT34S}}. This "
                            "tool cannot exec (law 2), so a probe's answer arrives "
                            "as data."
                        ),
                    },
                    "validate_only": {
                        "type": "boolean",
                        "description": "Refuse or accept the values; write nothing.",
                    },
                },
                "required": ["path", "values"],
                "additionalProperties": False,
            },
            handler=write_instance,
        ),
        Tool(
            name="record.list_editable",
            description=("Records that may be edited: one named subject, either "
                         "typed as a vad:ArtForm subclass (kind=work) or in the "
                         "entities scheme (kind=entity)."),
            input_schema={
                "type": "object",
                "properties": {
                    "data_dir": {"type": "string", "description": "Records dir.",
                                 "default": data_dir},
                    "kind": {
                        "type": "string",
                        "enum": [WORKS, ENTITIES],
                        "default": WORKS,
                        "description": "Which GROUP to list; never both at once.",
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
            handler=lambda fileops, data_dir=data_dir, kind=WORKS: list_editable(
                fileops, data_dir, art_forms, kind=kind),
        ),
    ]


_DATE_PUBLISHED = URIRef("https://schema.org/datePublished")
_ENTITIES_SCHEME = URIRef("http://visualartsdna.org/thesaurus/entities")


def group_of(graph, subject) -> str:
    """Which of the two groups this record belongs to, read off the RECORD.

    The same `skos:inScheme the:entities` rule `list_editable` filters on, in
    one function so the list and the record cannot disagree about where a
    record lives.

    **Because the URL is not evidence.** `?kind=` is a hint anyone can type,
    omit or get wrong — the Drafts page omitted it — and a group taken from it
    renders the wrong tab, the wrong dropdown, and a dropdown whose selected
    option is NOT the record on screen, because the record is absent from the
    list it is being shown against. A browser then displays the first option
    instead, so Open navigates to an unrelated record while looking like it
    reopens this one (Rick, 2026-10-01: "I hit Open with the new entity showing
    and it brought up the entity for Pillars").
    """
    return (ENTITIES if (subject, SKOS.inScheme, _ENTITIES_SCHEME) in graph
            else WORKS)


def list_editable(fileops, data_dir: str, art_forms=None, kind: str = WORKS) -> dict:
    """Single-subject instance files of ONE group, by publication date.

    Reads through the shared per-file cache. Doing its own read-per-file cost
    334 fileops and blew the 600-per-minute quota on the first real page load —
    the fourth time that has happened here, each time because a new reader
    looped over the directory instead of asking the cache.

    ``art_forms`` is the ontology's answer to "which types are works"
    (`art_form_names`). ``None`` means the model could not classify anything,
    and the work list is then empty rather than everything: offering an artist
    record to a form built for works is worse than offering nothing.

    **Two groups, named, never merged** (Rick, 2026-09-27). The original rule
    was works-only, because "entities, artists and artist profiles do not belong
    in this picker" — and that stands for artists, which have editors of their
    own that know what a persona owns (CE_DESIGN §14.10). Entities are the case
    it was too strict for: the Pillars background image needed a new file and
    the only way in was typing `/edit/open?path=…` by hand.

    The editor itself never needed changing — it is file-based, renders
    everything in the file and preserves verbatim what it cannot render, which
    is exactly what an entity needs (`skos:inScheme`, `the:conceptsExtracted`
    and a `skos:note` are no entry form's fields). Only the LIST was closed.

    Membership is DERIVED, like the work rule: a work is typed as an
    `vad:ArtForm` subclass, an entity is `skos:inScheme the:entities` — which
    `record.new_entity` writes on every entity it makes and nothing else in the
    store carries (161 of production's records, none of them a work or an
    artist). A listed type set would drift the day a new entity type appears.
    """
    from .workflow_tools import file_graphs

    out = []
    for path, one in file_graphs(fileops, data_dir):
        subjects = _named_subjects(one)
        if len(subjects) != 1:
            continue
        s = next(iter(subjects))
        types = sorted(str(t).rsplit("/", 1)[-1].rsplit("#", 1)[-1]
                       for t in one.objects(s, RDF.type))
        if kind == ENTITIES:
            if group_of(one, s) != ENTITIES:
                continue
        elif not (art_forms and set(types) & art_forms):
            continue
        label = one.value(s, RDFS.label)
        published = one.value(s, _DATE_PUBLISHED)
        out.append({
            "path": path,
            "value": path,
            "label": str(label) if label else path.rsplit("/", 1)[-1],
            "types": types,
            # The picker's date order. `schema:datePublished` and not the file's
            # mtime, because the order has to be one the user can recognise
            # (Rick, 2026-09-18): mtime is when the SANDBOX last touched the
            # file, which a sync rewrites wholesale.
            "published": str(published) if published else "",
        })
    return {"records": sorted(out, key=lambda d: (d["label"].lower(), d["path"]))}
