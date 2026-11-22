"""`record.new` — one record tool per artist profile, generated from its template.

CE_DESIGN §14. A profile carries an ordered list of properties; the property map
says how each becomes a widget and triples; this turns the two into a registered
tool, and the UX gets a form with no UX code.

**One tool per profile, not one generic tool taking a profile name.** The
project's contract is that what a form OFFERS is what the system ENFORCES, and
enforcement is `validate_args` against a tool's JSON schema. A single
`record.new(profile, values)` could only declare `values` as an open object,
which would enforce nothing and leave the checking to a handler nobody else
calls — the agent authors records too, and a rule only the form knows is a rule
the agent does not have. Generating the schema per profile keeps the two sides
the same object.

Tools are named by the profile's **GUID**, not its label: a label is the card's
text and the artist may edit it, while the tool name is an identity other things
hold. The user never sees the name — cards link to a route, which resolves the
profile and dispatches.

The registry is rebuilt on refresh, so a profile edited in the store changes its
form the same way an ontology edit already changes captions: without a restart.
"""

from __future__ import annotations

import uuid

from .base import Tool, ToolError
from .property_map import (
    PROPERTY_MAP,
    TemplateError,
    graph_from_template,
    picker_root,
    schema_from_template,
)

__all__ = ["build_profile_tools", "tool_name_for", "profile_layout"]


def tool_name_for(profile) -> str:
    """`record.new.<guid>` — stable across a rename, because it is the GUID."""
    guid = str(profile.uri).rstrip("/").rsplit("/", 1)[-1]
    return f"record.new.{guid}"


def profile_layout(profile, schema: dict) -> list:
    """Rows of fields, two to a row, in the template's own order.

    The ORDER is the artist's — that is what `ops:order` is for. The pairing is
    the dashboard's, and only because a form one field wide reads like a
    questionnaire. Multi-line fields take a row to themselves, since a textarea
    beside a text box looks like a mistake.
    """
    ordered = [PROPERTY_MAP[f.predicate].field for f in profile.template.ordered()
               if PROPERTY_MAP[f.predicate].field in schema["properties"]]
    rows, pending = [], []
    for name in ordered:
        spec = schema["properties"].get(name, {})
        if spec.get("x-multiline") or spec.get("type") == "array":
            if pending:
                rows.append(pending)
                pending = []
            rows.append([name])
            continue
        pending.append(name)
        if len(pending) == 2:
            rows.append(pending)
            pending = []
    if pending:
        rows.append(pending)
    return rows


def _type_field(profile, model, fallback: dict) -> dict:
    """The `type` picker: the subclasses of the template type's IMMEDIATE PARENT,
    defaulting to the template type itself (Rick, 2026-09-14).

    A watercolour profile should still be able to record the mixed-media piece
    the work turned into, without opening onto the whole ontology. With no model
    loaded the field keeps the plain description rather than offering a set that
    would be a guess.
    """
    from .record_tools import subclass_closure

    local = str(profile.template.type_default).rsplit("/", 1)[-1].rsplit("#", 1)[-1]
    root = picker_root(model, profile.template.type_default) if model is not None else None
    if root is None:
        return {**fallback, "default": local}
    offered = subclass_closure(model, root, include_root=True) or [local]
    if local not in offered:
        offered = sorted({*offered, local})
    return {
        "type": "string",
        "description": (
            f"{fallback.get('description', 'The work class.')} Candidate set = "
            f"subclasses of {str(root).rsplit('/', 1)[-1]}, this profile's type "
            f"and its siblings."
        ),
        "enum": offered,
        "default": local,
    }


def build_profile_tools(profiles, domain: str, *, model=None, layout=None) -> list:
    """One tool per readable profile. A profile that cannot be read is not here —
    `list_profiles` reports it with its reason, and the card says so."""
    from functools import partial

    from ..promotion.layout import Layout
    from .record_tools import _expand, _prefixes, image_base, work_namespace

    lay = layout or Layout.default()
    # ONE source for where a record lands. The schema's `dest_dir` default is
    # what the form submits, so a second constant here would silently win over
    # the active target's placement map — records written beside the synced
    # content instead of into it, which is the failure `Layout` exists to
    # prevent and which this got wrong on the first run.
    images_dir = lay.dir("image")
    documents_dir = lay.dir("document")
    dest_dir = lay.dir("work_ttl")
    work_ns = work_namespace(domain)
    img_base = image_base(domain)
    prefixes = _prefixes(work_ns)

    tools = []
    for profile in profiles:
        try:
            schema = schema_from_template(
                profile.template,
                images_dir=images_dir,
                documents_dir=documents_dir,
                data_dir=dest_dir,
                type_enum=_type_field(
                    profile, model,
                    {"type": "string", "description": "The work class."},
                ),
                # "The height of the work in inches." The artist stopped typing
                # the unit when the profile started supplying it, so the field
                # has to say which one — otherwise the form silently expects a
                # number in a unit it never names.
                unit_name=profile.units[1],
            )
        except TemplateError:
            continue  # read_profile already refused it; nothing to register

        def _handler(fileops, _profile=profile, _schema=schema, guid=None,
                     dest_dir=dest_dir, **values):
            guid = guid or str(uuid.uuid4())
            try:
                g = graph_from_template(
                    _profile.template, values, work_ns=work_ns, img_base=img_base,
                    guid=guid, units=_profile.units,
                    expand=lambda c: _expand(c, prefixes),
                    # The record says which profile made it, and the PROFILE
                    # says so — not a hidden field the browser posts back.
                    profile_uri=_profile.uri,
                )
            except TemplateError as exc:
                # The template's own rules — a required field left empty, a
                # dependency unmet — reported as the user's error, not as a
                # crash: they are the same class of thing `validate_args`
                # refuses, and only live here because JSON Schema has no
                # "required if".
                raise ToolError("missing_required", str(exc)) from None

            path = f"{str(dest_dir).rstrip('/')}/{guid}.ttl"
            res = fileops.write_text(path, g.serialize(format="turtle"),
                                     make_parents=True)
            return {"path": res.path, "guid": guid, "uri": str(work_ns[guid]),
                    "triples": len(g), "profile": _profile.uri}

        tools.append(Tool(
            name=tool_name_for(profile),
            description=(
                f"Stage a record from the artist profile {profile.label!r} "
                f"(inventory #1/#2 generalised — CE_DESIGN §14). Fields and their "
                f"order come from that profile's ops:template."
            ),
            input_schema=schema,
            handler=partial(_handler),
            redact=frozenset({"description", "note"}),
        ))
    return tools
