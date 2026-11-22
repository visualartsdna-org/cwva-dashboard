"""The two records a new user makes before anything else: an artist, and a
profile for one of the things they make.

**These are the bootstrap, so they are hand-written and always will be.** Every
other entry form is generated from a profile's `ops:template` (CE_DESIGN §14) —
which cannot help here, because the first thing a new deployment has is no
profile at all. Two forms escape the generalisation on purpose, and only two.

The profile form is also the **form builder** Rick asked for: a property picker
with an order box each, which is exactly the shape of `ops:field [ops:property …
; ops:order … ; ops:required true]`. Everything is required for now
(2026-09-14), until there is somewhere sensible to put the checkbox.
"""

from __future__ import annotations

import uuid

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, RDFS, SKOS

from .base import Tool, ToolError
from .property_map import ALWAYS, HOUSEKEEPING, PROPERTY_MAP

__all__ = ["build_bootstrap_tools", "offerable_properties", "ARTIST_ROOT"]

SCHEMA = Namespace("https://schema.org/")
VAD = Namespace("http://visualartsdna.org/model/")
OPS = Namespace("http://visualartsdna.org/operations/")
FOAF = Namespace("http://xmlns.com/foaf/0.1/")

#: Artist classes are the subclasses of this, the same way a work's classes are
#: the subclasses of its template type's parent. `vad:Painter` and
#: `vad:DigitalArtist` are Rick's two; a deployment with none of either still
#: gets the root itself.
ARTIST_ROOT = "http://visualartsdna.org/model/VisualArtist"

#: Unit codes the dashboard can render a measurement label from. The same four
#: `record_tools._UNITS` writes, offered by CODE because the code is what the
#: profile stores and `profiles.UNIT_NAMES` is what turns it back into a word.
UNIT_CHOICES = ["INH", "CTM", "MTR", "E37"]


#: The properties a record needs for cwva-py's works browser to display it
#: correctly (Rick, 2026-09-17), in the order he gave, and NOT optional: the
#: builder ticks them and will not let them be unticked. A profile is free to
#: order them differently and free to add to them; it is not free to make a
#: record the browser cannot show.
MANDATORY_ORDER = (
    ("http://www.w3.org/2000/01/rdf-schema#label", 10),
    ("https://schema.org/description", 20),
    ("https://schema.org/dateCreated", 30),
    ("https://schema.org/datePublished", 40),
    ("https://schema.org/image", 50),
    # `rdf:type` is a must-have (Rick, 2026-09-17), and locking it closes a real
    # gap rather than only tidying the list: a template without it built a
    # perfectly good profile whose every record then failed at creation, because
    # `graph_from_template` refuses a template that cannot say what it makes.
    # The failure was as far as possible from the mistake.
    ("http://www.w3.org/1999/02/22-rdf-syntax-ns#type", 60),
)
MANDATORY = {p for p, _ in MANDATORY_ORDER}


def offerable_properties(model=None) -> list[dict]:
    """What a template may contain — the mandatory five first, then the rest
    alphabetically, each with a suggested position.

    **Described, not named.** The first cut listed `height — schema:height`,
    which tells an RDF-literate reader what they already know and everyone else
    nothing; the user typically is not RDF literate (Rick). A property's own
    `rdfs:label` and `rdfs:comment` say more, and say it in words: `height, the
    height of the work`. The model is the source, as it is for every caption on
    every form; where it is silent, the field name with its underscores opened
    out stands in.

    Derived from the property map, so a property added there becomes available
    to every new profile with no change here. Housekeeping is left out: it is
    written whatever the template says, so offering it would be offering a
    choice that changes nothing (CE_DESIGN §14.8).
    """
    from rdflib import URIRef
    from rdflib.namespace import RDFS

    def described(predicate: str, field: str) -> tuple:
        label, comment = None, None
        if model is not None:
            label = model.value(URIRef(predicate), RDFS.label)
            comment = model.value(URIRef(predicate), RDFS.comment)
        name = str(label) if label else field.replace("_", " ")
        if not comment:
            return name, name
        definition = str(comment).strip().rstrip(".")
        # Lower-cased to read as a clause after the comma — but NOT when the
        # first word is an acronym. "A description of a work" becomes "a
        # description of a work"; "URI reference to a file" must not become
        # "uRI reference to a file" (Rick, 2026-09-17). A word carrying a
        # capital anywhere but the front is a name or an initialism, and
        # neither is ours to recase.
        first = definition.split(" ", 1)[0]
        if not any(c.isupper() for c in first[1:]):
            definition = definition[:1].lower() + definition[1:]
        return name, f"{name}, {definition}"

    ranked, rest = [], []
    for predicate, prop in PROPERTY_MAP.items():
        if predicate in HOUSEKEEPING:
            continue
        name, shown = described(predicate, prop.field)
        row = {"value": predicate, "label": shown, "name": name,
               "mandatory": predicate in MANDATORY}
        if predicate in MANDATORY:
            row["order"] = dict(MANDATORY_ORDER)[predicate]
            ranked.append(row)
        else:
            rest.append(row)

    ranked.sort(key=lambda r: r["order"])
    # The rest alphabetically, after the mandatory block, in tens — tens so a
    # field can be slipped between two later without renumbering the rest.
    rest.sort(key=lambda r: r["name"].lower())
    first_free = max(o for _, o in MANDATORY_ORDER) + 10
    for i, row in enumerate(rest):
        row["order"] = first_free + i * 10
    return [*ranked, *rest]


def _new_artist(fileops, *, work_ns, dest_dir, type, name, guid=None, email="",
                homepage="", brand="", pseudonym_for=""):
    """The person or persona whose work this deployment records.

    `vad:brand` is what makes an image carry a signature (CE_DESIGN §14.5), and
    leaving it empty is a decision rather than an omission: an artist who
    declares no brand gets no stamp. It is offered as the bare domain the
    signature draws — `visualartsdna.org` — because that is the string that lands
    on the image.
    """
    guid = guid or str(uuid.uuid4())
    subj = work_ns[guid]
    g = Graph()
    for pfx, ns in (("vad", VAD), ("work", work_ns), ("schema", SCHEMA),
                    ("foaf", FOAF), ("skos", SKOS)):
        g.bind(pfx, ns)

    g.add((subj, RDF.type, VAD[str(type)]))
    g.add((subj, SCHEMA.identifier, Literal(guid)))
    # Both, and from one field. `rdfs:label` is what every picker in the
    # dashboard reads; `foaf:name` is what the vocabulary means by a person's
    # name. Storing one and deriving the other at read time would make the
    # record depend on which of the two a reader happens to know.
    g.add((subj, RDFS.label, Literal(name)))
    g.add((subj, FOAF.name, Literal(name)))
    if email:
        g.add((subj, FOAF.mbox, URIRef(email if ":" in email else f"mailto:{email}")))
    if homepage:
        g.add((subj, FOAF.homepage, _absolute(homepage)))
    if brand:
        g.add((subj, VAD.brand, Literal(brand.split("://", 1)[-1].strip("/"))))
    if pseudonym_for:
        g.add((subj, VAD.pseudonymFor, _expand_work(pseudonym_for, work_ns)))

    path = f"{str(dest_dir).rstrip('/')}/{guid}.ttl"
    res = fileops.write_text(path, g.serialize(format="turtle"), make_parents=True)
    return {"path": res.path, "guid": guid, "uri": str(subj), "triples": len(g)}


# WHAT THE ARTIST FORM OWNS — one table, read by the editor and written by both
# writers, so "what the form shows" and "what a save replaces" cannot drift.
# Everything NOT here is preserved verbatim on an edit: the personas in Rick's
# store carry `schema:creator` and `schema:identifier` that the form never asks
# about, and an editor that rebuilt the record from its own fields would delete
# them (CE_DESIGN §14.10).
ARTIST_OWNED = (
    ("name", RDFS.label),
    ("name", FOAF.name),
    ("email", FOAF.mbox),
    ("homepage", FOAF.homepage),
    ("brand", VAD.brand),
    ("pseudonym_for", VAD.pseudonymFor),
)

# WHAT AN EDIT MAY REPLACE — the same set minus the NAME (Rick, 2026-09-19).
# The name identifies the persona. Every work ever made under this artist is
# shown under it, on the site, on a certificate, in a registry printout, and the
# artist's `vad:brand` is already burned into the pixels of those works' images.
# Renaming is therefore a retroactive re-attribution wearing the clothes of a
# typo fix — the same reason a profile's artist cannot be changed (§14.10).
#
# IN THE SCHEMA, not merely on the form: a field the page renders read-only can
# still be posted by a stale tab or a hand-made request, and "what the form
# offers is what the system enforces" means the tool is where a constraint
# lives. `record.edit_artist` has no `name` argument at all.
ARTIST_EDITABLE = tuple((f, p) for f, p in ARTIST_OWNED if f != "name")


def _artist_subject(fileops, guid, dest_dir):
    """The one named subject of `<guid>.ttl`, and its graph. Refuses a file that
    is not one artist: the editor rewrites the file, and a file describing two
    things has no single record to edit."""
    path = f"{str(dest_dir).rstrip('/')}/{guid}.ttl"
    try:
        text = fileops.read_text(path)
    except (FileNotFoundError, NotADirectoryError):
        raise ToolError("not_found", f"no artist record at {path}") from None
    g = Graph()
    g.parse(data=text, format="turtle")
    named = [s for s in set(g.subjects()) if isinstance(s, URIRef)]
    named = [s for s in named if any(True for _ in g.predicate_objects(s))]
    subjects = sorted({s for s in named}, key=str)
    if len(subjects) != 1:
        raise ToolError(
            "not_editable",
            f"{len(subjects)} subjects in {path}; an artist record describes one.",
        )
    subj = subjects[0]
    types = {str(o).rsplit("/", 1)[-1] for o in g.objects(subj, RDF.type)}
    if not any(x.endswith("Artist") or x.endswith("Painter") for x in types):
        raise ToolError("not_editable",
                        f"{path} is not an artist record (types: {sorted(types)}).")
    return path, g, subj


def _read_artist(fileops, *, guid, dest_dir):
    """The artist record as the FORM'S OWN fields, ready to be rendered.

    The mapping from predicates back to field names lives here, beside the
    writer that made them, rather than in the route — the day `email` stops
    meaning `foaf:mbox` there is one place to change.
    """
    _path, g, subj = _artist_subject(fileops, guid, dest_dir)
    types = [str(o).rsplit("/", 1)[-1] for o in g.objects(subj, RDF.type)]
    artist_type = next((x for x in sorted(types)
                        if x.endswith("Artist") or x.endswith("Painter")), "")
    mbox = g.value(subj, FOAF.mbox)
    home = g.value(subj, FOAF.homepage)
    pseud = g.value(subj, VAD.pseudonymFor)
    return {
        "guid": guid,
        "uri": str(subj),
        "values": {
            "guid": guid,
            "type": artist_type,
            "name": str(g.value(subj, RDFS.label) or g.value(subj, FOAF.name) or ""),
            # Shown as typed, not as stored: the writer adds `mailto:` and the
            # form would otherwise ask the user to maintain it.
            "email": str(mbox).replace("mailto:", "", 1) if mbox else "",
            "homepage": str(home) if home else "",
            "brand": str(g.value(subj, VAD.brand) or ""),
            "pseudonym_for": str(pseud) if pseud else "",
        },
    }


def _edit_artist(fileops, *, work_ns, dest_dir, guid, type, email="",
                 homepage="", brand="", pseudonym_for=""):
    """Rewrite an artist record, keeping everything the form does not own.

    **The name is not an argument.** It identifies the persona, and every work
    ever made under this artist is shown under it (§14.10). Correcting a name
    means discarding the draft and creating the artist again, or — once it has
    been distributed — living with it.

    The type is REPLACED among artist types only. A record may carry others —
    `schema:Person`, a class from a vocabulary this deployment never wrote — and
    dropping them because the form offers one dropdown would be the same
    silent-deletion mistake in a smaller place.
    """
    path, g, subj = _artist_subject(fileops, guid, dest_dir)

    for _field, pred in ARTIST_EDITABLE:
        for o in list(g.objects(subj, pred)):
            g.remove((subj, pred, o))
    for o in list(g.objects(subj, RDF.type)):
        local = str(o).rsplit("/", 1)[-1]
        if local.endswith("Artist") or local.endswith("Painter"):
            g.remove((subj, RDF.type, o))

    g.add((subj, RDF.type, VAD[str(type)]))
    if email:
        g.add((subj, FOAF.mbox, URIRef(email if ":" in email else f"mailto:{email}")))
    if homepage:
        g.add((subj, FOAF.homepage, _absolute(homepage)))
    if brand:
        g.add((subj, VAD.brand, Literal(brand.split("://", 1)[-1].strip("/"))))
    if pseudonym_for:
        g.add((subj, VAD.pseudonymFor, _expand_work(pseudonym_for, work_ns)))

    res = fileops.write_text(path, g.serialize(format="turtle"), make_parents=True)
    return {"path": res.path, "guid": guid, "uri": str(subj), "triples": len(g),
            "name": str(g.value(subj, RDFS.label) or "")}


def _new_artist_profile(fileops, *, work_ns, dest_dir, label, artist, template_type,
                        unit_code, fields, guid=None, description="", note="",
                        measurement_note=""):
    """A profile, and the template that becomes its entry form.

    `fields` arrives as `predicate:order` pairs — the form builder's grid — and
    each becomes one `ops:field` blank node. Per-field blank nodes rather than a
    comma list, because `ops:templateFields a, b, c` in Turtle is three
    UNORDERED triples and a form whose field order depends on serialization is a
    form that reorders itself (CE_DESIGN §14.3).
    """
    guid = guid or str(uuid.uuid4())
    subj = work_ns[guid]

    # Checked here as well as at record time: the form cannot produce a bad
    # template (the mandatory ticks are locked) but a POST can, and a profile
    # that reads fine and then fails every record it drives is the worst of the
    # three places this could break. Shared with the EDITOR, so a template
    # cannot be created one way and edited into a shape creation would refuse.
    pairs = _validated_fields(fields, unit_code)

    g = Graph()
    for pfx, ns in (("vad", VAD), ("ops", OPS), ("work", work_ns),
                    ("schema", SCHEMA), ("skos", SKOS)):
        g.bind(pfx, ns)

    g.add((subj, RDF.type, VAD.ArtistProfile))
    g.add((subj, SCHEMA.identifier, Literal(guid)))
    g.add((subj, RDFS.label, Literal(label)))
    g.add((subj, VAD.artist, _expand_work(artist, work_ns)))
    if description:
        g.add((subj, SCHEMA.description, Literal(description)))
    if note:
        g.add((subj, SKOS.note, Literal(note)))

    ms = BNode()
    g.add((subj, VAD.measurementSystem, ms))
    g.add((ms, RDF.type, SKOS.Concept))
    # The CODE is the load-bearing part — it is what turns 12 into "12 inches"
    # on every record this profile makes. The note beside it is for a human.
    g.add((ms, SCHEMA.unitCode, Literal(unit_code)))
    if measurement_note:
        g.add((ms, SKOS.note, Literal(measurement_note)))

    tpl = BNode()
    g.add((subj, OPS.template, tpl))
    g.add((tpl, RDFS.label, Literal("Input Form Spec")))
    g.add((tpl, OPS.templateType, _expand_class(template_type)))
    for predicate, order in pairs:
        node = BNode()
        g.add((tpl, OPS.field, node))
        g.add((node, OPS.property, URIRef(predicate)))
        g.add((node, OPS.order, Literal(int(order))))
        # Everything required until a form builder offers the checkbox
        # (Rick, 2026-09-14). Written explicitly rather than left to default, so
        # the profile says what it means and a later default change does not
        # silently reinterpret records already written.
        g.add((node, OPS.required, Literal(True)))

    path = f"{str(dest_dir).rstrip('/')}/{guid}.ttl"
    res = fileops.write_text(path, g.serialize(format="turtle"), make_parents=True)
    return {"path": res.path, "guid": guid, "uri": str(subj), "triples": len(g),
            "fields": len(pairs)}


# WHAT THE PROFILE FORM OWNS on the profile subject. Everything else stays:
# the store's profiles carry `schema:sameAs`, `rdfs:comment`, `foaf:maker` and
# `schema:identifier`, and `vad:artist` is deliberately not editable at all
# (CE_DESIGN §14.10).
PROFILE_EDITABLE = (RDFS.label, SCHEMA.description, SKOS.note)


def _profile_subject(fileops, guid, dest_dir):
    path = f"{str(dest_dir).rstrip('/')}/{guid}.ttl"
    try:
        text = fileops.read_text(path)
    except (FileNotFoundError, NotADirectoryError):
        raise ToolError("not_found", f"no profile record at {path}") from None
    g = Graph()
    g.parse(data=text, format="turtle")
    subjects = sorted({s for s in set(g.subjects()) if isinstance(s, URIRef)
                       and any(True for _ in g.predicate_objects(s))}, key=str)
    if len(subjects) != 1:
        raise ToolError(
            "not_editable",
            f"{len(subjects)} subjects in {path}; a profile record describes one.")
    subj = subjects[0]
    if (subj, RDF.type, VAD.ArtistProfile) not in g:
        raise ToolError("not_editable", f"{path} is not an artist profile.")
    return path, g, subj


def _read_artist_profile(fileops, *, guid, dest_dir):
    """An existing profile as the profile form's own fields.

    `fields` comes back in the builder's own `predicate:order` encoding, which
    is what the grid posts — so the widget that writes a template is the widget
    that reads one, with no translation between them to get wrong.
    """
    _path, g, subj = _profile_subject(fileops, guid, dest_dir)
    tpl = g.value(subj, OPS.template)
    ms = g.value(subj, VAD.measurementSystem)

    pairs = []
    for node in (g.objects(tpl, OPS.field) if tpl is not None else ()):
        prop = g.value(node, OPS.property)
        order = g.value(node, OPS.order)
        if prop is not None and order is not None:
            pairs.append((str(prop), int(order)))
    ttype = g.value(tpl, OPS.templateType) if tpl is not None else None
    return {
        "guid": guid,
        "uri": str(subj),
        "artist": str(g.value(subj, VAD.artist) or ""),
        "values": {
            "guid": guid,
            "label": str(g.value(subj, RDFS.label) or ""),
            "description": str(g.value(subj, SCHEMA.description) or ""),
            "note": str(g.value(subj, SKOS.note) or ""),
            "template_type": (str(ttype).rsplit("/", 1)[-1].rsplit("#", 1)[-1]
                              if ttype is not None else ""),
            "unit_code": str(g.value(ms, SCHEMA.unitCode) or "") if ms is not None else "",
            "measurement_note": str(g.value(ms, SKOS.note) or "") if ms is not None else "",
            "fields": [f"{p}:{o}" for p, o in sorted(pairs, key=lambda x: x[1])],
        },
    }


def _edit_artist_profile(fileops, *, work_ns, dest_dir, guid, label, template_type,
                         unit_code, fields, description="", note="",
                         measurement_note=""):
    """Rewrite a profile, keeping what the form cannot say.

    **The template is edited, not replaced.** A field the builder cannot express
    — `ops:dependsOn`, which the Blender profile uses for the mutual
    image3d/background rule (§14.8b) — survives an edit to its order, because
    the existing `ops:field` node is reused rather than rebuilt. Regenerating the
    template from the grid would delete every such statement, and the grid has
    no way to put one back.

    **No artist argument.** Changing it re-attributes every work ever made under
    this profile, and the images already carry the old artist's brand (§14.10).

    Template edits apply to works made FROM NOW ON. Nothing validates an existing
    record against its profile's template, which is what makes that true rather
    than merely intended.
    """
    path, g, subj = _profile_subject(fileops, guid, dest_dir)
    pairs = _validated_fields(fields, unit_code)
    wanted = {p for p, _ in pairs}

    tpl = g.value(subj, OPS.template)
    if tpl is None:
        tpl = BNode()
        g.add((subj, OPS.template, tpl))
        g.add((tpl, RDFS.label, Literal("Input Form Spec")))

    existing = {}
    for node in list(g.objects(tpl, OPS.field)):
        prop = g.value(node, OPS.property)
        if prop is None or str(prop) not in wanted:
            # Dropped from the template. Its own statements go with it; nothing
            # else in the file points at a field node.
            for p2, o2 in list(g.predicate_objects(node)):
                g.remove((node, p2, o2))
            g.remove((tpl, OPS.field, node))
            continue
        existing[str(prop)] = node

    # A dependency on a property the template no longer carries can never be
    # satisfied, and `read_profile` refuses such a profile outright — so the
    # card would go dead on the next read. Refused here, where it can still be
    # explained.
    orphaned = []
    for node in existing.values():
        dep = g.value(node, OPS.dependsOn)
        if dep is not None and str(dep) not in wanted:
            prop = str(g.value(node, OPS.property))
            orphaned.append((prop, str(dep)))
    if orphaned:
        raise ToolError(
            "invalid_argument",
            "removing " + ", ".join(_field_name(d) for _p, d in orphaned)
            + " would strand a dependency: "
            + "; ".join(f"{_field_name(p)} is only asked for when {_field_name(d)} "
                        "is filled in" for p, d in orphaned)
            + ". A profile with a dependency it cannot satisfy fails to load.",
        )

    for pred, order in pairs:
        node = existing.get(pred)
        if node is None:
            node = BNode()
            g.add((tpl, OPS.field, node))
            g.add((node, OPS.property, URIRef(pred)))
            g.add((node, OPS.required, Literal(True)))
        for old_order in list(g.objects(node, OPS.order)):
            g.remove((node, OPS.order, old_order))
        g.add((node, OPS.order, Literal(int(order))))

    for old_type in list(g.objects(tpl, OPS.templateType)):
        g.remove((tpl, OPS.templateType, old_type))
    g.add((tpl, OPS.templateType, _expand_class(template_type)))

    for pred in PROFILE_EDITABLE:
        for o in list(g.objects(subj, pred)):
            g.remove((subj, pred, o))
    g.add((subj, RDFS.label, Literal(label)))
    if description:
        g.add((subj, SCHEMA.description, Literal(description)))
    if note:
        g.add((subj, SKOS.note, Literal(note)))

    ms = g.value(subj, VAD.measurementSystem)
    if ms is None:
        ms = BNode()
        g.add((subj, VAD.measurementSystem, ms))
        g.add((ms, RDF.type, SKOS.Concept))
    for o in list(g.objects(ms, SCHEMA.unitCode)):
        g.remove((ms, SCHEMA.unitCode, o))
    g.add((ms, SCHEMA.unitCode, Literal(unit_code)))
    for o in list(g.objects(ms, SKOS.note)):
        g.remove((ms, SKOS.note, o))
    if measurement_note:
        g.add((ms, SKOS.note, Literal(measurement_note)))

    res = fileops.write_text(path, g.serialize(format="turtle"), make_parents=True)
    return {"path": res.path, "guid": guid, "uri": str(subj), "triples": len(g),
            "fields": len(pairs)}


def _field_name(predicate: str) -> str:
    prop = PROPERTY_MAP.get(predicate)
    return prop.field if prop is not None else predicate


def _validated_fields(fields, unit_code) -> list:
    """The builder's grid, checked. Shared by the writer and the editor so a
    template cannot be created one way and edited into a shape the creator would
    have refused."""
    pairs = _parse_fields(fields)
    if not pairs:
        raise ToolError("missing_required",
                        "a template with no fields describes no form — pick the "
                        "properties this profile's records carry.")
    if unit_code not in UNIT_CHOICES:
        raise ToolError("invalid_argument",
                        f"unit must be one of {', '.join(UNIT_CHOICES)}")
    missing = [p for p in ALWAYS if p not in {q for q, _ in pairs}]
    if missing:
        raise ToolError(
            "missing_required",
            "a template must include " + ", ".join(
                PROPERTY_MAP[p].field for p in missing)
            + " — the class of thing being made and what to call it.",
        )
    unknown = [p for p, _ in pairs if p not in PROPERTY_MAP]
    if unknown:
        raise ToolError("invalid_argument",
                        "not properties this dashboard can render: " + ", ".join(unknown))
    clash = {o for _, o in pairs if [x for _, x in pairs].count(o) > 1}
    if clash:
        raise ToolError("invalid_argument",
                        f"two fields share the order {sorted(clash)} — the form "
                        "would show them in an arbitrary sequence")
    return pairs


def _parse_fields(fields) -> list:
    """`["https://schema.org/height:5", …]` -> `[(predicate, order)]`.

    One string per chosen property, because that is what a checkbox-plus-number
    grid can post without inventing a nested form encoding.
    """
    out = []
    for item in (fields if isinstance(fields, list) else [fields]):
        text = str(item).strip()
        if not text:
            continue
        predicate, _, order = text.rpartition(":")
        if not predicate or not order.strip().isdigit():
            raise ToolError("invalid_argument",
                            f"{text!r} is not a property and an order")
        out.append((predicate, int(order)))
    return sorted(out, key=lambda p: p[1])


def _absolute(url: str) -> URIRef:
    """A typed web address as an IRI that means the same thing everywhere.

    `bj.net` is a RELATIVE IRI, and a relative IRI in a published record
    resolves against whatever base the reader happens to use — which in this
    dashboard meant a record that parsed one way for the gates and threw for the
    preview, so an artist could be saved and then make every promotion fail
    (Rick, 2026-09-17). A person typing their own site rarely types the scheme,
    so the scheme is supplied rather than demanded.
    """
    text = str(url).strip()
    if "://" not in text and not text.startswith("mailto:"):
        text = f"https://{text}"
    return URIRef(text)


def _expand_work(value: str, work_ns) -> URIRef:
    text = str(value).strip()
    if "://" in text:
        return URIRef(text)
    return work_ns[text.partition(":")[2] or text]


def _expand_class(value: str) -> URIRef:
    text = str(value).strip()
    return URIRef(text) if "://" in text else VAD[text.partition(":")[2] or text]


def build_bootstrap_tools(domain: str, *, model=None, layout=None,
                          artists=()) -> list[Tool]:
    """The two hand-written record tools, bound to this deployment."""
    from functools import partial

    from ..promotion.layout import Layout
    from .record_tools import _type_field, subclass_closure, work_namespace

    lay = layout or Layout.default()
    dest_dir = lay.dir("work_ttl")
    work_ns = work_namespace(domain)

    artist_types = (subclass_closure(model, ARTIST_ROOT) if model is not None else None)
    type_spec = {"type": "string", "description": "The artist's class."}
    if artist_types:
        type_spec = {**type_spec, "enum": artist_types,
                     "description": "The artist's class, from the ontology."}

    # Which classes a profile may produce: everything the model calls an art
    # form. Narrower than "any class" and wider than one branch, because a
    # deployment's first profile has no sibling to take its cue from.
    work_types = (subclass_closure(model, "http://visualartsdna.org/model/VisualArtForm")
                  if model is not None else None)
    # THE BUILDER GRID, shared by the two profile forms. One spec, so what a
    # template can be created as and what it can be edited into cannot differ.
    profile_fields_spec = {
        "type": "array",
        "items": {"type": "string"},
        "x-template-fields": True,
        # Carried by the schema, derived from the property map. The values
        # posted are "<predicate>:<order>" pairs, so an items-enum cannot
        # express the closed set; the handler checks every predicate against
        # the map instead, which is the same set this offers.
        "x-options": offerable_properties(model),
        # `fields` names no ontology property, so there is no model wording to
        # defer to: the schema is the only source for what this field is called
        # and what it says.
        "x-caption": "Entry form builder — property and order",
        "description": (
            "Tick what these records carry; the number is where the field sits "
            "on the form, lowest first. Prefilled ten apart so you can insert "
            "one later without renumbering. The GUID, QR code and artist "
            "profile are always written and are not listed."
        ),
    }

    template_type_spec = {"type": "string",
                          "description": "The class of record this profile makes."}
    if work_types:
        template_type_spec = {**template_type_spec, "enum": work_types}

    # NOT an `x-entity-ref`. That would put artists in the referents table,
    # which is shared with the vocabulary gate — and the gate matches a type
    # EXACTLY, so `vad:Painter` would fail a `vad:VisualArtist` condition and
    # every profile would be reported as referencing a non-artist. The picker
    # gets an enum (what `validate_args` enforces) plus labels for display, so
    # the offered set is still the enforced set without claiming a gate
    # guarantee this gate cannot make.
    artist_enum, artist_options = [], []
    for a in artists:
        artist_enum.append(a["uri"])
        artist_options.append({"value": a["uri"], "label": a["label"]})

    def _artist_field(description: str, required: bool) -> dict:
        spec = {"type": "string", "description": description}
        if artist_enum:
            spec["enum"] = artist_enum
            spec["x-options"] = artist_options
        return spec

    return [
        Tool(
            name="record.new_artist",
            description=(
                "Create an artist record — the person or persona whose work this "
                "deployment records. One of the two bootstrap forms (CE_DESIGN §14)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "type": type_spec,
                    "name": {"type": "string", "description": "The artist's name (rdfs:label + foaf:name)."},
                    "email": {"type": "string", "description": "Optional contact address (foaf:mbox)."},
                    "homepage": {"type": "string", "description": "Optional site (foaf:homepage)."},
                    "brand": {
                        "type": "string",
                        "description": (
                            "Optional signature stamped into published images, as the bare "
                            "domain — e.g. visualartsdna.org. Leave empty to publish unbranded."
                        ),
                    },
                    "pseudonym_for": _artist_field(
                        "Optional: the artist this one is a persona of.", False),
                    "guid": {"type": "string", "x-hidden": True,
                             "description": "Optional GUID; minted if omitted."},
                    "dest_dir": {"type": "string", "default": dest_dir,
                                 "description": "Sandbox-relative content dir."},
                },
                "required": ["type", "name"],
                "additionalProperties": False,
            },
            handler=partial(_new_artist, work_ns=work_ns),
        ),
        Tool(
            name="record.read_artist",
            description=("An existing artist record as the artist form's own "
                         "fields, for editing it."),
            input_schema={
                "type": "object",
                "properties": {
                    "guid": {"type": "string", "description": "The artist's GUID."},
                    "dest_dir": {"type": "string", "default": dest_dir,
                                 "description": "Sandbox-relative content dir."},
                },
                "required": ["guid"],
                "additionalProperties": False,
            },
            handler=_read_artist,
        ),
        Tool(
            name="record.edit_artist",
            description=(
                "Rewrite an existing artist record. Replaces what the artist form "
                "owns and preserves everything else — the record may carry "
                "statements this form never asks about. There is NO name "
                "argument: the name identifies the persona and every work made "
                "under it is shown under that name (CE_DESIGN §14.10)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "guid": {"type": "string", "x-hidden": True,
                             "description": "The artist being edited."},
                    "type": type_spec,
                    "email": {"type": "string", "description": "Optional contact address (foaf:mbox)."},
                    "homepage": {"type": "string", "description": "Optional site (foaf:homepage)."},
                    "brand": {
                        "type": "string",
                        "description": (
                            "Optional signature stamped into published images, as the bare "
                            "domain — e.g. visualartsdna.org. Changing it applies to images "
                            "ingested from now on; what is already stamped stays stamped."
                        ),
                    },
                    "pseudonym_for": _artist_field(
                        "Optional: the artist this one is a persona of.", False),
                    "dest_dir": {"type": "string", "default": dest_dir,
                                 "description": "Sandbox-relative content dir."},
                },
                "required": ["guid", "type"],
                "additionalProperties": False,
            },
            handler=partial(_edit_artist, work_ns=work_ns),
        ),
        Tool(
            name="record.read_artist_profile",
            description=("An existing artist profile as the profile form's own "
                         "fields, for editing it."),
            input_schema={
                "type": "object",
                "properties": {
                    "guid": {"type": "string", "description": "The profile's GUID."},
                    "dest_dir": {"type": "string", "default": dest_dir,
                                 "description": "Sandbox-relative content dir."},
                },
                "required": ["guid"],
                "additionalProperties": False,
            },
            handler=_read_artist_profile,
        ),
        Tool(
            name="record.new_artist_profile",
            description=(
                "Create an artist profile and the template that becomes its entry "
                "form: which properties its records carry, and in what order."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "label": {"type": "string",
                              "description": "What the card will say, e.g. 'Watercolor materials profile'."},
                    "artist": _artist_field("Whose profile this is.", True),
                    "template_type": template_type_spec,
                    "unit_code": {
                        "type": "string", "enum": UNIT_CHOICES,
                        "description": (
                            "How this profile measures: INH inches, CTM cm, MTR metres, "
                            "E37 pixels. Every record it makes is measured in this, and "
                            "no form asks again."
                        ),
                    },
                    "fields": profile_fields_spec,
                    # The caption and hint come from the ONTOLOGY, as on every
                    # other form: `schema:description` says "A description of a
                    # work". On a form about a profile that is the wrong
                    # subject, and the fix is in the model rather than here —
                    # Rick's, since the same comment serves the work forms where
                    # it is exactly right (2026-09-17).
                    "description": {"type": "string", "x-multiline": True,
                                    "description": "What kind of work this profile covers."},
                    "note": {"type": "string", "x-multiline": True,
                             "description": "Optional: assumptions behind it (skos:note)."},
                    "measurement_note": {
                        "type": "string",
                        "description": "Optional note on the measurement system.",
                    },
                    "guid": {"type": "string", "x-hidden": True,
                             "description": "Optional GUID; minted if omitted."},
                    "dest_dir": {"type": "string", "default": dest_dir,
                                 "description": "Sandbox-relative content dir."},
                },
                # `description` is required: a card whose only words are its
                # own label tells the next person nothing about which kind of
                # work belongs in it (Rick, 2026-09-17).
                "required": ["label", "artist", "template_type", "unit_code",
                             "fields", "description"],
                "additionalProperties": False,
            },
            handler=partial(_new_artist_profile, work_ns=work_ns),
        ),
        Tool(
            name="record.edit_artist_profile",
            description=(
                "Rewrite an existing artist profile and its template. Template "
                "edits apply to works made from now on. There is NO artist "
                "argument: changing it would re-attribute every work ever made "
                "under this profile (CE_DESIGN §14.10). Statements the builder "
                "cannot express — `ops:dependsOn` — survive an edit."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "guid": {"type": "string", "x-hidden": True,
                             "description": "The profile being edited."},
                    "label": {"type": "string",
                              "description": "What the card will say, e.g. 'Watercolor materials profile'."},
                    "template_type": template_type_spec,
                    "unit_code": {
                        "type": "string", "enum": UNIT_CHOICES,
                        "description": (
                            "The unit every measurement on these records is in: "
                            "INH inches, CTM centimetres, MTR metres, E37 pixels."
                        ),
                    },
                    "fields": profile_fields_spec,
                    "description": {"type": "string", "x-multiline": True,
                                    "description": "What kind of work this profile covers."},
                    "note": {"type": "string", "x-multiline": True,
                             "description": "Optional: assumptions behind it (skos:note)."},
                    "measurement_note": {
                        "type": "string",
                        "description": "Optional note on the measurement system.",
                    },
                    "dest_dir": {"type": "string", "default": dest_dir,
                                 "description": "Sandbox-relative content dir."},
                },
                "required": ["guid", "label", "template_type", "unit_code",
                             "fields", "description"],
                "additionalProperties": False,
            },
            handler=partial(_edit_artist_profile, work_ns=work_ns),
        ),
    ]
