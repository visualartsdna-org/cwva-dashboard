"""Config loading (CLAUDE.md: no hardcoded paths/thresholds in code).

Thin helpers over ``config/dashboard.rson``: resolve the sandbox root (outside
the project tree, ``~`` expanded), quotas, and the pointer-managed-binary
policy. Configs are **RSON** (JSON + ``#`` comments), the same language as
cwvaServer-py. Kept dependency-light so both the web app and the REPL harness
share one loader.
"""

from __future__ import annotations

import os
from pathlib import Path

from . import rson
from .identity import check_domain
from .sandbox.pointers import DEFAULT_GIT_CONTENT_EXTENSIONS
from .sandbox.quotas import Quotas

__all__ = [
    "DEFAULT_CONFIG_PATH",
    "load_config",
    "sandbox_root",
    "git_content_extensions",
    "trash_dir",
    "trash_keep_days",
    "attic_dir",
    "quotas",
    "domain",
    "host",
    "sites",
    "instances",
    "shapes_dir",
    "load_shapes",
    "entry_forms",
    "name_from_label_kinds",
    "DEFAULT_NAME_FROM_LABEL",
    "artist_profile",
    "date_format",
    "shadow_sot",
    "environment",
    "target_layout",
    "active_layout",
    "inbox",
    "resolve_config_path",
    "developer",
    "NoConfig",
    "CONFIG_DIR",
]

#: The project's own config folder, wherever the dashboard is run from.
CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"

#: A marker meaning "whichever config this installation has" (see
#: `resolve_config_path`); kept as the default argument everywhere so that an
#: explicit `--config` is still told apart from no choice at all.
DEFAULT_CONFIG_PATH = "config/config.rson"

#: Where an installation's own config is looked for, in order (2026-11-21):
#: `config.rson` is a CE user's, copied from an example; `dashboard.rson` is the
#: developer's QA instance. Neither is in the public repository.
_OWN_CONFIGS = ("config.rson", "dashboard.rson")


class NoConfig(FileNotFoundError):
    """No configuration yet: says how to make one."""


def resolve_config_path(explicit=None) -> str:
    """``explicit`` (a `--config`), else ``CWVA_DASHBOARD_CONFIG``, else this
    installation's own file in config/, else refuse with instructions."""
    if explicit and str(explicit) != DEFAULT_CONFIG_PATH:
        return str(explicit)
    env = os.environ.get("CWVA_DASHBOARD_CONFIG")
    if env:
        return env
    for name in _OWN_CONFIGS:
        if (CONFIG_DIR / name).is_file():
            return str(CONFIG_DIR / name)
    raise NoConfig(
        "no configuration yet. Copy one of the examples and set your domain:\n"
        f"    cp {CONFIG_DIR}/examples/folder.rson {CONFIG_DIR}/config.rson\n"
        "(folder.rson keeps the collection in a folder; git.rson in a git "
        "repository; gcp.rson in a Google Cloud bucket). See About > Configuration.")


def developer(cfg: dict) -> bool:
    """Developer extras on (QA Backup on the hub, and the like). Off for a CE
    installation: one environment, a simpler hub (2026-11-21)."""
    return bool((cfg or {}).get("developer", False))


def load_config(path: str | os.PathLike[str] = DEFAULT_CONFIG_PATH,
                _seen: tuple = ()) -> dict:
    """The config at ``path``, with any config it ``extends`` underneath it.

    A second dashboard instance differs from the first in three keys — its
    sandbox, its SOT target and its banner — and everything else is the same
    deployment: the same domain, sites, quotas, entry forms and shapes. Copying
    the file to change three keys would be two files drifting from the day they
    were written, which is the failure this project keeps finding in other
    guises. So an overlay names what it changes and inherits the rest.

    Dicts merge recursively; anything else in the overlay replaces what the base
    said. `"extends"` is resolved relative to the overlay's own directory, and a
    cycle raises rather than recursing forever.
    """
    if not _seen:
        path = resolve_config_path(path)
    cfg = rson.load(path) or {}
    base_name = cfg.pop("extends", None)
    if not base_name:
        return cfg
    here = Path(path).resolve()
    if here in _seen:
        raise ValueError(f"config extends itself: {' -> '.join(str(p) for p in _seen)}")
    base_path = here.parent / str(base_name)
    return _merge(load_config(base_path, _seen + (here,)), cfg)


def _merge(base: dict, overlay: dict) -> dict:
    out = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def environment(cfg: dict) -> dict:
    """What this instance is, for the banner: ``{"label", "colour"}``.

    Both instances are labelled, not only the dangerous one. If only production
    said so, the absence of a banner would have to mean "this is QA" — and
    absence is exactly what a rendering fault produces, so the two cases would
    be indistinguishable at the moment it matters most.
    """
    env = cfg.get("environment") or {}
    return {"label": str(env.get("label", "")).strip(),
            "colour": str(env.get("colour", "")).strip()}


def _sandbox(cfg: dict) -> dict:
    return cfg.get("sandbox") or {}


def sandbox_root(cfg: dict, *, create: bool = True) -> Path:
    raw = _sandbox(cfg).get("stage_root")
    if not raw:
        raise ValueError("config missing sandbox.stage_root")
    root = Path(os.path.expanduser(raw))
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root


def git_content_extensions(cfg: dict) -> frozenset[str]:
    """The extensions that stay ordinary git content; everything else is
    pointer-managed (inverted policy, CE_DESIGN §3.4).

    Reads ``sandbox.git_content_extensions`` — the key the config file, CLAUDE.md
    and the plan all use. It previously read ``pointer_git_content_extensions``,
    a name left over from before the policy inversion, so the configured list was
    silently ignored and the built-in default used instead. The two happened to
    be identical, which is exactly why nothing caught it: the same "edit the
    config, nothing happens" failure as the write-once ``.gitignore``. The legacy
    key is still accepted so an older config keeps working.
    """
    sandbox = _sandbox(cfg)
    exts = sandbox.get("git_content_extensions") or sandbox.get(
        "pointer_git_content_extensions"
    )
    if not exts:
        return DEFAULT_GIT_CONTENT_EXTENSIONS
    return frozenset(e.lower() for e in exts)


def shadow_sot(cfg: dict) -> dict:
    """The `shadow_sot` block: the disposable copy of production the dashboard is
    driven against. Raises if absent — callers that need it cannot proceed
    without it, and a silent default would point the sync at nothing."""
    block = cfg.get("shadow_sot")
    if not block:
        raise ValueError("config missing shadow_sot")
    return block


def target_layout(target_cfg: dict):
    """A target's :class:`Layout` (kind → path within that target), overlaid on
    the default. Layout translation is **reader-side** (CE_DESIGN §3.6): sync
    copies SOT relpaths verbatim, so the QA tree adopts the target's layout and
    everything addressing it resolves through this map, not a module constant."""
    from .promotion.layout import Layout

    return Layout.from_map(target_cfg.get("mirror_layout"))


def active_layout(cfg: dict):
    """The layout of the target the QA tree currently mirrors.

    Today that is ``shadow_sot`` — the only target configured, and the one the
    sync pulls from. When a real ``sot`` block lands (Phase 3/4 reserved slot) it
    takes precedence, since QA would then mirror production's layout instead.
    Falls back to the default map when neither exists, which is the fixture case.
    """
    from .promotion.layout import Layout

    target = cfg.get("sot") or cfg.get("shadow_sot")
    return target_layout(target) if target else Layout.default()


def inbox(cfg: dict):
    """The user's drop folder (see :mod:`cwva_dashboard.inbox`), or ``None`` when
    unconfigured — a deployment without one simply offers no ingest picker."""
    from .inbox import DEFAULT_EXTENSIONS, Inbox

    block = cfg.get("inbox") or {}
    path = block.get("path")
    if not path:
        return None
    exts = {
        kind: tuple(v) for kind, v in (block.get("extensions") or {}).items()
    } or DEFAULT_EXTENSIONS
    return Inbox(path, extensions=exts)


def trash_dir(cfg: dict) -> str:
    return _sandbox(cfg).get("trash_dir", ".qa/trash")


def trash_keep_days(cfg: dict) -> int:
    """How long a trashed file is kept after the work it belonged to reaches the
    SOT. 0 or less keeps everything, which is how a deployment opts out."""
    return int(_sandbox(cfg).get("trash_keep_days", 30))


def attic_dir(cfg: dict) -> str:
    return _sandbox(cfg).get("attic_dir", ".qa/attic")


def domain(cfg: dict) -> str:
    """The deployer's canonical domain (CE_DESIGN §13). The sovereign ``work:``
    namespace and the image base derive from this; ``vad:``/``the:`` do not.

    **Raises when absent — there is no default.** A fallback here was one
    deployment's domain compiled into the code, and every record minted under it
    would carry the wrong sovereign namespace: not a crash but a silently wrong
    identity, in the one field that cannot be corrected later without a
    namespace rebase (§13.6). Config is the only source (§13.4a), so an absent
    `domain` is a deployment that has not been set up, and saying so is the
    whole job.
    """
    raw = (cfg.get("domain") or "").strip().rstrip("/")
    if not raw:
        raise ValueError(
            "config is missing `domain` — the deployer's canonical domain "
            "(CE_DESIGN §13.2). `work:` and the image base derive from it, so "
            "there is nothing sensible to assume."
        )
    return check_domain(raw)


def host(cfg: dict) -> str | None:
    """Where the catalogue is SERVED, when that differs from the domain the data
    names (CE_DESIGN §13). Equal to `domain` once DNS is set, so this returns
    None in that case and callers need not special-case it."""
    raw = (cfg.get("host") or "").rstrip("/")
    return raw or None


def instances(cfg: dict) -> dict:
    """The `instances` block: the servers the Monitoring tab drives.

    Returns ``{"targets": [InstanceTarget], "secrets_path": str, "timeout_s":
    int}``. Absent block -> no targets, and the page says so rather than
    offering buttons that cannot work.
    """
    from .instances import InstanceTarget

    block = cfg.get("instances") or {}
    targets = [
        InstanceTarget(name=t["name"], url=t["url"], tag=t.get("tag", ""),
                       api=t.get("api", "py"))
        for t in (block.get("targets") or [])
        if t.get("name") and t.get("url")
    ]
    return {
        "targets": targets,
        "secrets_path": block.get("secrets_path") or "~/.secrets.rson",
        "timeout_s": int(block.get("timeout_s") or 300),
    }


def sites(cfg: dict) -> list[str]:
    """Sites for updateWorkOnSite to observe (CE_DESIGN §7.2)."""
    return list(cfg.get("sites") or [])


def shapes_dir(cfg: dict) -> str:
    """Where the SHACL shapes live (CE_DESIGN §14.4). Every ``*.ttl`` under it is
    loaded and handed to the promotion gate.

    Defaults to the shapes shipped with the dashboard rather than to a path in
    the SOT, and the distinction is the point: the ontology says what the art
    world is and belongs to the deployment, while these say what the DASHBOARD
    requires of the data it has to build forms from. A deployment may point this
    elsewhere to add its own.
    """
    configured = cfg.get("shapes_dir")
    if configured:
        return str(Path(str(configured)).expanduser())
    return str(Path(__file__).resolve().parents[2] / "config" / "shapes")


def load_shapes(cfg: dict):
    """The shapes graph, or None when the directory holds none.

    None is honest: it means the gate does not run, and a caller that wants to
    know whether it WILL run can ask this rather than assume. Silently returning
    an empty graph would make an unarmed gate look armed — a SHACL gate with no
    shapes conforms to everything.
    """
    from rdflib import Graph

    base = Path(shapes_dir(cfg))
    files = sorted(base.glob("*.ttl")) if base.is_dir() else []
    if not files:
        return None
    g = Graph()
    for f in files:
        g.parse(str(f), format="turtle")
    return g


#: Which file KINDS an entry form renames after the record's label. Kinds and
#: not a boolean, because the line is about whether the incoming name carries
#: information: a camera's `IMG_2104.JPG` carries none, while an export's
#: `ChatGPT-ArtCriticism…-20261005-1348.md` says which assistant and when.
#: A deployment that hand-names its meshes can add `model3d` here.
DEFAULT_NAME_FROM_LABEL: tuple[str, ...] = ("image",)


def name_from_label_kinds(cfg: dict) -> tuple[str, ...]:
    """The file kinds named after the record, from `entry_forms.name_from_label`.

    An explicit empty list turns it off and keeps the drop folder's names,
    which is the pre-2026-10-07 behaviour.
    """
    forms = cfg.get("entry_forms") or {}
    if "name_from_label" not in forms:
        return DEFAULT_NAME_FROM_LABEL
    return tuple(str(k) for k in (forms.get("name_from_label") or ()))


def entry_forms(cfg: dict) -> dict | None:
    """Per-form record-entry config: ``{form: {type_root, allow_abstract_root}}``.
    Backs the ontology-resolved `type` enum (Q9). None → tool defaults."""
    return cfg.get("entry_forms") or None


def artist_profile(cfg: dict) -> str | None:
    """The deployer's artist-profile CURIE, prefilled into entry forms. None →
    the field renders empty and stays required."""
    return cfg.get("artist_profile") or None


# Named date-display conventions -> the pattern shown to the user. Display only:
# xs:date is ISO 8601 by definition and that is what gets stored.
_DATE_PATTERNS = {"US": "MM/DD/YYYY", "EU": "DD/MM/YYYY", "ISO": "YYYY-MM-DD"}


def date_format(cfg: dict) -> str:
    """The date pattern to show beside date fields, e.g. ``MM/DD/YYYY``.

    Returns the sentinel ``"auto"`` when the browser should be asked instead —
    the only answer that cannot disagree with the picker, since the server
    cannot influence how ``<input type="date">`` renders.

    Otherwise accepts a name (``US``/``EU``/``ISO``) or a literal pattern, shown
    verbatim, so an unusual house convention needs config rather than code.
    """
    raw = str(cfg.get("date_format") or "auto").strip()
    if raw.lower() == "auto":
        return "auto"
    return _DATE_PATTERNS.get(raw.upper(), raw)


def quotas(cfg: dict) -> Quotas:
    q = cfg.get("quotas") or {}
    return Quotas(
        max_file_bytes=q.get("max_file_bytes", Quotas.max_file_bytes),
        max_file_count=q.get("max_file_count", Quotas.max_file_count),
        max_ops_per_minute=q.get("max_ops_per_minute", Quotas.max_ops_per_minute),
    )
