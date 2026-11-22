"""Trusted-side resolution of the *dynamic* affordance annotations.

The renderer reads the schema and only the schema (law 10): a field declares
``x-file-ref: <subtree>`` or ``x-vocabulary: <name>`` and the renderer generically
fetches its candidates from a uniform endpoint — no per-field knowledge. This
module is that endpoint's backend. Two dynamic affordances, resolved two ways:

- **x-file-ref** → the files under a sandbox subtree, via the confined ``fs.list``
  tool (so it obeys the same containment/audit as everything else, law 10).
- **x-vocabulary** → concepts from the QA vocabulary graph, by the same query the
  promotion gate enforces against (so the picker offers exactly what the gate
  will accept). Best-effort: empty until the vocabulary is synced (§5), in which
  case the renderer falls back to a free-text input.

Static affordances (``enum``, ``x-enum-suggested``, ``format``) need no backend —
their candidates are already in the schema — so they are not here.
"""

from __future__ import annotations

from pathlib import Path

from rdflib import Graph, Namespace
from rdflib.namespace import RDFS, SKOS

from ..referents import REFERENTS

VAD = Namespace("http://visualartsdna.org/model/")
THE = Namespace("http://visualartsdna.org/thesaurus/")

# The picker's candidate query IS the gate's requirement — one table, in
# `referents.py`, imported by both. It used to be two tables kept equal by a
# comment saying they must be; a picker offering what the gate refuses (or
# refusing what it offers) is the wired-form contract broken in either
# direction, and comments do not enforce contracts.


def resolve_file_ref(dispatch, subtree: str, *, managed_only: bool = False) -> list[dict]:
    """Files under ``subtree`` as ``[{value, label}]`` (value = filename).

    ``dispatch(name, args)`` is the app's confined tool dispatcher; this goes
    through ``fs.list`` so it cannot escape the sandbox and is audited. Returns
    ``[]`` if the subtree does not exist yet."""
    resp = dispatch("fs.list", {"path": subtree})
    if not resp.get("ok"):
        return []
    entries = (resp.get("result") or {}).get("entries", [])
    out = []
    for e in entries:
        if not e.get("is_file"):
            continue
        name = e["name"]
        if name.endswith(".ptr"):  # sidecars are machinery, never a user choice
            continue
        out.append({"value": name, "label": name})
    return sorted(out, key=lambda d: d["value"].lower())


def resolve_referent(graph: Graph | None, name: str) -> list[dict]:
    """Candidates for a referent name as ``[{value, label}]``, value = a CURIE,
    label = rdfs:label (falling back to the local name). ``[]`` when the graph
    is absent or the name is unknown.

    Offers exactly the subjects that satisfy the referent's conditions — which
    are the same conditions the gate refuses the reference for failing.
    """
    ref = REFERENTS.get(name)
    if graph is None or ref is None:
        return []
    first_pred, first_obj = ref.conditions[0]
    out = []
    for s in graph.subjects(first_pred, first_obj):
        if not ref.satisfied_by(graph, s):
            continue
        label = graph.value(s, RDFS.label)
        local = str(s).rsplit("/", 1)[-1].rsplit("#", 1)[-1]
        out.append({"value": _curie(str(s)), "label": str(label) if label else local})
    return sorted(out, key=lambda d: d["label"].lower())


# The name the routes have always used. Kept because `x-vocabulary` is still the
# schema annotation for thesaurus-sourced fields.
resolve_vocabulary = resolve_referent


def load_vocabulary_graph(*dirs) -> Graph | None:
    """Load ``*.ttl`` under the given vocabulary/model dirs into one graph, or
    None if none exist. Best-effort — the vocabulary may not be synced yet."""
    g = Graph()
    for d in dirs:
        base = Path(d)
        if not base.is_dir():
            continue
        for f in base.rglob("*.ttl"):
            try:
                g.parse(str(f), format="turtle")
            except Exception:
                continue
    return g if len(g) else None


def _type():
    from rdflib.namespace import RDF

    return RDF.type


def _curie(uri: str) -> str:
    for prefix, ns in (("the", str(THE)), ("vad", str(VAD)), ("work", "http://visualartsdna.org/work/")):
        if uri.startswith(ns):
            return f"{prefix}:{uri[len(ns):]}"
    return uri


# --- field terms from the ontology (resolved per render) ---------------------

# Cache: dir -> (fingerprint, cached_at_ns, graph). The FINGERPRINT is every
# model file's (name, size, mtime_ns), so editing the ontology is picked up on
# the next render with no restart — which is the requirement: labels and
# comments are derived from the model each time the form is drawn, not baked
# into the registry at startup.
#
# Re-parsing 2600 triples on every keystroke-free page load would be waste, so
# the cache exists; it is the INVALIDATION that carries the requirement. The
# racy-clean window is the same one the content cache uses: a file whose mtime
# is not strictly older than the cache entry is re-read rather than trusted,
# because a write in the same filesystem tick leaves the fingerprint unchanged.
_MODEL_CACHE: dict[str, tuple[tuple, int, Graph]] = {}
_RACY_WINDOW_NS = 10_000_000  # 10 ms


def load_model_live(model_dir) -> Graph | None:
    """The ontology as it is on disk RIGHT NOW, re-read when it changes."""
    import time
    from pathlib import Path

    base = Path(model_dir)
    if not base.is_dir():
        return None
    files = sorted(f for f in base.rglob("*.ttl") if f.is_file())
    fingerprint = []
    for f in files:
        try:
            st = f.stat()
            fingerprint.append((f.name, st.st_size, st.st_mtime_ns))
        except OSError:
            continue
    key = tuple(fingerprint)

    hit = _MODEL_CACHE.get(str(base))
    if hit is not None and hit[0] == key:
        newest = max((m for _, _, m in key), default=0)
        if newest < hit[1] - _RACY_WINDOW_NS:  # not racily clean
            return hit[2]

    g = Graph()
    for f in files:
        try:
            g.parse(str(f), format="turtle")
        except Exception:
            continue  # a broken model file is the parse gate's concern
    _MODEL_CACHE[str(base)] = (key, time.time_ns(), g)
    return g if len(g) else None


def resolve_field_terms(model: Graph | None, field_properties: dict) -> dict:
    """``{field: {"label":…, "comment":…, "property":…}}`` from the ontology.

    The form's wording therefore lives in the model, not in the UI: editing an
    ``rdfs:label`` or ``rdfs:comment`` changes what the form says. A field whose
    property carries no label falls back to the field name, and one with no
    comment simply shows no help text — absence is normal (``height`` has no
    comment today) and must not render an empty hint.
    """
    from rdflib import RDFS, URIRef

    out: dict[str, dict] = {}
    for field, uri in (field_properties or {}).items():
        entry = {"label": field, "comment": "", "property": uri}
        if model is not None:
            ref = URIRef(uri)
            lab = model.value(ref, RDFS.label)
            com = model.value(ref, RDFS.comment)
            if lab:
                entry["label"] = str(lab)
            if com:
                entry["comment"] = str(com)
        out[field] = entry
    return out
