"""Read an artist profile, and the form template it carries.

This is the piece that turns Rick's `dashboardEntryFormApproach.txt` from a
design into a thing the dashboard does: a profile record in the store names an
artist, a measurement system and an ordered list of properties, and the
dashboard builds an entry form from it (CE_DESIGN §14).

**A profile that cannot be honoured fails HERE, with a reason.** The alternative
is a form that renders half its fields and silently drops the rest, which is
worse than no card at all — the artist would find out at the review, or not at
all. So reading is validating: SHACL for structure, the property map for
vocabulary, and a couple of checks SHACL cannot express.

Three sources of truth meet in one place and none of them is this module:

- the **profile record** says which properties, in what order, and which are
  required (data, in the store);
- the **property map** says how each of those becomes a widget and triples
  (`tools/property_map.py`, code);
- the **ontology** says what the type picker offers and how every field is
  captioned (data, in the store).

A template may only *select and order* what the property map already knows. That
is the law-3 answer — a profile is stored data, stored data is hostile, and a
template naming an unknown property is refused rather than improvised.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from rdflib import BNode, Graph, Namespace, URIRef
from rdflib.namespace import RDF, RDFS, SKOS

from .tools.property_map import PROPERTY_MAP, Template, TemplateField

__all__ = [
    "Profile", "ProfileError", "read_profile", "list_profiles", "load_from_dir",
    "list_artists", "load_artists_from_dir",
    "shapes_graph", "warm_shapes", "SHAPES_PATH",
]

OPS = Namespace("http://visualartsdna.org/operations/")
VAD = Namespace("http://visualartsdna.org/model/")
SCHEMA = Namespace("https://schema.org/")

SHAPES_PATH = Path(__file__).resolve().parents[2] / "config" / "shapes" / "artist_profile.ttl"

#: unitCode -> the word a measurement's label reads with ("12 inches"). The
#: codes are the entry form's own (`record_tools._UNITS`), inverted here so a
#: profile states a code and the label still comes out right.
UNIT_NAMES = {"INH": "inches", "CTM": "cm", "MTR": "meters", "E37": "pixels"}


class ProfileError(Exception):
    """A profile that cannot drive a form. Carries what is wrong with it, in
    the words the card will show."""


@dataclass(frozen=True)
class Profile:
    """One card in Content Management, and everything the form behind it needs."""

    uri: str
    label: str
    template: Template
    artist_uri: str
    description: str = ""
    note: str = ""
    #: The artist's `vad:brand`, or "" when they declare none. This is what
    #: replaces the signature picker: brand if the artist has one, else do not
    #: (CE_DESIGN §14.5). Absence is a decision, not a gap.
    brand: str = ""
    unit_code: str = ""
    #: The file this profile was read from, sandbox-relative. Answers "is this
    #: profile distributed yet?" — a question about a FILE, since that is what
    #: git tracks and promotion moves.
    source: str = ""

    @property
    def units(self) -> tuple:
        """`(unitCode, unit name)` for the quantity shape, from the profile's
        measurement system — so "inches" is said once per profile instead of
        once per record."""
        return (self.unit_code, UNIT_NAMES.get(self.unit_code, ""))


#: The parsed shapes, kept once. See `shapes_graph`.
_SHAPES_CACHE: dict = {}


def shapes_graph(path=None) -> Graph:
    """The profile shapes. Loaded from `config/`, not from the store: these say
    what the DASHBOARD requires in order to build a form, and a user should not
    be able to delete the thing that protects them from a broken one.

    **Read once, and deliberately.** Reading profiles is part of building the
    registry, and the registry is rebuilt INSIDE the Landlock-confined worker,
    which cannot see the project tree — so a fresh read there fails with
    `PermissionError: … artist_profile.ttl` and takes the whole rebuild with it.
    That is what a save of a new artist did (Rick, 2026-09-17), because creating
    a bootstrap record rebuilds the registry on purpose.

    Caching in module state is what crosses the boundary: the parent warms this
    before forking, and the child inherits the parsed graph. `warm_shapes()` does
    the warming explicitly rather than relying on a profile happening to exist —
    a deployment with none would fork cold and fail the first time one appeared.
    """
    key = str(path or SHAPES_PATH)
    if key not in _SHAPES_CACHE:
        _SHAPES_CACHE[key] = Graph().parse(key, format="turtle")
    return _SHAPES_CACHE[key]


def warm_shapes() -> None:
    """Parse the shapes now, in the trusted parent, so the worker never has to.

    Called before the fork. Failing here is loud and correct — a dashboard whose
    shapes cannot be read cannot validate a profile, and finding that out at
    startup beats finding it out inside a confined child three screens later.
    """
    shapes_graph()


def _validate(graph: Graph, uri: URIRef, shapes: Graph) -> list:
    """SHACL, scoped to one profile.

    Scoped deliberately: the store holds several profiles and validating all of
    them to open one would report another artist's problem on this artist's
    card.
    """
    from pyshacl import validate

    sub = Graph()
    for pfx, ns in graph.namespaces():
        sub.bind(pfx, ns)
    # BLANK NODES ONLY. The template, its fields and the measurement system all
    # hang off the profile as blank nodes, so following them collects exactly
    # this profile's structure; following IRIs instead would drag in the artist,
    # then their works, then the store.
    seen, frontier = set(), [uri]
    while frontier:
        node = frontier.pop()
        if node in seen:
            continue
        seen.add(node)
        for pred, obj in graph.predicate_objects(node):
            sub.add((node, pred, obj))
            if isinstance(obj, BNode):
                frontier.append(obj)
    conforms, _results, text = validate(
        sub, shacl_graph=shapes, inference="none", abort_on_first=False,
        meta_shacl=False, advanced=False,
    )
    if conforms:
        return []
    return [ln.strip() for ln in str(text).splitlines()
            if ln.strip().startswith("Message:")]


def _fields(graph: Graph, template_node) -> tuple:
    """The template's fields, checked against the property map and each other."""
    fields, unknown, orders = [], [], {}
    for node in graph.objects(template_node, OPS.field):
        pred = graph.value(node, OPS.property)
        order = graph.value(node, OPS.order)
        if pred is None or order is None:
            continue  # SHACL has already reported this; do not double-report
        pred = str(pred)
        if pred not in PROPERTY_MAP:
            unknown.append(pred)
            continue
        required = graph.value(node, OPS.required)
        depends = graph.value(node, OPS.dependsOn)
        if depends is not None and str(depends) not in PROPERTY_MAP:
            unknown.append(str(depends))
            continue
        orders.setdefault(int(order), []).append(pred)
        fields.append(TemplateField(
            predicate=pred,
            order=int(order),
            required=bool(required) if required is not None else True,
            depends_on=str(depends) if depends is not None else "",
        ))

    if unknown:
        raise ProfileError(
            "this template names properties the dashboard cannot render: "
            + ", ".join(sorted(set(unknown)))
            + ". A profile may order and select properties the dashboard knows "
            "how to write; it cannot define new ones."
        )
    # Two fields at the same position is not a SHACL constraint (it is about
    # siblings, not about a node), and it is worth a real message: the form
    # would order them arbitrarily, which is the bug per-field ordering exists
    # to prevent.
    clashes = {o: p for o, p in orders.items() if len(p) > 1}
    if clashes:
        raise ProfileError(
            "two fields share an ops:order, so their order on the form would be "
            "arbitrary: "
            + "; ".join(f"{o} → {', '.join(sorted(p))}" for o, p in sorted(clashes.items()))
        )
    # A dependency on a property this template does not carry can never be
    # satisfied, so the field it guards can never be filled in.
    present = {f.predicate for f in fields}
    dangling = [(f.predicate, f.depends_on) for f in fields
                if f.depends_on and f.depends_on not in present]
    if dangling:
        raise ProfileError(
            "a field depends on a property this template does not include: "
            + "; ".join(f"{PROPERTY_MAP[a].field} depends on {PROPERTY_MAP[b].field}"
                        for a, b in dangling)
        )
    return tuple(fields)


def read_profile(graph: Graph, uri, *, shapes: Graph | None = None) -> Profile:
    """One profile, validated, with its template.

    Raises `ProfileError` rather than returning something half-built: the caller
    is about to render a form from this, and a form missing fields it should
    have is indistinguishable from a form whose fields the artist left blank.
    """
    uri = URIRef(str(uri))
    if (uri, RDF.type, VAD.ArtistProfile) not in graph:
        raise ProfileError(f"{uri} is not a vad:ArtistProfile")

    problems = _validate(graph, uri, shapes if shapes is not None else shapes_graph())
    if problems:
        raise ProfileError("this profile is not yet coherent: " + " ".join(problems))

    template_node = graph.value(uri, OPS.template)
    type_default = graph.value(template_node, OPS.templateType)
    fields = _fields(graph, template_node)

    ms = graph.value(uri, VAD.measurementSystem)
    unit_code = str(graph.value(ms, SCHEMA.unitCode) or "") if ms is not None else ""
    if unit_code and unit_code not in UNIT_NAMES:
        raise ProfileError(
            f"unit code {unit_code!r} is not one the dashboard knows "
            f"({', '.join(sorted(UNIT_NAMES))})"
        )

    # The brand is the ARTIST's, reached through the profile — one artist may
    # have several profiles and they all publish under the same signature.
    artist = graph.value(uri, VAD.artist)
    brand = graph.value(artist, VAD.brand) if artist is not None else None

    return Profile(
        uri=str(uri),
        label=str(graph.value(uri, RDFS.label) or ""),
        template=Template(type_default=str(type_default), fields=fields),
        artist_uri=str(artist or ""),
        description=str(graph.value(uri, SCHEMA.description) or ""),
        note=str(graph.value(uri, SKOS.note) or ""),
        brand=str(brand or ""),
        unit_code=unit_code,
    )


def list_profiles(graph: Graph, *, shapes: Graph | None = None,
                  sources: dict | None = None) -> tuple:
    """`(profiles, broken)` — every profile in the store, and why each rejected
    one was rejected.

    Both halves are returned because silence is the wrong report. A profile that
    does not appear as a card, with nothing said about it, looks exactly like a
    profile nobody created; and the one person who can fix it is the one looking
    at the screen.
    """
    shapes = shapes if shapes is not None else shapes_graph()
    good, broken = [], []
    for uri in sorted(graph.subjects(RDF.type, VAD.ArtistProfile), key=str):
        label = str(graph.value(uri, RDFS.label) or uri)
        try:
            profile = read_profile(graph, uri, shapes=shapes)
            source = (sources or {}).get(str(uri), "")
            good.append(replace(profile, source=source) if source else profile)
        except ProfileError as exc:
            broken.append({"uri": str(uri), "label": label, "reason": str(exc)})
    good.sort(key=lambda p: p.label.lower())
    return good, broken


def load_from_dir(data_dir, *, shapes: Graph | None = None) -> tuple:
    """`(profiles, broken)` read from a directory of instance TTLs.

    Only the files that could hold one are parsed. The store has 341 records and
    four profiles; parsing all of them to find four is the ops-quota bug wearing
    a different hat, and this runs at every registry build. The artist files are
    parsed too, because `vad:brand` lives there and the profile reaches it.

    Reading the text to decide what to parse is a cheap substring test, not a
    parse — and a file that mentions neither cannot define either.
    """
    base = Path(str(data_dir))
    if not base.is_dir():
        return [], []
    graph = Graph()
    sources: dict = {}
    for f in sorted(base.glob("*.ttl")):
        try:
            head = f.read_text(errors="replace")
        except OSError:
            continue
        if "ArtistProfile" not in head and "brand" not in head:
            continue
        # Parsed per FILE first, so each profile knows which file it came from —
        # a dashboard-written profile is `<guid>.ttl`, but a hand-authored one
        # may hold several, and "is this distributed?" is a question about the
        # file git tracks rather than about a name.
        one = Graph()
        try:
            one.parse(data=head, format="turtle")
        except Exception:
            continue  # a broken file is the parse gate's business, not ours
        for subj in one.subjects(RDF.type, VAD.ArtistProfile):
            sources[str(subj)] = f.name
        graph += one
    return list_profiles(graph, shapes=shapes, sources=sources)


def list_artists(graph: Graph) -> list:
    """`[{uri, label, brand}]` for every artist in the store, for the pickers on
    the two bootstrap forms.

    An artist is anything a profile could point `vad:artist` at: the ontology's
    `vad:VisualArtist` subtree in practice, but this asks the DATA rather than
    the model — a deployment whose artist is typed with a class we have never
    heard of still has an artist, and a picker that hid them would be telling
    them they do not exist.
    """
    seen = {}
    for subj in set(graph.subjects(VAD.brand, None)) | set(
            graph.subjects(None, None)):
        types = {str(o) for o in graph.objects(subj, RDF.type)}
        is_artist = any(t.endswith("Artist") or t.endswith("Painter") for t in types)
        # EXCEPT a thesaurus concept. "John Singer Sargent Watercolors" and
        # "Winslow Homer" are `skos:Concept`s in a scheme that also carry
        # `vad:Artist`, and both were offered in the artist pickers as if they
        # were personas of this deployment (CE_DESIGN §14.10). They are subjects
        # the work is ABOUT, not people it belongs to.
        if str(SKOS.Concept) in types or (subj, SKOS.inScheme, None) in graph:
            continue
        if not is_artist or str(subj) in seen:
            continue
        label = graph.value(subj, RDFS.label)
        seen[str(subj)] = {
            "uri": str(subj),
            "label": str(label) if label else str(subj).rsplit("/", 1)[-1],
            "brand": str(graph.value(subj, VAD.brand) or ""),
        }
    return sorted(seen.values(), key=lambda a: a["label"].lower())


def load_artists_from_dir(data_dir) -> list:
    """The artists, read the same cheap way profiles are — candidate files only."""
    base = Path(str(data_dir))
    if not base.is_dir():
        return []
    graph = Graph()
    for f in sorted(base.glob("*.ttl")):
        try:
            head = f.read_text(errors="replace")
        except OSError:
            continue
        if "Artist" not in head and "Painter" not in head:
            continue
        try:
            graph.parse(data=head, format="turtle")
        except Exception:
            continue
    return list_artists(graph)
