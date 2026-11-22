"""The property map: one row per RDF property, naming how it becomes a form
field and how a value becomes triples.

**Why this exists.** The three entry forms are tailored to Rick's artwork, which
is a release blocker for anyone else's (`dashboardEntryFormApproach.txt`). The
proposal is that an **artist profile carries a template** — an ordered list of
properties — and the dashboard builds the form from it. Two of the three layers
already work that way: `ux/forms.py` renders widgets from a field's *declared
affordance*, and the submit pipeline derives its file handling from the schema
rather than naming `image` literally.

What was missing is the part a list of predicates cannot supply: **how a value
becomes triples**. `schema:height` is not a number in the graph — it is a blank
node typed `schema:QuantitativeValue` carrying a unit code, a float and a label
reading "12 inches". `vad:qrcode` is never entered at all. `schema:image` is a
filename joined to the images base. Eight such shapes are spelled out by hand in
`record_tools.py`, once per form.

So the template SELECTS FROM this map; it cannot BE the map. That is also the
law-3 answer: a profile is stored data and stored data is hostile, so a template
naming a property this map does not know is refused rather than improvised into
a widget. Nothing here can be reached by writing a clever TTL.

The map is the single table for both directions — the JSON schema the form
renders from and `validate_args` enforces, and the triples the record is made
of. One table, so the offered set and the enforced set cannot drift; the same
discipline as `referents.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, RDFS, SKOS, XSD

__all__ = [
    "PROPERTY_MAP", "Property", "TemplateError", "Template", "TemplateField",
    "schema_from_template", "graph_from_template", "picker_root",
    "HOUSEKEEPING", "ALWAYS",
]

SCHEMA = Namespace("https://schema.org/")
VAD = Namespace("http://visualartsdna.org/model/")
THE = Namespace("http://visualartsdna.org/thesaurus/")


class TemplateError(Exception):
    """A template that cannot be honoured — an unknown property, a missing
    dependency, a type that is not in the model. Raised at BUILD time, so a
    profile fails at its card with a reason instead of rendering half a form."""


# --- shapes -----------------------------------------------------------------
#
# Every shape below is already written by hand somewhere in record_tools.py;
# this names them so a template can ask for one. The names are descriptions of
# the TRIPLES, not of the widget — two properties can share a widget and differ
# entirely in what they write (`vad:hasPaper` and `vad:hasArtistProfile` are both
# pickers; one resolves against a vocabulary, the other against the work store).
LITERAL = "literal"          # plain literal
DATE = "date"                # literal typed xs:date
FILE_IRI = "file_iri"        # images/documents base + filename
VOCAB_IRI = "vocab_iri"      # a CURIE into a concept scheme
RECORD_IRI = "record_iri"    # a CURIE into the work store
QUANTITY = "quantity"        # BNode schema:QuantitativeValue (value + unitCode + label)
TYPE = "type"                # rdf:type, from the picker
DERIVED_GUID = "derived_guid"      # schema:identifier — the guid itself
DERIVED_QRCODE = "derived_qrcode"  # vad:qrcode — a URL built from the guid
# The eighth shape, and the only one where ONE filename becomes a whole node: a
# schema:VideoObject blank node whose label, name and thumbnail URL are all
# computed from the file, whose uploadDate is the day it entered the record, and
# whose duration is read from the file itself by the trusted layer (this tool
# cannot exec — law 2). The user supplies a filename and, optionally, a
# description; everything else is determined.
COMPOSITE_VIDEO = "composite_video"


@dataclass(frozen=True)
class Property:
    """One row. `field` is the form/argument name, kept identical to the
    hand-written schemas so this can be proven equivalent to them."""

    predicate: str
    field: str
    shape: str
    description: str
    json: dict = dc_field(default_factory=dict)
    multiline: bool = False
    #: Properties whose value this one needs but does not ask for — height and
    #: width need a unit, which now comes from the profile's measurement system
    #: rather than from a field on every record (Rick, 2026-09-14).
    needs: tuple = ()


def _row(p, field, shape, description, **json):
    return Property(predicate=str(p), field=field, shape=shape,
                    description=description, json=json)


# The properties a template may name. Adding a row here — not editing a form —
# is how a new property becomes available to every profile.
PROPERTY_MAP: dict[str, Property] = {
    str(p.predicate): p
    for p in (
        _row(RDF.type, "type", TYPE, "The work's class."),
        _row(RDFS.label, "label", LITERAL, "Work title (rdfs:label)."),
        Property(str(SCHEMA.identifier), "guid", DERIVED_GUID,
                 "The record's GUID — minted, never typed."),
        Property(str(SCHEMA.description), "description", LITERAL,
                 "Work description (schema:description).",
                 json={"x-multiline": True}, multiline=True),
        _row(SCHEMA.location, "location", LITERAL, "Optional schema:location."),
        Property(str(SKOS.note), "note", LITERAL, "Optional skos:note.",
                 json={"x-multiline": True}, multiline=True),
        _row(SCHEMA.datePublished, "recorded_date", DATE,
             "schema:datePublished, ISO date (YYYY-MM-DD).", format="date"),
        _row(SCHEMA.dateCreated, "completed_date", DATE,
             "schema:dateCreated, ISO date (YYYY-MM-DD).", format="date"),
        _row(VAD.hasPaper, "has_paper", VOCAB_IRI,
             "vad:hasPaper CURIE/IRI — a vad:WatercolorPaper concept.",
             **{"x-vocabulary": "papers"}),
        _row(VAD.hasArtistProfile, "has_artist_profile", RECORD_IRI,
             "vad:hasArtistProfile CURIE or IRI, e.g. work:<guid>."),
        Property(str(VAD.qrcode), "qrcode", DERIVED_QRCODE,
                 "vad:qrcode — derived from the GUID, never typed."),
        _row(SCHEMA.image, "image", FILE_IRI,
             "Image filename (schema:image = images base + name).",
             **{"x-file-kind": "image"}),
        _row(SCHEMA.height, "height", QUANTITY, "Height value."),
        _row(SCHEMA.width, "width", QUANTITY, "Width value."),
        _row(SCHEMA.depth, "depth", QUANTITY, "Depth value."),
        _row(VAD.image3d, "image3d", FILE_IRI,
             "3D object filename (vad:image3d).", **{"x-file-kind": "model3d"}),
        _row(VAD.background, "background", RECORD_IRI,
             "vad:background CURIE/IRI — the Entity this work is displayed against.",
             **{"x-entity-ref": "backgrounds"}),
        _row(THE.tag, "tags", VOCAB_IRI, "the:tag references.", array=True),
        _row(SCHEMA.video, "video", COMPOSITE_VIDEO,
             "Video filename (schema:video — a VideoObject built from the file).",
             **{"x-file-kind": "video"}),
    )
}

#: The HOUSEKEEPING set: every record carries these, no form ever shows them,
#: and no template decides either question (Rick, 2026-09-16 — "they are a
#: mandatory, house-keeping set… the user doesn't need to see them and shouldn't
#: have the display or not decision to make").
#:
#: Supplied SERVER-SIDE rather than carried as hidden inputs. A hidden field is
#: still a field the browser posts back, and these are the record's identity —
#: its GUID, the QR that encodes it, and whose profile made it. Nothing that
#: round-trips through a form can be sacred.
#:
#: A template may list them, and Rick's four do; it changes nothing, which is
#: the point. Omitting them changes nothing either — a profile written by hand
#: cannot produce an unhealthy record by forgetting.
HOUSEKEEPING = (str(SCHEMA.identifier), str(VAD.qrcode), str(VAD.hasArtistProfile))

#: What a template must still say for itself: the class of thing being made and
#: what to call it. Neither can be supplied by machinery — a default type comes
#: from `ops:templateType`, but a record with no label is a record nobody can
#: find, and that is the artist's business rather than the dashboard's.
ALWAYS = (str(RDF.type), str(RDFS.label))


@dataclass(frozen=True)
class TemplateField:
    """One field of a profile's template.

    Ordered by `order` rather than by document order, because
    `vad:templateFields a, b, c` in Turtle is three unordered triples — the
    parser may hand them back in any sequence, and a form whose field order
    depends on serialization is a form that reorders itself. Per-field blank
    nodes also give `required` and `depends_on` somewhere to live that does not
    rely on two parallel lists staying aligned.
    """

    predicate: str
    order: int = 0
    required: bool = True
    #: Rick's rule (2026-09-14): everything is required, EXCEPT where a property
    #: only applies when another one is filled in. `vad:background` is required
    #: when `vad:image3d` is given and meaningless otherwise, which no flat
    #: required-flag can say.
    depends_on: str = ""


@dataclass(frozen=True)
class Template:
    type_default: str          # vad:templateType — the picker's DEFAULT, not its only value
    fields: tuple

    def ordered(self) -> list:
        return sorted(self.fields, key=lambda f: (f.order, f.predicate))


def picker_root(model, type_default: str) -> str | None:
    """The class whose subclasses the type picker offers: the IMMEDIATE PARENT
    of the template's type (Rick, 2026-09-14).

    A watercolour profile should still let a mixed-media piece be entered, so the
    picker is not pinned to one class — but neither should it open onto the whole
    ontology. The parent of `vad:Watercolor` is `vad:PaintingForm`, whose
    subclasses are the other painting forms. This replaces the per-form
    `type_root` in config: the profile's own type says where the picker starts.
    """
    if model is None:
        return None
    cls = URIRef(type_default) if "://" in type_default else VAD[type_default]
    parents = [p for p in model.objects(cls, RDFS.subClassOf) if isinstance(p, URIRef)]
    if not parents:
        return None
    # One parent is the modelled case. More than one is a multiple-inheritance
    # model; take the shallowest by IRI for determinism rather than guessing.
    return str(sorted(str(p) for p in parents)[0])


def _known(predicate: str) -> Property:
    prop = PROPERTY_MAP.get(predicate)
    if prop is None:
        raise TemplateError(
            f"the template names {predicate}, which is not in the property map. "
            "A profile may only order and select properties the dashboard knows "
            "how to render and how to write; it cannot define new ones."
        )
    return prop


def schema_from_template(
    template: Template,
    *,
    images_dir: str,
    documents_dir: str = "",
    data_dir: str = "",
    type_enum=None,
    defaults=None,
    unit_name: str = "",
) -> dict:
    """The tool's input schema, generated from the template.

    Generated rather than hand-written because enforcement lives here:
    `validate_args` refuses what this schema does not declare. Write the form
    from a template and the schema by hand, and "what the form offers is what the
    system enforces" stops being true by construction.
    """
    props: dict = {}
    required: list[str] = []
    subtree = {"image": images_dir, "model3d": images_dir,
               "markdown": documents_dir, "pdf": documents_dir}

    for tf in template.ordered():
        prop = _known(tf.predicate)
        if tf.predicate in HOUSEKEEPING:
            continue  # supplied, not asked — see HOUSEKEEPING
        spec: dict = {"description": prop.description}
        spec.update({k: v for k, v in prop.json.items() if k != "array"})

        if prop.shape == TYPE:
            spec = dict(type_enum or {"type": "string", "description": prop.description})
        elif prop.shape == QUANTITY:
            spec["type"] = "number"
            # "The height of the work in inches." The unit is the PROFILE's, so
            # the field can say it — which is the other half of removing the
            # units field: the artist stopped typing it, so the form has to
            # stop leaving them to guess (Rick, 2026-09-16).
            if unit_name:
                # In the description for whoever reads the TOOL — an agent
                # authoring records sees this and nothing else — and as
                # `x-unit` for the form, which appends it to the ontology's own
                # comment rather than replacing it. Same rule as the date
                # format: the model says what the property IS, and it cannot
                # know which unit this profile measures in.
                spec["description"] = (
                    f"{spec['description'].rstrip('.')} in {unit_name}."
                )
                spec["x-unit"] = unit_name
        elif prop.shape in (FILE_IRI, COMPOSITE_VIDEO):
            kind = prop.json.get("x-file-kind", "image")
            spec["type"] = "string"
            spec["x-file-ref"] = subtree.get(kind, images_dir)
            # `image` is the default kind, so saying so adds a key the renderer
            # already assumes — and an extra key is a difference to explain
            # every time these schemas are compared.
            if kind == "image":
                spec.pop("x-file-kind", None)
        elif prop.json.get("array"):
            spec = {"type": "array", "items": {"type": "string"},
                    **{k: v for k, v in spec.items() if k != "array"}}
        else:
            spec["type"] = "string"
        spec.pop("array", None)
        # Per-deployment prefill (the configured artist profile). Config, not
        # template: a default belongs to the deployment, not to the shared map.
        if (defaults or {}).get(prop.field) not in (None, ""):
            spec["default"] = defaults[prop.field]

        props[prop.field] = spec
        if prop.shape == COMPOSITE_VIDEO:
            # Two of the node's properties are the user's to say; the rest are
            # the file's. `video_duration` is filled in by the trusted-side
            # ffprobe when it can answer, and a typed value always wins.
            props["video_description"] = {
                "type": "string", "x-multiline": True,
                "description": "Optional schema:description for the video.",
            }
            props["video_duration"] = {
                "type": "string", "format": "duration",
                "description": (
                    "Optional video duration as an ISO-8601 xs:duration, e.g. "
                    "PT34S. Read from the file automatically when possible."
                ),
            }
            props["video_upload_date"] = {
                "type": "string", "format": "date",
                "description": "Optional schema:uploadDate; defaults to today.",
            }
        # Required unless it only applies when something else is filled in.
        # `depends_on` is checked at build time (graph_from_template), where both
        # values are in hand; the schema cannot express "required if".
        if tf.required and not tf.depends_on:
            required.append(prop.field)

    # Hidden in a GENERATED form, not in every form. It is minted, never typed,
    # and showing it beside a `vad:qrcode` that is NOT shown made the form look
    # arbitrary about which derived values it displays (Rick, 2026-09-16). The
    # hand-written forms still show it read-only — their schema is hand-written
    # too, and in a generated form this is the template's call, which is what
    # `ops:display` would make sayable.
    props["guid"] = {"type": "string", "x-hidden": True,
                     "description": "Optional work GUID; minted if omitted."}
    if data_dir:
        props["dest_dir"] = {"type": "string",
                             "description": "Sandbox-relative content dir.",
                             "default": data_dir}
    return {"type": "object", "properties": props, "required": required,
            "additionalProperties": False}


def graph_from_template(
    template: Template,
    values: dict,
    *,
    work_ns: Namespace,
    img_base: str,
    guid: str,
    units: tuple,
    expand,
    profile_uri: str = "",
) -> Graph:
    """The record's triples, built by walking the same template.

    `units` is `(unitCode, unit_name)` resolved from the PROFILE's
    `vad:measurementSystem`, not asked for per record (Rick, 2026-09-14): a
    profile that says "inches" should not make the artist retype it on every
    work.
    """
    from .record_tools import qrcode_url

    subj = work_ns[guid]
    g = Graph()
    for pfx, ns in (("vad", VAD), ("work", work_ns), ("the", THE),
                    ("schema", SCHEMA), ("skos", SKOS)):
        g.bind(pfx, ns)
    g.bind("xs", XSD)

    # HOUSEKEEPING first, and unconditionally. Whether the template lists them
    # is not the question — every record carries its identity, the QR that
    # encodes it, and the profile that made it.
    g.add((subj, SCHEMA.identifier, Literal(guid)))
    g.add((subj, VAD.qrcode, URIRef(qrcode_url(guid, img_base))))
    if profile_uri:
        g.add((subj, VAD.hasArtistProfile, URIRef(str(profile_uri))))

    unit_code, unit_name = units
    seen = set()
    for tf in template.ordered():
        prop = _known(tf.predicate)
        seen.add(prop.predicate)
        pred = URIRef(prop.predicate)
        raw = values.get(prop.field)

        if tf.predicate in HOUSEKEEPING:
            continue  # already written above, and not the template's to vary

        if raw in (None, "", []):
            if tf.required and not tf.depends_on:
                raise TemplateError(f"{prop.field} is required by this template")
            if tf.depends_on and values.get(_known(tf.depends_on).field):
                raise TemplateError(
                    f"{prop.field} is required when "
                    f"{_known(tf.depends_on).field} is given"
                )
            continue

        if prop.shape == TYPE:
            g.add((subj, RDF.type, VAD[str(raw)] if "://" not in str(raw) else URIRef(str(raw))))
            # Dual-typed, for the reason spelled out at the same line in
            # `record_tools._new_work`: the leaf says what KIND, this says THAT
            # IT IS A WORK, and the two are siblings so neither entails the
            # other. Every `Template` is a work form — they are built only by
            # `profiles.py` from an artist profile, which is the generated
            # equivalent of `record.new_work` — so this is unconditional here.
            # `tests/tools/test_property_map_proof.py` is what makes the two
            # writers stay the same graph, and it is what caught this one.
            g.add((subj, RDF.type, VAD.CreativeWork))
        elif prop.shape == LITERAL:
            g.add((subj, pred, Literal(str(raw))))
        elif prop.shape == DATE:
            g.add((subj, pred, Literal(str(raw), datatype=XSD.date)))
        elif prop.shape == FILE_IRI:
            g.add((subj, pred, URIRef(img_base + str(raw))))
        elif prop.shape in (VOCAB_IRI, RECORD_IRI):
            for one in (raw if isinstance(raw, list) else [raw]):
                g.add((subj, pred, expand(str(one))))
        elif prop.shape == COMPOSITE_VIDEO:
            # Delegated to the record tool's own builder rather than restated
            # here. A second copy of a shape is a second thing to keep in step,
            # and this one has four derived properties to get wrong.
            from .record_tools import _add_video

            _add_video(g, subj, img_base, str(raw),
                       description=values.get("video_description"),
                       duration=values.get("video_duration"),
                       upload_date=values.get("video_upload_date"),
                       # What the record knows about itself, for the derived
                       # description. Read from `values` rather than from the
                       # graph being built: the template's field ORDER decides
                       # what has been written by now, and a description that
                       # depends on whether the video happens to come after the
                       # label is a description that changes with the profile.
                       work_label=str(values.get("label") or ""),
                       type_local=str(values.get("type") or ""))
        elif prop.shape == QUANTITY:
            bn = BNode()
            g.add((subj, pred, bn))
            g.add((bn, RDF.type, SCHEMA.QuantitativeValue))
            g.add((bn, RDFS.label, Literal(f"{raw} {unit_name}")))
            g.add((bn, SCHEMA.unitCode, Literal(unit_code)))
            g.add((bn, SCHEMA.value, Literal(str(raw), datatype=XSD.float)))
        else:  # pragma: no cover — a shape added to the map and not handled here
            raise TemplateError(f"no writer for shape {prop.shape!r}")

    missing = [p for p in ALWAYS if p not in seen]
    if missing:
        raise TemplateError(
            "a template cannot omit " + ", ".join(missing)
            + " — the class of thing being made and what to call it are the "
            "profile's to say, and nothing can supply them for it"
        )
    return g
