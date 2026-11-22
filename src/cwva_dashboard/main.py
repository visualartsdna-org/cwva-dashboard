"""FastAPI app — the dashboard UX over the tool registry (Phase 4.5).

Law 10: **every UX route dispatches through the tool registry only.** The web
layer holds no filesystem or SOT logic of its own; a request becomes a tool
call routed to the hardened worker (Layer 1 + Layer 2 + audit), exactly the
path the agent will use later. The served page is itself generated from the
registry, so a newly ported function appears as a card with no UX code change.

Run: ``uvicorn cwva_dashboard.main:create_app --factory --port 8100`` (localhost
only). The worker is forked in the lifespan startup; blocking tool calls run in
a threadpool under a lock (CE v1 is single-user / single-workflow).
"""

from __future__ import annotations

import os
import threading
import re
import time
import uuid
from urllib.parse import quote, urlencode
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from . import __version__
from . import config as cfgmod
from .audit import AuditLog, default_path as _default_audit_path
from . import inbox as inbox_mod
from .inbox import InboxError
from .media import probe_duration
from .promotion.driver import PromotionDriverError
from .sandbox.worker import WorkerClient
from .tools.fileops_tools import build_default_registry
from .tools.registry import ToolRegistry as ToolRegistryT

from .dts.pipeline import StageError
from .instances import load_refreshes, record_refreshes
from .tools import edit_tools
from .tools.doc_tools import ID_LINE
from .tools.edit_tools import ENTITIES, WORKS
from .tools.profile_tools import profile_layout, tool_name_for
from .tools.record_tools import documents_base, image_base, work_namespace

__all__ = ["create_app", "Dashboard"]

_UX_DIR = Path(__file__).parent / "ux"
# Cap what the review page echoes back. A record TTL is ~1.5 KB, so this only
# ever trips on something unexpected — and a runaway file should not become a
# multi-megabyte page.
_SOURCE_LIMIT = 200_000
# The proven Groovy dashboard, used directly as the hub (Phase 4.7 D1).
_HUB = Path(__file__).resolve().parents[2] / "html" / "function.html"


def _hub_html() -> str:
    """The hub as authored, with the version filled in beside the logo. Every
    page that wears the hub's header reads it through here."""
    return _HUB.read_text(encoding="utf-8").replace("<!-- VERSION -->", f"v{__version__}")


def _gates_rdf(path: str) -> bool:
    """Is this path RDF the review page can usefully show as text?"""
    from .promotion.gates import rdf_format

    return rdf_format(path) is not None


async def _json_body(request: Request) -> dict:
    """Parse an optional JSON object body; {} when absent."""
    raw = await request.body()
    if not raw:
        return {}
    try:
        body = await request.json()
    except Exception as exc:  # malformed JSON is a client error, not a 500
        raise HTTPException(status_code=400, detail="body must be JSON") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    return body


def _trusted_fileops(sandbox_root, cfg):
    """A FileOps bound to the sandbox, for the trusted side.

    Ingress cannot go through the confined worker: the worker is Landlock-
    restricted to the sandbox and cannot read the drop folder at all. So the
    copy happens here, the same way `sot_sync` already writes pulled bytes in.
    It is still FileOps rather than a raw filesystem write, which is what mints
    the `.ptr` sidecar and applies quotas.
    """
    from .sandbox.fileops import FileOps
    from .sandbox.paths import Sandbox

    return FileOps(
        Sandbox.open(sandbox_root),
        git_content_extensions=cfgmod.git_content_extensions(cfg or {}),
    )


# `_default_audit_path` is `audit.default_path`, imported above. It moved so
# that `tools/repl.py` could reach it too.
def _build_promotion_driver(cfg, sandbox_root, layout, dash):
    """Construct the promotion driver for the configured SOT target, or None.

    This is the one place a **writable** transport is built — everything else in
    the dashboard reads. It stays here in the trusted orchestrator rather than
    anywhere the worker can reach (law 1). Returns None when there is no target
    or no QA repo yet, so the routes 503 instead of half-working.
    """
    if not cfg:
        return None
    target = cfg.get("sot") or cfg.get("shadow_sot")
    if not target or not (Path(sandbox_root) / ".git").is_dir():
        return None
    try:
        from .promotion.driver import PromotionDriver
        from .promotion.qa_git import QAGit
        from .promotion.targets import build_transport
        from .tools.record_tools import image_base

        # Any of the four kinds: a folder, a git checkout (local or pushed), or
        # a bucket (promotion/targets.py), scoped to what the layout manages.
        transport = build_transport(target, layout)
        return PromotionDriver(
            QAGit(root=Path(sandbox_root)),
            transport,
            git_content_extensions=cfgmod.git_content_extensions(cfg),
            image_base=image_base(cfgmod.domain(cfg)),
            layout=layout,
            documents_base=documents_base(cfgmod.domain(cfg)),
            vocab_dirs=[layout.dir("vocab_ttl"), layout.dir("tags_ttl")],
            # Content-sourced referents (vad:background) are entity records, so
            # the gate needs the record store to resolve them.
            content_dirs=[layout.dir("work_ttl")],
            # SHACL. Armed HERE and not left to a flag, for the same reason the
            # asset gate arms on having a base + dir: a gate that is written,
            # tested and passed `None` in the one place that runs it is a gate
            # nobody runs, and "gates passed" then means "no gates ran". The
            # shapes are the dashboard's own requirements of profile data
            # (CE_DESIGN §14.4), so what this catches is a profile that would
            # fail to build a form — before it reaches the SOT and every other
            # copy of the dashboard.
            shapes=cfgmod.load_shapes(cfg),
            # Trashed drafts are pruned once the work they belonged to is in the
            # SOT — the moment it is definitively somewhere else (§2.3).
            trash_dir=cfgmod.trash_dir(cfg),
            trash_keep_days=cfgmod.trash_keep_days(cfg),
            audit=dash.audit.record if hasattr(dash.audit, "record") else None,
        )
    except Exception as exc:  # missing optional dep / no credentials / bad target
        # Said at startup, in the terminal that started the dashboard: a CE
        # user's hand-edited config is the likeliest cause, and "no promotion
        # target configured" on a page much later does not say which line.
        import sys

        print(f"[dashboard] cannot reach the source of truth "
              f"({target.get('transport')}): {type(exc).__name__}: {exc}",
              file=sys.stderr, flush=True)
        return None


class Dashboard:
    """Owns the registry, the hardened worker, and the audit log for one app
    instance. ``dispatch`` is the single choke point every UX route uses."""

    def __init__(
        self,
        sandbox_root: str | Path,
        *,
        enforce_landlock: bool = True,
        audit_path: str | Path | None = None,
        actor: str = "ux",
        registry=None,
        standing_queries=None,
        domain=None,
        sites=None,
        model=None,
        entry_forms=None,
        layout=None,
        artist_profile=None,
        profiles=None,
        artists=None,
        workflows=None,
    ):
        # How to build the registry, kept as a callable so the worker can redo
        # it on a refresh. The model is re-read INSIDE the rebuild rather than
        # captured, or a reload would rebuild from the same stale ontology it is
        # meant to replace.
        self._model_dir = (
            Path(sandbox_root) / layout.dir("model_ttl") if layout is not None else None
        )
        # Where the profiles live, for the same reason: a rebuild re-reads them
        # rather than reusing the ones captured at startup, so a profile edited
        # and refreshed changes its form without a restart.
        self._data_dir = (
            Path(sandbox_root) / layout.dir("work_ttl") if layout is not None else None
        )

        def _build() -> "ToolRegistryT":
            from .profiles import load_artists_from_dir, load_from_dir
            from .tools.record_tools import load_ontology_model

            fresh = load_ontology_model(self._model_dir) if self._model_dir else None
            fresh_profiles = (
                load_from_dir(self._data_dir)[0] if self._data_dir else list(profiles or [])
            )
            # Artists are re-read for the same reason profiles are: an artist
            # created and promoted has to appear in the next profile's picker
            # without a restart.
            fresh_artists = (
                load_artists_from_dir(self._data_dir) if self._data_dir
                else list(artists or [])
            )
            return build_default_registry(
                standing_queries, domain, sites, model=fresh, profiles=fresh_profiles,
                artists=fresh_artists,
                entry_forms=entry_forms, layout=layout,
                artist_profile=artist_profile, workflows=workflows,
            )

        #: The tree this instance owns. Published because a headless
        #: caller needs it to build a trusted-side FileOps, and
        #: re-deriving it from config is how a script ends up in a
        #: different sandbox than the dashboard it is driving.
        self.sandbox_root = Path(sandbox_root)
        self._build_registry = _build
        self.registry = registry if registry is not None else _build()
        # Audit lives outside the sandbox (parent of the stage tree) so the
        # confined worker cannot rewrite it.
        self.audit = AuditLog(
            audit_path or _default_audit_path(sandbox_root), actor=actor
        )
        self.worker = WorkerClient(
            sandbox_root, self.registry, actor=actor, audit=self.audit,
            enforce_landlock=enforce_landlock,
            # Inherited across the fork; the child calls it on `reload`.
            rebuild=None if registry is not None else _build,
        )
        self._lock = threading.Lock()
        #: The open recording, or None. Set by the record routes; read here
        #: because this is the ONE wrapper every registry dispatch goes
        #: through, in the trusted parent, with the arguments unredacted —
        #: which is exactly what a replay needs and exactly what the audit log
        #: does not keep.
        self.recorder = None

    def dispatch(self, name: str, args: dict) -> dict:
        with self._lock:  # serialize: one worker, request/response protocol
            out = self.worker.call(name, **args)
        rec = self.recorder
        if rec is not None and (out or {}).get("ok", True):
            # Only what SUCCEEDED. A refused call changed nothing, so replaying
            # it would assert a failure the scenario format has no way to
            # express — and a session's refusals are usually the user finding
            # out what the rules are, not part of the work.
            rec.step(name, args)
        return out

    def reload(self) -> dict:
        """Make this dashboard current with the ontology on disk.

        Rebuilds the parent's registry (what the FORM offers) and tells the
        worker to rebuild its own (what DISPATCH enforces). Both come from the
        same model, and they must move together: a form offering a class the
        worker rejects is the offered-set != enforced-set hole in a new place.
        """
        with self._lock:
            before = set(self.registry.names())
            self.registry = self._build_registry()
            worker = self.worker.reload()
        return {
            "registry_rebuilt": True,
            "worker_reloaded": bool(worker.get("ok")),
            "worker_error": worker.get("error") or "",
            "tools": len(self.registry.names()),
            "tools_added": sorted(set(self.registry.names()) - before),
        }

    def close(self) -> None:
        self.worker.close()
        self.audit.close()


def create_app(
    *,
    sandbox_root: str | Path | None = None,
    config_path: str = cfgmod.DEFAULT_CONFIG_PATH,
    enforce_landlock: bool = True,
    audit_path: str | Path | None = None,
    registry=None,
    promotion_driver=None,
    inbox=None,
    sites=None,
    site_fetcher=None,
    domain=None,
    instances=None,
    instance_opener=None,
    viewer=None,
) -> FastAPI:
    domain_val = domain
    # Pinned-sandbox path (tests, embedding): the caller supplies the site list
    # the same way it supplies the inbox and the driver, since config is not
    # loaded at all when `sandbox_root` is given.
    sites_val = list(sites) if sites is not None else None
    entry_forms_val = None
    artist_profile_val = None
    date_format_val = ""
    cfg = None  # only loaded when the caller did not pin a sandbox (test path)
    if sandbox_root is None:
        # WHICH config, for the second instance. `uvicorn --factory` calls this
        # with no arguments, so the environment is the only channel it has:
        #   CWVA_DASHBOARD_CONFIG=config/production.rson uvicorn … --port 8102
        # Only consulted when the caller accepted the default — an explicit
        # `config_path` is an explicit choice and outranks the environment.
        config_path = cfgmod.resolve_config_path(config_path)
        cfg = cfgmod.load_config(config_path)
        sandbox_root = cfgmod.sandbox_root(cfg)
        if domain_val is None:
            domain_val = cfgmod.domain(cfg)  # CE_DESIGN §13: work: derives from this
        if sites_val is None:
            sites_val = cfgmod.sites(cfg)  # CE_DESIGN §7.2: updateWorkOnSite targets
        entry_forms_val = cfgmod.entry_forms(cfg)  # per-form type_root (Q9)
        artist_profile_val = cfgmod.artist_profile(cfg)  # prefilled form default
        date_format_val = cfgmod.date_format(cfg)  # display hint only; storage is ISO

    # The signatures Brand Image may stamp (inventory #7), DERIVED from the
    # sites rather than listed again: `https://visualartsdna.org` -> the string the
    # Groovy's radio button held. It is the same list `image.brand` enforces as
    # its enum, so what the form offers is what the tool accepts.
    from .tools.image_tools import signature_options

    signatures_val = signature_options(sites_val or [])

    if not domain_val:
        # Checked HERE, before the registry is built, so the message names the
        # thing the caller can fix. Pinned-sandbox callers skip config entirely,
        # so this is the only place that can catch a deployment with no
        # identity. Refusing beats defaulting: a wrong `work:` namespace is not
        # correctable later without a rebase (CE_DESIGN §13.6), and it fails
        # silently, as perfectly valid RDF.
        raise ValueError(
            "create_app needs a `domain`: pass it explicitly, or let it load "
            "config (omit `sandbox_root`). CE_DESIGN §13.4a — the deployer "
            "configures the dashboard; there is no default identity."
        )

    # The servers the Monitoring tab drives. Like `sites`, a pinned-sandbox
    # caller supplies them directly because config is not loaded on that path.
    instances_val = instances if instances is not None else (
        cfgmod.instances(cfg) if cfg else
        {"targets": [], "secrets_path": "~/.secrets.rson", "timeout_s": 300}
    )

    # Standing-query definitions load as data (CE_DESIGN §7.1) from a sibling of
    # the config; absent -> shipped defaults. Loaded here in the orchestrator so
    # the confined worker inherits them and never reads the project config tree.
    from .workflow_state.definitions import load_standing_queries

    sq_path = str(Path(config_path).with_name("standing_queries.rson"))
    standing_queries = load_standing_queries(sq_path)
    # The workflow board's definitions, the same way and for the same reason.
    from .workflow_state.board import load_workflows

    workflows_val = load_workflows(str(Path(config_path).with_name("workflows.rson")))

    # Ontology model backs the `type` enum (Q9): its candidate set is the RDFS
    # subclass closure of each form's type_root. Loaded best-effort from the QA
    # content tree — absent on a fresh sandbox (before the model is synced, §5),
    # in which case `type` falls back to an unenforced suggested set.
    from .promotion.layout import Layout
    from .tools.record_tools import load_ontology_model
    from .ux.affordance import load_vocabulary_graph

    # Layout is resolved from the ACTIVE TARGET, not the module constant
    # (CE_DESIGN §3.6, gate item B1). The QA tree adopts the layout of whatever
    # SOT it mirrors — the shadow bucket is flat (`ttl/model`), the default disk
    # layout is not (`metacontent/model`) — so reading through the constant found
    # nothing with the correct ontology sitting on disk.
    layout = cfgmod.active_layout(cfg) if cfg else Layout.default()
    # The user's drop folder — the single ingress (see inbox.py).
    inbox_val = inbox if inbox is not None else (cfgmod.inbox(cfg) if cfg else None)

    _sb = Path(sandbox_root)
    model_dir = _sb / layout.dir("model_ttl")
    model_val = load_ontology_model(model_dir)
    # Vocabulary graph for x-vocabulary pickers (best-effort; empty pre-sync).
    # Held in a mutable cell, not closed over: /api/refresh replaces it so the
    # x-vocabulary pickers reflect a thesaurus that arrived with the sync.
    live = {"vocab_graph": load_vocabulary_graph(_sb / layout.dir("vocab_ttl"), model_dir)}

    # Fork the worker here, at factory time, while the process is still
    # single-threaded — forking later (inside the async lifespan, once the
    # server's threadpool exists) risks a deadlock in the child. Uvicorn's
    # --factory calls this before starting the event loop; TestClient callers
    # construct the app before entering the client context.
    # The artist profiles, read from the QA store TRUSTED-SIDE before the worker
    # forks. They feed the registry (one record tool per profile) and the hub's
    # cards, and re-reading them is part of rebuilding the registry, so a profile
    # edited in the store changes its form on the next refresh — the same way an
    # ontology edit already changes captions.
    from .profiles import load_from_dir as _load_profiles
    from .profiles import warm_shapes as _warm_shapes

    # BEFORE the worker forks. The child rebuilds this registry on every reload
    # and cannot read the project tree; the parsed shapes have to be in memory
    # by then, not on disk. Warmed explicitly rather than as a side effect of
    # there happening to be a profile to validate.
    _warm_shapes()

    profiles_val, profiles_broken = _load_profiles(
        Path(sandbox_root) / layout.dir("work_ttl")
    )
    from .profiles import load_artists_from_dir as _load_artists

    artists_val = _load_artists(Path(sandbox_root) / layout.dir("work_ttl"))

    dash = Dashboard(
        sandbox_root,
        enforce_landlock=enforce_landlock,
        audit_path=audit_path,
        registry=registry,
        standing_queries=standing_queries,
        workflows=workflows_val,
        domain=domain_val,
        sites=sites_val,
        model=model_val,
        entry_forms=entry_forms_val,
        layout=layout,
        artist_profile=artist_profile_val,
        profiles=profiles_val,
        artists=artists_val,
    )

    # The cwva-py viewer over this sandbox (viewer.py). Built, never started:
    # it runs only when someone presses Start on its card. Its scratch folder
    # sits beside the sandbox like the audit log, named after the sandbox so
    # the two instances' viewers never share one.
    from .viewer import Viewer, ViewerSettings

    viewer_settings = (viewer if viewer is not None
                       else ViewerSettings.from_config(cfg) if cfg else None)
    viewer = (Viewer(viewer_settings, sandbox_root=sandbox_root, layout=layout,
                     domain=domain_val,
                     scratch=Path(dash.audit.path).with_name(
                         f"viewer-{Path(sandbox_root).name}"),
                     # the instance's own label and colour, as on its pages
                     **{k: (cfgmod.environment(cfg) if cfg else {}).get(k, "")
                        for k in ("label", "colour")})
              if viewer_settings else None)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            yield
        finally:
            if viewer is not None:
                viewer.stop()  # a viewer outliving its dashboard holds the port
            dash.close()

    app = FastAPI(title="CWVA CE Dashboard", version=__version__, lifespan=lifespan)

    # WHICH INSTANCE THIS IS, on every page. Two dashboards run side by side and
    # render the same pages against the same `work:` namespace; only the SOT
    # behind them differs, and one of the two cannot be undone (ux/banner.py).
    env = cfgmod.environment(cfg) if cfg else {"label": "", "colour": ""}
    app.state.environment = env
    if env.get("label"):
        from .ux.banner import EnvironmentBanner

        app.add_middleware(EnvironmentBanner, label=env["label"],
                           colour=env.get("colour", ""))

    app.state.dash = dash
    app.state.viewer = viewer
    # The pieces a HEADLESS caller needs to compose the same workflows the
    # routes do (DTS runs headless first, by design). Published here rather
    # than re-derived in a script, because re-deriving them is how a script
    # ends up pointing at a different layout or a different drop folder than
    # the dashboard it is supposed to be driving.
    app.state.layout = layout
    app.state.inbox = inbox_val
    app.state.domain = domain_val
    app.state.config = cfg
    #: guid -> paths minted by an attempt the user went back to edit. Cleared
    #: by the next successful submit for that guid (see `rdf_entry_edit`).
    app.state.drafts = {}
    app.state.profiles = profiles_val
    app.state.profiles_broken = profiles_broken
    app.state.artists = artists_val
    # The promotion driver is built only when a SOT target is configured and its
    # QA repo exists. Absent one, the promotion routes answer 503 rather than the
    # app failing to start: a dashboard with nothing synced is still useful for
    # entry and inspection, and a half-built driver would be worse than none.
    app.state.promotion_driver = promotion_driver or _build_promotion_driver(
        cfg, sandbox_root, layout, dash
    )

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        # Phase 4.7 D1: the proven dashboard IS the UI. `html/function.html` is
        # served directly as the hub — layout preserved, not regenerated — and
        # each function is wired behind its card one cycle at a time. Cards for
        # unwired functions still render and 404 on click; that is the accepted
        # cost of replacing the generic renderer outright rather than keeping a
        # second surface alive.
        # TWO substitutions, both of them cards that cannot be static: one per
        # artist profile (CE_DESIGN §14), and the pair that creates them.
        # Everything else about the page is still served exactly as authored.
        from .ux.dts_pages import render_dts_card
        from .ux.forms import (
            render_bootstrap_cards,
            render_drafts_card,
            render_profile_cards,
        )

        # Read from DISK, not from app state. A card is a claim that a profile
        # exists, and app state only learned otherwise when a bootstrap record
        # was written — so a profile trashed at the review stop (Edit form) left
        # its card standing, and clicking it minted records pointing at a
        # profile that was no longer there. The read is a substring scan over
        # the record files, which is what `load_from_dir` is built to be cheap
        # at, and the hub is not polled.
        profiles, broken = _refresh_profiles(app)
        page = (
            _hub_html()
            .replace(
                "<!-- PROFILE-CARDS -->",
                render_profile_cards(profiles, broken,
                                     undistributed=_undistributed(app)),
            )
            .replace("<!-- BOOTSTRAP-CARDS -->", render_bootstrap_cards())
            .replace("<!-- DTS-CARD -->", render_dts_card(*_dts_counts(app)))
            .replace("<!-- DRAFTS-CARD -->", render_drafts_card(_draft_count(app)))
            .replace("<!-- WORKFLOWS-CARD -->", _workflows_card(app))
            .replace("<!-- VIEWER-CARD -->", _viewer_card(app))
            .replace("<!-- CARD-MOVER-CONTENT -->", _card_mover(app, "content"))
        )
        return _developer_only(page, cfgmod.developer(cfg) if cfg else True)

    def _developer_only(page: str, on: bool) -> str:
        """The hub's developer extras, between <!-- DEVELOPER --> markers, are
        shown only with `developer: true` (2026-11-21). The routes behind them
        stay; only the hub stops offering them. A fixture with no config is a
        developer's."""
        if on:
            return page
        return re.sub(r"<!-- DEVELOPER -->.*?<!-- /DEVELOPER -->\n?", "", page, flags=re.S)

    def _hub_layout_path(app_) -> Path:
        # Beside the audit log, like the refresh times: a preference of this
        # machine's, shared by both instances, outside every sandbox and SOT.
        return Path(app_.state.dash.audit.path).with_name("hub-layout.json")

    def _card_mover(app_, section: str) -> str:
        from .hub_layout import load_layout
        from .ux.hub_cards import render_card_mover

        return render_card_mover(section, load_layout(_hub_layout_path(app_)).get(section, []))

    @app.post("/api/hub/layout")
    async def hub_layout(request: Request) -> JSONResponse:
        """Save one section's card order (``order: []`` resets it)."""
        from .hub_layout import LayoutError, save_order

        try:
            body = await request.json()
        except Exception:
            body = None
        if not isinstance(body, dict):
            return JSONResponse({"error": "body must be a JSON object"}, status_code=400)
        try:
            order = await run_in_threadpool(
                save_order, _hub_layout_path(request.app),
                str(body.get("section", "")), body.get("order"))
        except LayoutError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse({"section": body["section"], "order": order})

    def _viewer_card(app_) -> str:
        from .ux.viewer_page import render_viewer_card

        v = app_.state.viewer
        return render_viewer_card(v.status() if v is not None else None)

    def _workflows_card(app_) -> str:
        from .ux.board_page import render_board_card

        try:
            got = app_.state.dash.dispatch("workflow.board", {})
        except Exception:
            got = {"ok": False}
        board = got.get("result") if got.get("ok") else None
        return render_board_card(board, (board or {}).get("stall_days", 7))

    def _dts_counts(app_) -> tuple:
        """(entities awaiting a step, documents with no entity).

        Read from the store on every hub render, like the draft count. The
        alternative is a cached number, and a queue surface whose number is
        stale is worse than none — it is the thing the user is trusting to
        know whether to look.
        """
        from rdflib import Graph

        from .dts.state import THE, state_of

        graph = Graph()
        root = Path(app_.state.dash.sandbox_root)
        for sub in ("work_ttl",):
            for path in sorted((root / layout.dir(sub).strip("/")).rglob("*.ttl")):
                try:
                    graph.parse(path, format="turtle")
                except Exception:
                    continue
        pending = sum(1 for s_ in set(graph.subjects(None, THE.AI))
                      if state_of(graph, s_) != "complete")
        documents = len(_dts_documents(graph))
        return pending, documents

    def _draft_count(app_) -> int:
        idx = _drafts_for(app_)
        return idx.count() if idx is not None else 0

    def _drafts_for(app_):
        from .promotion.drafts import DraftIndex
        from .sandbox.pointers import PointerManager

        drv = getattr(app_.state, "promotion_driver", None)
        if drv is None:
            return None
        return DraftIndex(
            drv.qa, layout=layout,
            pointers=PointerManager(drv.qa.root,
                                    git_content=drv.git_content_extensions),
            work_ns=str(work_namespace(domain_val)),
        )

    @app.get("/stageStatus")
    async def stage_status(request: Request) -> JSONResponse:
        """The hub polls this for queue badges. Answered from the same
        standing-query engine the panel and agent narration use — one
        computation, three renderings."""
        resp = await run_in_threadpool(
            request.app.state.dash.dispatch, "workflow.state", {}
        )
        if not resp["ok"]:
            return JSONResponse({})
        state = resp.get("result") or {}
        queues = state.get("queues") or {}
        return JSONResponse({k: v for k, v in queues.items() if isinstance(v, int)})

    # -- RDF Entry (Phase 4.7, first wired function) ------------------------
    def _entry_context(request: Request, tool: str = "record.new_work") -> dict:
        """Resolve everything the form needs, trusted-side: the tool schema (the
        agent's contract), the vocabulary the gate enforces, and the sandbox
        assets. Same sources, so the form cannot offer what the system rejects."""
        from .tools.record_tools import WORK_FIELD_PROPERTIES
        from .ux.affordance import (
            load_model_live,
            resolve_field_terms,
            resolve_vocabulary,
        )

        dash: Dashboard = request.app.state.dash
        schema = next(s for s in dash.registry.schemas() if s["name"] == tool)
        props = schema["inputSchema"]["properties"]
        vocabularies, file_refs = {}, {}
        for spec in props.values():
            if "x-vocabulary" in spec:
                key = spec["x-vocabulary"]
                vocabularies[key] = resolve_vocabulary(live["vocab_graph"], key)
            if "x-entity-ref" in spec:
                # Same closed-set treatment as a vocabulary field, different
                # STORE: these referents are content records, not thesaurus
                # concepts, so they come back through a registry tool over the
                # cached content graph rather than the metacontent graph held
                # in `live`. The candidate conditions are shared with the gate
                # either way (referents.py).
                key = spec["x-entity-ref"]
                vocabularies[key] = _entity_ref_candidates(request, key)
            if "x-file-ref" in spec:
                key = spec["x-file-ref"]
                # The drop folder is THE source of user-supplied images, and the
                # only one offered when it is configured.
                #
                # An earlier version offered the union of the drop folder and the
                # sandbox subtree. That was wrong: the sandbox also holds what the
                # system GENERATES — QR codes now, brand images and thumbnails
                # later — and those are outputs, never a work's source image. It
                # surfaced immediately as a `qrc_<guid>.jpg` in the picker.
                #
                # The union bought nothing anyway, because ingest COPIES rather
                # than moves: an image that was ingested is still in the drop
                # folder, so it is offered either way. And once the full image
                # corpus syncs (~1075 objects) the sandbox half would bury the
                # user's handful of files. Filtering derived names by prefix
                # would be a guess about naming; choosing the source of truth is
                # not.
                #
                # Only the *rendering* changes. `x-file-ref` still names the
                # sandbox subtree the value must resolve within, and the asset
                # gate still enforces exactly that — render ≠ enforce.
                kind = spec.get("x-file-kind", "image")
                # Keyed by (subtree, kind): two fields can share a subtree and
                # still offer different things — `image` and `image3d` both live
                # in images/ but must never show each other's files.
                file_refs[(key, kind)] = _file_ref_candidates(request, key, kind)
        # Re-read the ontology on EVERY render, so an edited rdfs:label or
        # rdfs:comment shows up without restarting. (The `type` enum is still
        # bound at registry-build time, so a change to the CLASS hierarchy does
        # still need a restart — a different lifetime, worth not conflating.)
        model_now = load_model_live(Path(sandbox_root) / layout.dir("model_ttl"))
        return {
            "schema": schema,
            "vocabularies": vocabularies,
            "file_refs": file_refs,
            "terms": resolve_field_terms(model_now, WORK_FIELD_PROPERTIES),
            "inbox": inbox_val,
        }

    # Each wired record form is a SPEC, not a copy of the route. The submit
    # cycle — uniqueness, ingest, record, QR, read-back, preview — is identical
    # across record forms; only the tool, the field order and the wording
    # differ. Cycle 1 earned that logic the hard way (a missing QR generator, a
    # sidecar-less binary, a picker offering generated artifacts), so cycle 2
    # inherits every fix instead of re-deriving them.
    # The bases a reference resolves against. Both derive from the deployer's
    # domain (CE_DESIGN §13.2), and a file field's KIND decides which one it
    # gets — documents do not live under the image base.
    image_base_val = image_base(domain_val)
    docs_base_val = documents_base(domain_val)
    _URL_BASE_FOR_DIR = {
        layout.dir("image"): image_base_val,
        layout.dir("document"): docs_base_val,
    }

    def _url_base_for(subtree: str) -> str:
        """The URL base for files kept in ``subtree``. Images are the default,
        since every other file-ref field so far lands beside them."""
        return _URL_BASE_FOR_DIR.get(subtree, image_base_val)

    from .ux.forms import (
        RDF_DIGITAL_LAYOUT,
        RDF_ENTITY_LAYOUT,
        RDF_ENTRY_LAYOUT,
    )

    _FORMS = {
        "entry": {
            "tool": "record.new_work", "layout": RDF_ENTRY_LAYOUT,
            "title": "VADNA RDF Entry", "path": "/rdf/entry",
            "workflow": "rdf_entry",
            # The image IS the work, so it is named after it (Rick,
            # 2026-10-07). See the entity form below for the contrast.
            "name_from_label": True,
        },
        "digital": {
            "tool": "record.new_digital", "layout": RDF_DIGITAL_LAYOUT,
            "title": "VADNA RDF Digital", "path": "/rdf/digital",
            "workflow": "rdf_digital",
            "name_from_label": True,
        },
        "entity": {
            "tool": "record.new_entity", "layout": RDF_ENTITY_LAYOUT,
            "title": "VADNA RDF Entity", "path": "/rdf/entity",
            "workflow": "rdf_entity",
            # No QR code. The Groovy generated one for WORKS; an entity is not a
            # work and carries no vad:qrcode, so generating one would leave a
            # stray qrc_<guid>.jpg in the sandbox that no record references —
            # an orphan the user would find and rightly ask about.
            "qrcode": False,
            # AND NO BRANDING. An entity's images are references — a background
            # plate, a document scan, a reference photograph — and are left
            # exactly as they arrive (Rick, 2026-09-27). Said by the spec rather
            # than inferred from the fields: the form was offering the control
            # because it has an image field, and having an image field is not
            # the same as owning the image.
            "brands": False,
            # AND NO RENAMING, for the same reason and stated separately
            # because it is a separate act (Rick, 2026-10-07: "On entity forms,
            # the image is not renamed … Entity has its own rules"). A work's
            # image is the work, so it takes the work's name. An entity's image
            # is a REFERENCE to something that already exists and is already
            # called something; renaming it to the entity's label would assert
            # an ownership the entity does not have.
            #
            # The name is still NORMALIZED — "the entity image names must be
            # changed to make them URL compatible, i.e., no whitespace" — which
            # is `normalize_filename`, and is what every file gets regardless.
            "name_from_label": False,
        },
    }

    # A profile becomes an entry in the SAME table as the three hand-written
    # forms, which is the point: everything the submit route does — the
    # collision check, the ingest, the QR, the markdown stamp, the duration
    # probe, branding, the review stop — is already derived from the schema, so
    # a generated form gets all of it with no new code.
    def _profile_spec(app_, guid: str) -> dict | None:
        """The form spec for one profile, resolved WHEN ASKED.

        Built on demand rather than once at startup, because a profile created
        through the bootstrap form has to be usable immediately — and a spec
        table fixed at startup gave the new profile a card that led to a 404.
        Cached in `_FORMS`, and the cache is dropped whenever profiles are
        re-read, so an edited template cannot be served from a stale entry.
        """
        key = f"profile:{guid}"
        if key in _FORMS:
            return _FORMS[key]
        _refresh_profiles(app_)
        profile = next((p for p in app_.state.profiles
                        if str(p.uri).rstrip("/").rsplit("/", 1)[-1] == guid), None)
        if profile is None:
            return None
        # `dash.registry`, not the `registry` parameter — the latter is the
        # caller's override and is usually None, the former is what was built.
        schema = next((s for s in app_.state.dash.registry.schemas()
                       if s["name"] == tool_name_for(profile)), None)
        if schema is None:
            # The profile is on disk but has no tool: it arrived after the last
            # registry build — synced down, or written while the dashboard was
            # running. Rebuild once and look again, rather than answering 404
            # for a card the hub is showing.
            app_.state.dash.reload()
            schema = next((s for s in app_.state.dash.registry.schemas()
                           if s["name"] == tool_name_for(profile)), None)
        if schema is None:
            return None
        _FORMS[key] = {
            "tool": tool_name_for(profile),
            "layout": profile_layout(profile, schema["inputSchema"]),
            "title": profile.label,
            "path": f"/rdf/profile/{guid}",
            "workflow": "rdf_profile",
            # A profile form makes WORKS, so it renames like the other two.
            "name_from_label": True,
            # Every work made under a profile gets its custody record and DI
            # when it is made (PROVENANCE_PLAN.md §9).
            "provenance": True,
            # ALWAYS. `vad:qrcode` is housekeeping (§14.8): every record
            # carries it whether or not the template lists it, and the builder
            # no longer offers it — so asking the template produced False on
            # every built profile, and the record cited a QR nobody generated.
            # The asset gate caught it, which is the gate working; the record
            # should never have reached it (Rick, 2026-09-17).
            "qrcode": True,
            # "" is a real answer (this artist does not brand); None means "not
            # a profile form", which is what keeps the picker on the others.
            "brand": profile.brand,
        }
        return _FORMS[key]

    def _refresh_profiles(app_) -> tuple:
        """The profiles as they are on disk right now, into app state.

        Cheap by construction (`load_from_dir` parses only files that could hold
        one) and deliberately not a registry rebuild: what EXISTS is a question
        about the store, what is DISPATCHABLE is a question about the worker, and
        conflating them is what made a deleted profile keep its card.
        """
        from .profiles import load_from_dir

        app_.state.profiles, app_.state.profiles_broken = load_from_dir(
            Path(sandbox_root) / layout.dir("work_ttl")
        )
        # A spec cached for a profile that has since changed or gone must not be
        # served from the shape it had.
        live = {str(p.uri).rstrip("/").rsplit("/", 1)[-1] for p in app_.state.profiles}
        for key in [k for k in _FORMS if k.startswith("profile:")]:
            if key.split(":", 1)[1] not in live:
                _FORMS.pop(key, None)
        return app_.state.profiles, app_.state.profiles_broken

    def _undistributed(app_) -> set:
        """Profile GUIDs that exist only in QA — created here and not yet
        approved. They are real and usable, and they are also the ones a
        refresh, a discard or an Edit form will take away, which is worth
        saying on the card rather than discovering (Rick, 2026-09-17)."""
        driver = app_.state.promotion_driver
        if driver is None:
            return set()
        try:
            status = driver.qa.uncommitted_paths()
        except Exception:
            return set()
        # The FILES git has not seen, matched to the profiles read out of them.
        # Matching on filename would assume one profile per `<guid>.ttl`, which
        # is the dashboard's own convention and not a rule — a hand-authored file
        # may hold several.
        data_dir = layout.dir("work_ttl").strip("/")
        pending = {Path(p).name for p in status
                   if p.startswith(data_dir) and p.endswith(".ttl")}
        return {str(p.uri).rstrip("/").rsplit("/", 1)[-1]
                for p in app_.state.profiles if p.source in pending}

    def spec_path_for(pending) -> str:
        """The form path a pending promotion came from, for reopening it."""
        ctx = pending.context or {}
        if ctx.get("path"):
            return str(ctx["path"])
        spec = next((f for f in _FORMS.values() if f["workflow"] == pending.workflow),
                    _FORMS["entry"])
        return spec["path"]

    def _brand_for_record(app_, instance) -> str:
        """The brand this record publishes under, via its profile's artist.

        Editing a record asks no branding question (Rick, 2026-09-17: "I already
        made my decision on branding when I created the artist"). The record
        names a profile, the profile names an artist, the artist declares a
        brand or does not — and an artist who declares none gets no stamp, here
        as on the entry forms (CE_DESIGN §14.5).

        Returns "" for a record whose profile cannot be resolved, which means no
        branding rather than a guess: a legacy record predating profiles has no
        artist to ask.
        """
        # From DISK, for the same reason the hub reads from disk: app state
        # learns about profiles at particular moments, and "whose work is this?"
        # must not depend on whether one of those moments has happened yet.
        _refresh_profiles(app_)
        wanted = "http://visualartsdna.org/model/hasArtistProfile"
        cited = ""
        for field in (instance or {}).get("fields") or []:
            if field.get("predicate") == wanted:
                # `uris`, not `value`: the field's value is the profile's LABEL
                # now, which is the right thing to show and the wrong thing to
                # resolve.
                uris = field.get("uris") or []
                cited = str(uris[0] if uris else field.get("value") or "").strip()
                break
        if not cited:
            return ""
        tail = cited.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]
        brand = ""
        for profile in app_.state.profiles:
            if str(profile.uri).rstrip("/").endswith(tail):
                brand = profile.brand
                break
        if not brand:
            return ""
        # `_refresh_profiles` answers what EXISTS; stamping is a DISPATCH, and
        # `image.brand` closes its signature to the set the registry was built
        # with. A profile created since that build therefore resolves to a brand
        # the worker refuses — which is how this failed first: `not_in_enum`,
        # reported as "NOT branded" on a page nobody was reading closely. The
        # registry is made current only when the store knows a brand it does
        # not, so the common save still costs nothing.
        if brand not in _accepted_signatures(app_):
            app_.state.dash.reload()
        return brand

    def _accepted_signatures(app_) -> set:
        """The signatures `image.brand` will accept right now — read from the
        tool itself, so this cannot drift from what the worker enforces."""
        tool = app_.state.dash.registry.get("image.brand")
        if tool is None:
            return set()
        spec = (tool.input_schema.get("properties") or {}).get("signature") or {}
        return set(spec.get("enum") or [])

    def _spec_for_path(app_, path: str) -> dict | None:
        """The form spec behind a path, including a profile's generated one."""
        if path.startswith("/rdf/profile/"):
            return _profile_spec(app_, path.rsplit("/", 1)[-1])
        return next((f for f in _FORMS.values() if f["path"] == path), None)

    def _reload_bootstrap(app_) -> None:
        """Re-read artists and profiles, and rebuild the registry from them."""
        from .profiles import load_artists_from_dir, load_from_dir

        data = Path(sandbox_root) / layout.dir("work_ttl")
        app_.state.artists = load_artists_from_dir(data)
        app_.state.profiles, app_.state.profiles_broken = load_from_dir(data)
        # Drop the cached specs: a template that changed must not be served from
        # the shape it had before.
        for key in [k for k in _FORMS if k.startswith("profile:")]:
            _FORMS.pop(key, None)
        app_.state.dash.reload()

    # The BOOTSTRAP forms. Hand-written, and in the same table as everything
    # else so they get the same submit pipeline and the same review stop.
    _FORMS["artist"] = {
        "tool": "record.new_artist", "path": "/rdf/artist",
        "title": "New artist", "workflow": "rdf_artist", "qrcode": False,
        "layout": [["type", "name"], ["email", "homepage"],
                   ["brand", "pseudonym_for"]],
    }
    _FORMS["artist_profile"] = {
        "tool": "record.new_artist_profile", "path": "/rdf/artist-profile",
        "title": "New artist profile", "workflow": "rdf_artist_profile",
        "qrcode": False,
        "layout": [["label", "artist"], ["template_type", "unit_code"],
                   ["description"], ["note"], ["measurement_note"], ["fields"]],
    }

    _FORMS["artist_edit"] = {
        "tool": "record.edit_artist", "path": "/rdf/artist/edit",
        "title": "Edit artist", "workflow": "rdf_artist_edit", "qrcode": False,
        # No `name`: the tool has no such argument, and a layout naming a field
        # the schema does not define renders an empty cell.
        "layout": [["type"], ["email", "homepage"],
                   ["brand", "pseudonym_for"]],
    }

    @app.get("/rdf/artist", response_class=HTMLResponse)
    async def artist_form(request: Request) -> HTMLResponse:
        return await _render_form(request, _FORMS["artist"])

    def _artist_chooser(app_, guid: str, name: str = "") -> str:
        from .ux.forms import render_record_chooser

        # The NAME is shown and cannot be changed (CE_DESIGN §14.10). It is the
        # only field on this form that is a fact rather than a setting, so it is
        # here with its reason instead of missing from the fields below.
        fixed = ()
        if name:
            fixed = ((
                "Name",
                name,
                "Read-only. The name identifies the persona, and every work made "
                "under this artist is shown under it &mdash; on the site, on a "
                "certificate, and in the signature already stamped into those "
                "works' images. To correct a new artist's name, discard the draft "
                'on <a href="/drafts">Drafts</a> and create it again.',
            ),)
        return render_record_chooser(
            [{"value": str(a["uri"]).rstrip("/").rsplit("/", 1)[-1],
              "label": a["label"]} for a in app_.state.artists],
            nav="/rdf/artist/edit?guid=", label="Artist", selected=guid,
            readonly=fixed,
        )

    @app.get("/rdf/artist/edit", response_class=HTMLResponse)
    async def artist_edit_form(request: Request, guid: str = "") -> HTMLResponse:
        """The artist form, opened on an existing record.

        Same form as New artist — generated from the tool schema, so the two
        cannot offer different fields — with the record chooser above it and the
        values already in it.
        """
        _reload_artists(request.app)
        artists = request.app.state.artists
        if not artists:
            return HTMLResponse(
                "<h1>Edit artist</h1><p>This store has no artists yet. "
                "<a href='/rdf/artist'>Create one</a> first.</p>"
                "<p><a href='/'>&larr; dashboard</a></p>", status_code=409,
            )
        guid = guid or str(artists[0]["uri"]).rstrip("/").rsplit("/", 1)[-1]
        got = await run_in_threadpool(
            request.app.state.dash.dispatch, "record.read_artist", {"guid": guid}
        )
        if not got.get("ok"):
            err = got.get("error") or {}
            return HTMLResponse(
                _artist_chooser(request.app, guid)
                + f"<p>{err.get('code', 'error')}: {err.get('message', '')}</p>"
                "<p><a href='/'>&larr; dashboard</a></p>", status_code=404,
            )
        values = (got["result"] or {}).get("values", {})
        return await _render_form(
            request, _FORMS["artist_edit"], guid=guid, values=values,
            picker=_artist_chooser(request.app, guid, values.get("name", "")),
        )

    @app.post("/rdf/artist/edit", response_class=HTMLResponse)
    async def artist_edit_submit(request: Request) -> HTMLResponse:
        return await _submit_record(request, _FORMS["artist_edit"])

    _FORMS["artist_profile_edit"] = {
        "tool": "record.edit_artist_profile", "path": "/rdf/artist-profile/edit",
        "title": "Edit artist profile", "workflow": "rdf_artist_profile_edit",
        "qrcode": False,
        # No `artist`: the tool has no such argument. It is shown above the
        # fields as a fact of the profile (CE_DESIGN §14.10).
        "layout": [["label"], ["template_type", "unit_code"],
                   ["description"], ["note"], ["measurement_note"], ["fields"]],
    }

    def _profile_chooser(app_, guid: str, artist_uri: str = "") -> str:
        from .ux.forms import render_record_chooser

        who = next((a["label"] for a in app_.state.artists
                    if str(a["uri"]) == str(artist_uri)), "")
        fixed = ()
        if who or artist_uri:
            fixed = ((
                "Artist",
                who or artist_uri,
                "Read-only. Every work ever made under this profile is attributed "
                "through it, and those works' images already carry this artist's "
                "brand. To make the same kind of work for a different artist, "
                'create a new profile on <a href="/rdf/artist-profile">New artist '
                "profile</a>.",
            ),)
        # The profiles that cannot drive a form yet are offered too: this
        # editor is where they are repaired.
        choices = [{"value": str(p.uri).rstrip("/").rsplit("/", 1)[-1], "label": p.label}
                   for p in app_.state.profiles]
        choices += [{"value": str(b["uri"]).rstrip("/").rsplit("/", 1)[-1],
                     "label": f'{b["label"]} (no form yet)'}
                    for b in getattr(app_.state, "profiles_broken", ()) or ()]
        return render_record_chooser(
            choices, nav="/rdf/artist-profile/edit?guid=", label="Profile",
            selected=guid, readonly=fixed,
        )

    @app.get("/rdf/artist-profile/edit", response_class=HTMLResponse)
    async def artist_profile_edit_form(request: Request, guid: str = "") -> HTMLResponse:
        """The profile form, opened on an existing profile.

        Template edits apply to works made from now on: nothing validates an
        existing record against its profile's template, which is what makes that
        true rather than merely intended.
        """
        _reload_artists(request.app)
        profiles, broken = _refresh_profiles(request.app)
        if not profiles and not broken:
            return HTMLResponse(
                "<h1>Edit artist profile</h1><p>This store has no "
                "profiles. <a href='/rdf/artist-profile'>Create one</a> first.</p>"
                "<p><a href='/'>&larr; dashboard</a></p>", status_code=409,
            )
        first = profiles[0].uri if profiles else broken[0]["uri"]
        guid = guid or str(first).rstrip("/").rsplit("/", 1)[-1]
        got = await run_in_threadpool(
            request.app.state.dash.dispatch, "record.read_artist_profile",
            {"guid": guid},
        )
        if not got.get("ok"):
            err = got.get("error") or {}
            return HTMLResponse(
                _profile_chooser(request.app, guid)
                + f"<p>{err.get('code', 'error')}: {err.get('message', '')}</p>"
                "<p><a href='/'>&larr; dashboard</a></p>", status_code=404,
            )
        result = got["result"] or {}
        return await _render_form(
            request, _FORMS["artist_profile_edit"], guid=guid,
            values=result.get("values", {}),
            picker=_profile_chooser(request.app, guid, result.get("artist", "")),
        )

    @app.post("/rdf/artist-profile/edit", response_class=HTMLResponse)
    async def artist_profile_edit_submit(request: Request) -> HTMLResponse:
        return await _submit_record(request, _FORMS["artist_profile_edit"])

    def _reload_artists(app_) -> None:
        from .profiles import load_artists_from_dir

        app_.state.artists = load_artists_from_dir(
            Path(sandbox_root) / layout.dir("work_ttl"))

    @app.post("/rdf/artist", response_class=HTMLResponse)
    async def artist_submit(request: Request) -> HTMLResponse:
        return await _submit_record(request, _FORMS["artist"])

    @app.get("/rdf/artist-profile", response_class=HTMLResponse)
    async def artist_profile_form(request: Request) -> HTMLResponse:
        # A profile belongs to an artist, so there has to BE one. Said here
        # rather than rendered as a form with an empty picker: an empty picker
        # looks like a bug, and the remedy — make an artist — is one click.
        if not app.state.artists:
            return HTMLResponse(
                "<h1>New artist profile</h1><p>A profile belongs to an artist, "
                "and this store has none yet. <a href='/rdf/artist'>Create an "
                "artist</a> first — it takes a name and a class.</p>"
                "<p><a href='/'>&larr; dashboard</a></p>",
                status_code=409,
            )
        return await _render_form(request, _FORMS["artist_profile"])

    @app.post("/rdf/artist-profile", response_class=HTMLResponse)
    async def artist_profile_submit(request: Request) -> HTMLResponse:
        return await _submit_record(request, _FORMS["artist_profile"])

    @app.get("/rdf/resume/{guid}", response_class=HTMLResponse)
    async def resume_form(guid: str, request: Request) -> HTMLResponse:
        """Reopen the form a draft came from, with what was typed in it.

        Reached from a failed gate. The values are held server-side rather than
        round-tripped through the page: they are the user's work, and a hidden
        blob of them in HTML is a thing to get wrong rather than a thing to
        rely on.
        """
        draft = request.app.state.drafts.get(guid)
        if not draft:
            return HTMLResponse(
                "<h1>Nothing to resume</h1><p>That draft is no longer in "
                "progress. Its record may still be in QA — use "
                "<a href='/edit'>Edit Record</a> to change it, or "
                "<a href='/'>start again</a>.</p>", status_code=404)
        spec = _spec_for_path(request.app, str(draft.get("path", "")))
        if spec is None:
            return HTMLResponse(
                "<h1>Nothing to resume</h1><p>The form that made this draft is "
                "no longer available.</p><p><a href='/'>&larr; dashboard</a></p>",
                status_code=404)
        values = dict(draft.get("values") or {})
        return await _render_form(
            request, spec, guid=values.get("guid", guid), values=values,
            editing=True,
            notice="Back to your entry. The draft is still in QA and will be "
                   "replaced when you submit again.",
        )

    @app.get("/rdf/profile/{guid}", response_class=HTMLResponse)
    async def profile_form(guid: str, request: Request) -> HTMLResponse:
        spec = _profile_spec(request.app, guid)
        if spec is None:
            return HTMLResponse(_profile_missing(guid), status_code=404)
        return await _render_form(request, spec)

    @app.post("/rdf/profile/{guid}", response_class=HTMLResponse)
    async def profile_submit(guid: str, request: Request) -> HTMLResponse:
        spec = _profile_spec(request.app, guid)
        if spec is None:
            return HTMLResponse(_profile_missing(guid), status_code=404)
        return await _submit_record(request, spec)

    def _profile_missing(guid: str) -> str:
        """Named rather than generic: a profile that failed to read is the
        likely reason, and its reason is already in hand."""
        broken = next((b for b in app.state.profiles_broken
                       if b["uri"].endswith(guid)), None)
        if broken:
            return (f"<h1>{broken['label']}</h1><p>This profile cannot build a "
                    f"form: {broken['reason']}</p><p><a href='/'>&larr; dashboard</a></p>")
        return ("<h1>No such profile</h1><p>No artist profile with that id is in "
                "the store. If you have just added one, refresh to pick it up."
                "</p><p><a href='/'>&larr; dashboard</a></p>")

    async def _render_form(request: Request, spec: dict, *, guid=None, values=None,
                           error: str = "", notice: str = "", editing: bool = False,
                           status: int = 200, picker: str = "") -> HTMLResponse:
        """Render one record form from its spec.

        Every path that shows a form goes through here — first load, refusal,
        and edit — so a fix to one is a fix to all three, in both forms.
        """
        from .tools.record_tools import qrcode_url
        from .ux.forms import render_entry_form

        ctx = await run_in_threadpool(_entry_context, request, spec["tool"])
        guid = str(guid or uuid.uuid4())
        # Ask where the file is only for a kind of work that IS one. Decided from
        # the form's own type, by the storage solutions, so a new digital type is
        # covered by adding it to a solution and nothing here.
        location = None
        input_schema = ctx["schema"].get("inputSchema") or {}
        default_type = ((input_schema.get("properties") or {}).get("type") or {}).get("default")
        if spec.get("provenance") and default_type:
            got = await run_in_threadpool(
                request.app.state.dash.dispatch, "provenance.storage_class",
                {"types": [str(default_type)]},
            )
            cls = ((got.get("result") or {}).get("classes") or {}).get(str(default_type))
            if got.get("ok") and cls:
                location = {"storage_class": cls,
                            "value": (values or {}).get("file_location", "")}
        return HTMLResponse(
            render_entry_form(
                ctx["schema"],
                guid=guid,
                vocabularies=ctx["vocabularies"],
                file_refs=ctx["file_refs"],
                terms=ctx["terms"],
                date_format=date_format_val,
                field_layout=spec["layout"],
                values=values,
                qrcode_url=qrcode_url(
                    guid, image_base(domain_val)
                ),
                drop_folder=str(inbox_val.root) if inbox_val else "",
                action=spec["path"],
                title=spec["title"],
                editing=editing,
                # A profile form offers NO signature picker: the profile names
                # the artist, the artist declares `vad:brand` or does not, and
                # that settles it (CE_DESIGN §14.5). Asking would be offering a
                # choice about someone whose answer is already recorded.
                signatures=(
                    [] if (spec.get("brand") is not None
                           or not spec.get("brands", True))
                    else signatures_val
                ),
                # The way out of an open session, wherever the user is standing.
                episode=_episode(request),
                # The record chooser, when the form is editing one.
                picker=picker,
                notice=notice,
                error=error,
                file_location=location,
            ),
            status_code=status,
        )

    @app.get("/rdf/entry", response_class=HTMLResponse)
    async def rdf_entry_form(request: Request) -> HTMLResponse:
        return await _render_form(request, _FORMS["entry"])

    @app.get("/rdf/digital", response_class=HTMLResponse)
    async def rdf_digital_form(request: Request) -> HTMLResponse:
        return await _render_form(request, _FORMS["digital"])

    @app.get("/rdf/entity", response_class=HTMLResponse)
    async def rdf_entity_form(request: Request) -> HTMLResponse:
        return await _render_form(request, _FORMS["entity"])

    @app.post("/rdf/entry", response_class=HTMLResponse)
    async def rdf_entry_submit(request: Request) -> HTMLResponse:
        return await _submit_record(request, _FORMS["entry"])

    @app.post("/rdf/digital", response_class=HTMLResponse)
    async def rdf_digital_submit(request: Request) -> HTMLResponse:
        return await _submit_record(request, _FORMS["digital"])

    @app.post("/rdf/entity", response_class=HTMLResponse)
    async def rdf_entity_submit(request: Request) -> HTMLResponse:
        return await _submit_record(request, _FORMS["entity"])

    def _episode(request: Request) -> dict:
        """The open session, for the bar that offers the way out of it."""
        drv = getattr(request.app.state, "promotion_driver", None)
        return drv.open_episode() if drv is not None else {}

    def _begin_episode(request: Request, workflow: str, subject: str = "") -> dict:
        """Snapshot the sandbox before a writer writes (promotion/episode.py).

        Called by every form that writes, because what makes leaving safe is
        having somewhere to go back TO. A deployment with no promotion target
        has no driver and therefore no snapshot — the same trade the promotion
        routes already make, and it fails toward "nothing happens" rather than
        "nothing can be undone but we pretended otherwise".
        """
        drv = getattr(request.app.state, "promotion_driver", None)
        if drv is None:
            return {}
        return drv.begin_episode(workflow, subject)

    async def _submit_record(request: Request, spec: dict) -> HTMLResponse:
        """Create the record, then stop at the Distribute review.

        Two registry dispatches' worth of work happen here and *no* convergence:
        the record tool writes TTL into QA, and the promotion driver builds the
        preview. Approving is a separate, explicit act (A0).
        """
        from .tools.record_tools import qrcode_url
        from .ux.forms import render_entry_form, render_review_page

        # The episode is keyed by the FORM, not the record: a new record has no
        # identity until it is written, and submitting the same form twice —
        # which is what "Edit form, fix it, submit again" is — is one piece of
        # work with one restore point.
        _begin_episode(request, spec["workflow"], spec["path"])
        form = await request.form()
        args = {k: v for k, v in form.items() if str(v) != ""}
        # Not a property of the record — a instruction about the FILES arriving
        # with it. Popped here so the record tool keeps refusing anything it does
        # not declare (additionalProperties: false).
        brand_signature = str(args.pop("brand_signature", "") or "")
        # For the provenance record, not the work.
        file_location = str(args.pop("file_location", "") or "").strip()
        # On a profile form the artist is known, so their brand is known. An
        # artist who declares none gets none — absence is a decision, not a gap.
        if spec.get("brand") is not None:
            brand_signature = str(spec["brand"])
        # ARRAY fields, first needed by the entity form. `form.items()` keeps
        # one value per key, which silently drops all but the last checkbox of a
        # multi-select — so array fields are read with getlist instead, and a
        # textarea field is split on newlines/commas.
        schema = next(
            (x for x in request.app.state.dash.registry.schemas()
             if x["name"] == spec["tool"]),
            None,
        )
        props = (schema or {}).get("inputSchema", {}).get("properties", {}) or {}
        for name, f in props.items():
            if f.get("type") != "array" or name == "notes":
                continue
            if "x-vocabulary" in f or "x-file-ref" in f:
                picked = [v for v in form.getlist(name) if str(v).strip()]
            else:
                raw = str(form.get(name) or "")
                picked = [
                    part.strip()
                    for chunk in raw.splitlines()
                    for part in chunk.split(",")
                    if part.strip()
                ]
            args.pop(name, None)
            if picked:
                args[name] = picked
        # Notes are parallel lists — one `note_type` and one `note_text` per row
        # — so removing a row leaves no numbering gap to reassemble and there is
        # no row limit to silently exceed (the Groovy stopped at 20).
        if "notes" in props:
            kinds = form.getlist("note_type")
            texts = form.getlist("note_text")
            notes = [
                {"type": kinds[i] if i < len(kinds) else "note", "text": t.strip()}
                for i, t in enumerate(texts)
                if str(t).strip()
            ]
            for key in ("note_type", "note_text"):
                args.pop(key, None)
            if notes:
                args["notes"] = notes

        # What the user actually typed, kept verbatim for redisplay. `args` gets
        # numbers coerced for the tool call, and echoing those back turns "15"
        # into "15.0" in the field they typed it into.
        typed = dict(args)
        if file_location:
            typed["file_location"] = file_location
        # qrcode is derived, never submitted (EXTRACTION D1); numbers are typed.
        args.pop("qrcode", None)
        # Coerce by SCHEMA, not by a hard-coded field list. HTML posts strings,
        # and `validate_args` enforces declared types, so every numeric field
        # needs converting. The old list named height and width; RDF Digital
        # added `depth` and every submit failed with "must be number, got str"
        # — per-form knowledge in a shared path is exactly what cycle 2 was
        # supposed to shake out.
        numeric = {name for name, f in props.items() if f.get("type") == "number"}
        for name in numeric & set(args):
            try:
                args[name] = float(args[name])
            except (TypeError, ValueError):
                pass  # leave it; validate_args reports it properly

        # EVERY file-ref field, derived from the same schema the ingest loop
        # below reads. Deriving both from one source is the actual fix here: the
        # check used to name `image` literally, so `image3d` and `video` were
        # ingested with no collision check at all and could overwrite a
        # published work's mesh or video in silence. A field list written out by
        # hand falls behind the schema the moment a field is added — which is
        # exactly what happened.
        file_fields = [
            (name, f.get("x-file-ref"), f.get("x-file-kind", "image"))
            for name, f in (
                (schema or {}).get("inputSchema", {}).get("properties", {}) or {}
            ).items()
            if "x-file-ref" in f
        ]
        # A file field may hold one name or several (the entity form takes a
        # list of images). Flattened here so the collision check and the ingest
        # below both see every file, whatever the field's arity.
        def _names(value) -> list[str]:
            if isinstance(value, str):
                return [value] if value else []
            if isinstance(value, list):
                return [str(v) for v in value if str(v).strip()]
            return []

        # NORMALIZE before anything else looks at these names. A filename with
        # a space in it is not merely awkward: it is joined to the image or
        # documents base and becomes the IRI the record points at, and a space
        # in an IRI is invalid. Rick has been collapsing names by hand before
        # every entry; that cannot be asked of other users.
        #
        # `args` gets the NORMALIZED names — they are what the record will cite
        # and what lands in the sandbox — while `typed` keeps the ORIGINALS, so
        # a form redisplayed after a refusal still shows the drop-folder file
        # the user actually picked (the picker lists the folder's own names, and
        # a normalized value would match no option and lose the selection).
        # AN IMAGE IS NAMED AFTER THE WORK, not after the camera (2026-10-05).
        # Restoring `support/ImageMgt.groovy:179` — `camelCase(title).jpg` —
        # which the port lost when it split naming from branding. The filename
        # is the last segment of the IRI the record cites AND of the URL on the
        # artist's site, so `IMG_2104.jpg` is what a visitor sees.
        #
        # Only the kinds config names, which is `image` by default: a document
        # arrives as `ChatGPT-ArtCriticism…-20261005-1348.md` and that name says
        # which assistant and when, so renaming it to the label DESTROYS
        # information. A mesh and a video are hand-named for the same reason.
        # The others still get `normalize_filename`, because a space in a name
        # is an invalid IRI whatever the name came from.
        #
        # The ordinal runs ACROSS the record's image fields, not within one:
        # two fields each starting at 1 would mint the same name twice.
        # TWO CONDITIONS, deliberately orthogonal. The FORM decides whether a
        # file is named after the record at all — a work's image is the work,
        # an entity's image is a reference to something already called
        # something else. The CONFIG decides which kinds, within a form that
        # does: a camera's `IMG_2104.JPG` carries no information, an export's
        # `ChatGPT-…-20261005-1348.md` carries which assistant and when.
        label_for_files = str(args.get("label", "")).strip()
        from_label = (cfgmod.name_from_label_kinds(cfg or {})
                      if spec.get("name_from_label") else ())
        ordinal = 0

        # ONLY A FILE ARRIVING FROM THE DROP FOLDER IS RENAMED. The picker also
        # offers files already in the sandbox from an earlier entry, and those
        # keep their names: the ingest has nothing to copy for one, so renaming
        # its reference points the record at a path no file will ever occupy —
        # which the asset gate catches as a dangling reference, after the fact.
        # It is law 12's own rule restated: names are decided on INGRESS, and
        # existing content is never re-processed.
        def _in_drop(kind: str, fname: str) -> bool:
            if inbox_val is None:
                return False
            try:
                return any(f.name == fname for f in inbox_val.list(kind))
            except Exception:
                return False

        # A LABEL COLLISION TAKES AN ORDINAL; it is not a refusal (Rick,
        # 2026-10-07: "Since labels are not guaranteed unique, for a name
        # collision the label-rename gets an ordinal"). Refusing would have
        # contradicted a decision already settled the other way — a reused
        # label only WARNS and still promotes, because titles legitimately
        # repeat.
        #
        # Bumped against what is ON DISK in the target subtree, because that is
        # what a write would actually overwrite, MINUS what this record already
        # cites — or re-submitting a draft would bump its own image one notch
        # on every pass.
        #: How many same-label works one name may disambiguate against. Twenty
        #: is far past anything real and keeps this to ONE dispatch instead of
        #: a loop of them.
        _ORDINAL_LIMIT = 20

        async def _taken_names(subtree: str, candidates: list) -> set:
            """Which of these names another record already cites.

            The SAME question the refusal below asks, asked first — bumping
            against the disk alone was not enough, because a name can be cited
            by a record whose file has not synced down, and the submit would
            then be refused for a collision the ordinal was supposed to absorb.
            """
            if not candidates:
                return set()
            base = _url_base_for(subtree)
            got = await run_in_threadpool(
                request.app.state.dash.dispatch, "record.check_uniqueness",
                {
                    "files": [base + c for c in candidates],
                    "exclude_subject": str(work_namespace(domain_val)[
                        str(args.get("guid") or "")]) if args.get("guid") else "",
                },
            )
            res = (got.get("result") or {}) if got.get("ok") else {}
            return {str(u).rsplit("/", 1)[-1] for u in (res.get("files_taken") or [])}

        def _mine() -> set:
            """Filenames THIS record already cites.

            Excluded from the disk check, or re-submitting a draft would bump
            its own image one notch on every pass: `Draft.jpg`, `Draft-2.jpg`,
            `Draft-3.jpg`, each leaving the last behind. A re-submit must land
            on the same name and replace, which is what the attic is for.
            `check_uniqueness` already excludes this subject for the same
            reason; this is the disk half of the same exclusion.
            """
            guid = str(args.get("guid") or "")
            if not guid:
                return set()
            path = f"{layout.dir('work_ttl').rstrip('/')}/{guid}.ttl"
            try:
                from rdflib import Graph as _G
                g = _G()
                g.parse(data=_trusted_fileops(sandbox_root, cfg).read_text(path),
                        format="turtle")
            except Exception:
                return set()
            return {str(o).rsplit("/", 1)[-1] for o in g.objects()
                    if str(o).startswith("http") and "/" in str(o)}

        def _on_disk(subtree: str) -> set:
            try:
                return {e.name for e in
                        _trusted_fileops(sandbox_root, cfg).list_dir(subtree)}
            except Exception:
                return set()

        renamed: list[tuple[str, str, str]] = []  # (field, from, to)
        derived_names: set[str] = set()  # names the RECORD chose, not the user
        for name, _sub, kind in file_fields:
            picked = _names(args.get(name))
            if not picked:
                continue
            fixed = []
            for value in picked:
                derived = ""
                if label_for_files and kind in from_label and _in_drop(kind, value):
                    ordinal += 1
                    sub = (_sub or layout.dir("image")).strip("/")
                    # Two reasons to bump, one counter: a second image OF THIS
                    # RECORD, and a name another record already holds. Labels
                    # are not unique and a repeated one has never been a
                    # blocking error, so the collision takes an ordinal rather
                    # than a refusal (Rick, 2026-10-07).
                    cands = [
                        inbox_mod.filename_from_label(
                            label_for_files, value, ordinal=o)
                        for o in range(ordinal, ordinal + _ORDINAL_LIMIT)
                    ]
                    cands = [c for c in cands if c]
                    unavailable = ((_on_disk(sub) | await _taken_names(sub, cands))
                                   - _mine())
                    for o, candidate in enumerate(cands, start=ordinal):
                        if candidate not in unavailable:
                            ordinal, derived = o, candidate
                            derived_names.add(candidate)
                            break
                # Falls back to the drop folder's own name when the label
                # yields no usable stem — better a camera name than `file.jpg`.
                fixed.append(derived or inbox_mod.normalize_filename(value))
            renamed += [
                (name, was, now) for was, now in zip(picked, fixed) if was != now
            ]
            args[name] = fixed if isinstance(args.get(name), list) else fixed[0]

        selected_files = [
            (name, sub, kind, fname)
            for name, sub, kind in file_fields
            for fname in _names(args.get(name))
        ]

        # Two different files normalizing to ONE name would have the second
        # quietly overwrite the first inside this single submission — which no
        # collision check against existing records can see, because neither file
        # is in the store yet.
        clashes = [
            (was, now) for (_f, was, now) in renamed
            if sum(1 for (_a, _b, _c, n) in selected_files if n == now) > 1
        ]
        if clashes:
            listed = ", ".join(f"{was!r} → {now!r}" for was, now in clashes)
            return await _render_form(
                request, spec, guid=args.get("guid"), values=typed, status=409,
                error=(
                    "Two of the files you chose normalize to the same name "
                    f"({listed}), so one would overwrite the other. Rename one "
                    "in your drop folder and pick it again. Everything you have "
                    "typed is kept — do not reload the page."
                ),
            )
        # Documents live under a different base than images, so a document name
        # checked against the image base would compare the wrong URI and find no
        # collision at all. Resolved from the field's SUBTREE rather than its
        # kind: the subtree is where the file lands, the base is that directory's
        # URL, and the pair cannot drift when a new kind is added (markdown and
        # pdf became two kinds the moment the entity form needed two pickers).
        checked_uris = [
            _url_base_for(sub) + fname
            for _name, sub, _kind, fname in selected_files
        ]

        # Uniqueness, BEFORE the ingest — the order is the point. copy_into
        # overwrites a same-named file in the sandbox, so checking after
        # ingesting would report the collision only once the damage was done.
        uniq = {}
        if checked_uris or args.get("label"):
            got = await run_in_threadpool(
                request.app.state.dash.dispatch,
                "record.check_uniqueness",
                {
                    "files": checked_uris,
                    "label": str(args.get("label", "")),
                    "type": str(args.get("type", "")),
                    # A RE-SUBMIT must not collide with its own draft. Since the
                    # draft is now kept when you go back to edit (rather than
                    # trashed on the intention), the record being rewritten
                    # already cites these files — and without this it reports
                    # the user's own image as taken by a record they are in the
                    # middle of correcting.
                    "exclude_subject": str(work_namespace(domain_val)[
                        str(args.get("guid") or "")]) if args.get("guid") else "",
                },
            )
            uniq = (got.get("result") or {}) if got.get("ok") else {}

        # Back from URIs to the filenames the user chose, which is what they can
        # act on — nobody renames a URI in their drop folder.
        taken_uris = set(uniq.get("files_taken") or [])
        taken = [
            fname for (_n, sub, _kind, fname) in selected_files
            if (_url_base_for(sub) + fname) in taken_uris
        ]
        if taken:
            # An ERROR, not a warning: a second work reusing a filename means the
            # ingest overwrites the first work's asset and convergence pushes the
            # new bytes to the same SOT path, silently replacing a published
            # work's picture, mesh or video. Only a rename fixes it, and only the
            # user can do that — the file is in their drop folder.
            #
            # Names the offending FIELDS, not just the files: with three pickers
            # sharing one folder, "already in use" without a field is a hunt.
            # Name the offending FIELD, and — when the clash is only a
            # difference in case — the EXISTING spelling. "SpiritedTree.jpg is
            # already in use" is a puzzle when the user is looking at
            # spiritedtree.JPG in their folder.
            matched = uniq.get("taken_uris") or {}
            parts = []
            for (fld, sub, _kind, fname) in selected_files:
                if fname not in taken:
                    continue
                existing = str(matched.get(_url_base_for(sub) + fname, "")).rsplit("/", 1)[-1]
                differs_only_by_case = (
                    existing and existing != fname and existing.lower() == fname.lower()
                )
                parts.append(
                    f"{fname!r} ({fld})"
                    + (f" — the store already has {existing!r}"
                       if differs_only_by_case else "")
                )
            listed = ", ".join(parts) or ", ".join(repr(t) for t in taken)
            many = len(taken) > 1
            plural = "s are" if many else " is"
            # WHAT TO CHANGE depends on where the name came from. A name DERIVED
            # from the label cannot be fixed in the drop folder — renaming the
            # file there changes nothing, because the record names it. Telling
            # the user otherwise sends them to do something that cannot work
            # (2026-10-07, when images started being named after the work).
            # Was THIS NAME derived, or did it come straight from the picker?
            # Asking "is this kind renameable" was wrong: an image already in
            # the sandbox is not renamed even on a form that renames, and for
            # that one the drop folder IS still the remedy.
            derived_clash = bool(set(taken) & derived_names)
            if derived_clash:
                fix = (
                    "These names come from this record's LABEL, so renaming "
                    "anything in your drop folder will not change them. Either "
                    "give this record a label of its own, or — if it is the "
                    "same work — edit the existing record instead of making a "
                    "second one."
                )
            else:
                rename = "Rename the files" if many else "Rename the file"
                fix = (
                    f"{rename} in your drop folder "
                    f"({inbox_val.root if inbox_val else 'the drop folder'}), "
                    "then use \u21bb Refresh list under that field and pick "
                    "the new name."
                )
            return await _render_form(
                request, spec, guid=args.get("guid"), values=typed, status=409,
                error=(
                    f"Filename{plural} already in use: {listed} "
                    "already referenced by another record. Submitting would "
                    f"overwrite that work's file. {fix} Everything you have "
                    "typed is kept — do not reload the page."
                ),
            )

        # Ingest the chosen image BEFORE writing the record. The user drops files
        # into the configured folder and never touches the sandbox; this copies
        # the selection in through FileOps, which mints the .ptr sidecar so the
        # binary is visible to promotion the moment it lands. Already-ingested
        # selections are a no-op, so re-running an entry is free.
        # EVERY file-ref field, not just `image`. RDF Digital adds `image3d`,
        # and ingesting only the first one would leave the .glb outside the
        # sandbox: vad:image3d would then dangle at the asset gate, or worse
        # reach SOT referencing a mesh that never converged — the hand-placed
        # binary defect, arriving by a new route.
        ingested_paths: list[str] = []
        if inbox_val is not None:
            # The SAME `file_fields` the collision check used, deliberately: the
            # set that gets ingested and the set that gets checked must be one
            # list, or they drift apart again.
            # original -> normalized, so the ingest can READ the drop folder's
            # own name and WRITE the system's.
            fixed_name = {was: now for (_f, was, now) in renamed}
            original_of = {now: was for was, now in fixed_name.items()}
            for name, subtree, kind in file_fields:
                for value in _names(args.get(name)):
                    source = original_of.get(value, value)
                    try:
                        res = await run_in_threadpool(
                            partial(
                                inbox_val.copy_into,
                                source,
                                _trusted_fileops(sandbox_root, cfg),
                                subtree or layout.dir("image"),
                                kind=kind,
                                dest_name=value,
                            )
                        )
                    except InboxError:
                        # Not in the drop folder — it may already be in the
                        # sandbox from an earlier entry, which the asset gate
                        # confirms or refuses. Not this step's decision.
                        continue
                    if res.get("copied"):
                        ingested_paths.append(res["path"])
                        _rec_ingest(request, res["path"])

        # Brand the images that just arrived, if asked (inventory #7, Brand
        # Image). AFTER the ingest and never inside it: the ingest is a verbatim,
        # idempotent copy, while the stamp is destructive and not repeatable, so
        # a re-run of an entry must not stamp a second time. Only files this
        # submit actually COPIED IN are branded — an image already in the store
        # belongs to a record that has been published with whatever it carries.
        branded: list[tuple[str, str]] = []
        if ingested_paths:
            image_subtrees = {
                (subtree or layout.dir("image")).strip("/")
                for name, subtree, kind in file_fields if kind == "image"
            }
            for path_ in ingested_paths:
                if path_.rsplit("/", 1)[0].strip("/") not in image_subtrees:
                    continue
                if not brand_signature:
                    # Reported with an empty signature, which the review renders
                    # as "not branded". An image arriving unstamped is a fact the
                    # reviewer needs before approving, not an absence.
                    branded.append((path_.rsplit("/", 1)[-1], ""))
                    continue
                stamp = await run_in_threadpool(
                    request.app.state.dash.dispatch, "image.brand",
                    {"path": path_, "signature": brand_signature},
                )
                if stamp.get("ok"):
                    branded.append((path_.rsplit("/", 1)[-1], brand_signature))
                else:
                    # Reported, never fatal: the record is sound and the image is
                    # the one the user chose. A missing font on a fresh install
                    # must not cost them the entry.
                    err = stamp.get("error") or {}
                    branded.append((path_.rsplit("/", 1)[-1],
                                    f"NOT branded — {err.get('message', 'failed')}"))

        # schema:duration is a fact about the file, so read it FROM the file
        # instead of asking the user to time their own video.
        #
        # Trusted-side only, and that is structural rather than stylistic: the
        # probe shells out to ffprobe, and the confined worker has no exec
        # (law 2). So it runs here and the answer reaches the record tool as an
        # ordinary string argument — the tool stays pure and the agent gains no
        # exec by the back door.
        #
        # A typed value always wins (it is the correction path), and a probe
        # that cannot answer — no ffmpeg, unreadable file, a container carrying
        # no duration — leaves the property off entirely. Omitting a fact is
        # correct; guessing one is not.
        if args.get("video") and not args.get("video_duration"):
            props = (schema or {}).get("inputSchema", {}).get("properties", {}) or {}
            subtree = (props.get("video") or {}).get("x-file-ref") or layout.dir("image")
            probed = await run_in_threadpool(
                probe_duration,
                sandbox_root / subtree.strip("/") / str(args["video"]),
            )
            if probed:
                args["video_duration"] = probed

        resp = await run_in_threadpool(
            request.app.state.dash.dispatch, spec["tool"], args
        )
        if not resp["ok"]:
            # The record was refused, so the files this submit copied in from
            # the drop folder belong to nothing. Left behind, they were
            # distributed with the NEXT approval, and the retry arrived as
            # `<name>-2.jpg` beside them (2026-11-21, found entering a work into
            # a git source of truth; Edit Record had the same fault fixed by
            # validating first). The drop folder still has the originals.
            # FileOps trashes a managed binary's sidecar with it.
            fo = _trusted_fileops(sandbox_root, cfg)
            for path_ in ingested_paths:
                try:
                    await run_in_threadpool(fo.trash, path_)
                except (FileNotFoundError, OSError):
                    pass
            err = resp.get("error") or {}
            code, msg = err.get("code", "error"), err.get("message", "")
            # A rule the user broke reads as a sentence; a fault they cannot act
            # on keeps its code, because that is the part worth reporting. The
            # rule itself lives in the tool, not here — the agent authors these
            # records too, and a rule only the form knows is a rule the agent
            # does not have.
            shown = msg if code == "missing_required" and msg else f"{code}: {msg}"
            return await _render_form(
                request, spec, guid=args.get("guid"), values=typed, status=400,
                error=shown + (
                    "  Everything you have typed is kept — do not reload the page."
                    if code == "missing_required" else ""
                ),
            )

        result = resp.get("result") or {}

        # A BOOTSTRAP record changes what the dashboard itself offers: a new
        # artist belongs in the next profile's picker, and a new profile is a
        # card. Both are read at registry-build time, so the build is redone
        # here rather than waiting for a refresh — "I made an artist and the
        # profile form says there are none" is the kind of correctness nobody
        # believes.
        #
        # The record is in QA and not yet promoted, and that is the right moment:
        # the review stop governs what reaches the SOT, not what the dashboard
        # can see in its own store.
        # EDITING one changes the same things: a renamed artist is a different
        # label in every picker, and an edited template is a different form
        # behind its card.
        if spec.get("workflow") in ("rdf_artist", "rdf_artist_profile",
                                    "rdf_artist_edit", "rdf_artist_profile_edit"):
            await run_in_threadpool(_reload_bootstrap, request.app)

        # A re-submit after "Edit form" supersedes an earlier attempt. Whatever
        # that attempt minted and this one did not produce — an image swapped
        # out, a QR for a guid that changed — is trashed NOW, when there is
        # something to replace it with, rather than on the intention to edit.
        prior = request.app.state.drafts.pop(
            str(result.get("guid") or args.get("guid") or ""), {})
        superseded = list(prior.get("minted") or []) if isinstance(prior, dict) else []

        created = [p for p in (result.get("path"), *(result.get("paths") or [])) if p]
        # Only paths this submission actually MINTED are discardable on edit. A
        # file already in the sandbox (copied=False) belongs to an earlier,
        # possibly committed, entry and must not be swept up.
        created.extend(ingested_paths)
        # The earlier attempt's leftovers are trashed further down, once the QR
        # and the provenance record have been written: both are REWRITTEN in
        # place on a re-submit, and trashing them first threw the provenance
        # away with its file location, then minted a fresh one.
        annotated: list[tuple[str, str]] = []

        # The QR JPEG is generated on submit, as the Groovy entry did
        # (ImageMgt.qrcode). The record derives `vad:qrcode` for every work, so
        # without this the asset-reference gate fails every single entry with a
        # dangling qrcode — which is exactly what the first real run produced.
        # Composed here rather than inside the record tool: the side effects stay
        # decomposed (CE_DESIGN §3.6), the workflow orchestrates them.
        # Stamp any markdown this record references with the record's own CURIE.
        # Concept derivation and tagging read that line to find the entity a
        # document belongs to; it has been a manual step until now, and only 5
        # of the 70 markdown files in the store carry it.
        #
        # Composed here rather than inside the record tool, like the QR code:
        # side effects stay decomposed and the workflow orchestrates them. It
        # runs AFTER the record is written because the CURIE is the record's,
        # and it goes through the registry (law 10) so the agent has the same
        # capability for the derivation workflow.
        curie = f"work:{result.get('guid', args.get('guid', ''))}"
        for name, subtree, kind in file_fields:
            if kind != "markdown":
                continue
            for value in _names(args.get(name)):
                stamped = await run_in_threadpool(
                    request.app.state.dash.dispatch,
                    "doc.set_id",
                    {"path": f"{(subtree or layout.dir('document')).rstrip('/')}/{value}",
                     "curie": curie},
                )
                if stamped.get("ok") and (stamped["result"] or {}).get("changed"):
                    annotated.append((value, curie))

        # Resolve the tag references to their labels, for the review stop.
        #
        # ADVISORY, never a refusal, and the distinction is not timidity: a tag
        # may legitimately run AHEAD of what it names. Rick's collection
        # workflow is exactly that — a work is tagged into a series collection
        # that gets created afterwards — and the store already holds one
        # dangling tag among 186. Refusing forward references would break a
        # workflow that is working.
        #
        # The label is the useful half. `work:53bfd31d-…` tells a reviewer
        # nothing; "Network-Art Aesthetic" tells them whether they tagged what
        # they meant to.
        tags_report = None
        if props.get("tags", {}).get("type") == "array":
            got = await run_in_threadpool(
                request.app.state.dash.dispatch,
                "record.resolve_tags",
                {"tags": _names(args.get("tags"))},
            )
            tags_report = (got.get("result") or {}) if got.get("ok") else {}

        if spec.get("qrcode", True):
            qr = await run_in_threadpool(
                request.app.state.dash.dispatch,
                "image.qrcode",
                {"guid": result.get("guid", args.get("guid", ""))},
            )
            if qr["ok"] and (qr.get("result") or {}).get("path"):
                created.append(qr["result"]["path"])

        # The incipient provenance. In `created`, so going back and re-submitting
        # finds it again; the tool keeps the item id for the same work. A refusal
        # is reported rather than fatal: the record is sound, and the review says
        # what is still owed before it is approved.
        disposition = None
        provenance_note = ""
        if spec.get("provenance"):
            made = await run_in_threadpool(
                request.app.state.dash.dispatch, "provenance.new_incipient",
                {"work": str(result.get("guid") or args.get("guid") or ""),
                 **({"file_location": file_location} if file_location else {})},
            )
            if made.get("ok"):
                disposition = made["result"]
                created.append(disposition["path"])
                if disposition.get("location_ignored"):
                    provenance_note = (
                        "The original file was not recorded: this kind of work is "
                        "stored as an object, so its provenance names no file.")
            else:
                provenance_note = (
                    "No provenance record was written: "
                    f"{(made.get('error') or {}).get('message', 'failed')}")

        # What the earlier attempt minted and this one did not produce.
        for stale in [p for p in superseded if p not in created]:
            await run_in_threadpool(
                request.app.state.dash.dispatch, "fs.trash", {"path": stale}
            )
        # Read the generated RDF back for the review page. Through `fs.read`, so
        # it stays confined and audited like every other file access (law 10) —
        # and reading it back from disk rather than echoing what the tool
        # returned means the page shows what was actually WRITTEN.
        sources = []
        for path in created:
            if not _gates_rdf(path):
                continue  # binaries (the QR) have nothing readable to show
            got = await run_in_threadpool(
                request.app.state.dash.dispatch, "fs.read", {"path": path}
            )
            if not got.get("ok"):
                continue
            text = (got.get("result") or {}).get("text", "")
            note = ""
            if len(text) > _SOURCE_LIMIT:
                text, note = text[:_SOURCE_LIMIT], f"truncated at {_SOURCE_LIMIT} chars"
            sources.append({"path": path, "text": text, "note": note})

        try:
            preview = await run_in_threadpool(
                partial(
                    _driver(request).preview,
                    workflow=spec["workflow"],
                    description=f"{spec['title']} {args.get('label', '')}".strip(),
                    context={"values": typed, "minted": list(created)},
                )
            )
        except HTTPException as exc:
            return HTMLResponse(
                render_review_page(
                    preview={}, created=created, sources=sources,
                    error=str(exc.detail),
                ),
                status_code=exc.status_code,
            )
        warning = ""
        if uniq.get("label_taken"):
            others = ", ".join(
                u.rsplit("/", 1)[-1] for u in uniq.get("label_matches", [])[:5]
            )
            warning = (
                f"Another {args.get('type', 'work')} already uses the label "
                f"{args.get('label')!r} ({others}). That is allowed — titles repeat — "
                "but if it was not intended, use Edit form to change it."
            )
        if provenance_note:
            warning = f"{warning} {provenance_note}".strip()
        # A failed gate leaves the record in QA and the page saying "go back to
        # change it" — which had nothing to click, because a unit that never
        # previewed has no token and the Edit-form button is built from one
        # (Rick, 2026-09-17). The way back is the form it came from, repopulated
        # from what was typed; the draft stays where it is and a re-submit
        # replaces it.
        back = None
        if preview.get("status") == "gates_failed":
            work_guid = str(result.get("guid") or args.get("guid") or "")
            if work_guid:
                request.app.state.drafts[work_guid] = {
                    "minted": list(created), "values": typed, "path": spec["path"],
                }
                back = {"href": f"/rdf/resume/{work_guid}",
                        "label": "Back to the form"}
        return HTMLResponse(
            render_review_page(
                preview=preview, created=created, sources=sources, warning=warning,
                renamed=renamed, annotated=annotated, tags=tags_report,
                branded=branded, back=back, disposition=disposition,
            )
        )

    def _bootstrap_in(paths) -> bool:
        """Did this change touch an artist or an artist profile?

        The cheap substring test the loaders use is not enough here, and the
        difference matters: **every profile-driven work record contains the word
        "Artist"**, because it cites `vad:hasArtistProfile`. Using the substring
        alone would rebuild the registry — re-parsing the ontology — on every
        work anyone creates. So the substring is only a gate on whether to
        parse, and the answer comes from the types the file actually declares.

        A DELETION counts without being read: the file is gone, so the question
        cannot be asked, and a profile that has just been removed is exactly the
        case where a stale registry keeps offering its form.
        """
        from rdflib import Graph
        from rdflib.namespace import RDF

        records = layout.dir("work_ttl").strip("/")
        for rel in paths or ():
            if not (rel.startswith(records + "/") and rel.endswith(".ttl")):
                continue
            full = Path(sandbox_root) / rel
            if not full.exists():
                return True
            try:
                text = full.read_text(errors="replace")
            except OSError:
                return True
            if not ("ArtistProfile" in text or "Artist" in text or "Painter" in text):
                continue
            try:
                graph = Graph().parse(data=text, format="turtle")
            except Exception:
                continue  # the gates judge a broken file; this only decides a reload
            for _subject, kind in graph.subject_objects(RDF.type):
                local = str(kind).rsplit("/", 1)[-1].rsplit("#", 1)[-1]
                if (local == "ArtistProfile" or local.endswith("Artist")
                        or local.endswith("Painter")):
                    return True
        return False

    @app.post("/rdf/entry/approve", response_class=HTMLResponse)
    async def rdf_entry_approve(request: Request) -> HTMLResponse:
        from .ux.forms import render_review_page

        form = await request.form()
        try:
            out = await run_in_threadpool(
                _driver(request).approve, str(form.get("token", ""))
            )
        except PromotionDriverError as exc:
            return HTMLResponse(
                render_review_page(preview={}, error=str(exc)), status_code=409
            )
        if out.get("status") not in ("stale",):
            _rec(request, "workflow.promote",
                 {"workflow": out.get("workflow") or "entry",
                  "description": out.get("description") or ""})

        # A CONVERGED PROFILE IS A DIFFERENT FORM. Creating one through the
        # bootstrap form rebuilds the registry on submit, so this never shows in
        # ordinary use — but a profile that arrives by SYNC or by script was
        # written by nobody the app can hear, and the card would then open a
        # form the registry has no tool for. Found the first time production's
        # profiles were imported (2026-09-27).
        if out.get("status") == "converged" and _bootstrap_in(out.get("paths")):
            await run_in_threadpool(_reload_bootstrap, request.app)

        code = 409 if out.get("status") == "stale" else 200
        return HTMLResponse(render_review_page(preview=out), status_code=code)

    @app.post("/rdf/entry/edit", response_class=HTMLResponse)
    async def rdf_entry_edit(request: Request) -> HTMLResponse:
        """Back to the form with the submitted values, the draft KEPT.

        This replaced "Reject", which only abandoned the promotion and left the
        record sitting in QA. The useful action after reviewing your own entry
        is almost always "that is not quite right, let me fix it", and that
        needs the form back with the values in it.

        **The draft is not trashed here** (Rick, 2026-09-17). It used to be,
        immediately — which meant that leaving the reopened form, refreshing, or
        cycling the server destroyed the record with nothing in the UI to say so.
        He lost an artist profile that way and asked the right question about it.
        A draft you can still see is a draft you can still finish.

        What the earlier attempt minted is remembered instead, and cleaned up
        when the NEXT submit succeeds: the record file is rewritten in place
        (same guid, same path), and anything the new attempt did not produce —
        an image swapped out, say — is trashed then. Nothing is destroyed on the
        strength of an intention.

        The draft does stay in QA meanwhile, which is exactly where an
        unapproved record lives, and the review stop lists it before anything
        converges — so an abandoned one is visible rather than silent.
        """
        from .tools.record_tools import qrcode_url
        from .ux.forms import render_entry_form

        form = await request.form()
        pending = _driver(request).take(str(form.get("token", "")))
        if pending is None:
            raise HTTPException(status_code=409, detail="unknown or already-decided token")

        ctx_data = pending.context or {}
        values = dict(ctx_data.get("values") or {})
        minted = [p for p in (ctx_data.get("minted") or [])]
        guid = str(values.get("guid") or "")
        if guid:
            # Remembered, not removed. The next successful submit for this guid
            # trashes whatever it did not itself produce. Held server-side and
            # keyed by guid: a hidden field naming sandbox paths to delete would
            # be a capability handed to whoever can craft a POST.
            request.app.state.drafts[guid] = {
                "minted": minted, "values": values, "path": spec_path_for(pending),
            }

        note = (
            f"Editing your entry. Your draft is still in QA ({len(minted)} file(s)) "
            "and will be replaced when you submit again — nothing has been thrown "
            "away."
        )
        # Back to whichever form produced it: the pending promotion recorded its
        # workflow, so an edited digital record returns to the digital form.
        spec = next(
            (f for f in _FORMS.values() if f["workflow"] == pending.workflow),
            _FORMS["entry"],
        )
        return await _render_form(
            request, spec, guid=values.get("guid"), values=values,
            editing=True, notice=note,
        )

    @app.post("/rdf/entry/reject", response_class=HTMLResponse)
    async def rdf_entry_reject(request: Request) -> HTMLResponse:
        from .ux.forms import render_review_page

        form = await request.form()
        try:
            out = await run_in_threadpool(
                _driver(request).reject, str(form.get("token", ""))
            )
        except PromotionDriverError as exc:
            return HTMLResponse(
                render_review_page(preview={}, error=str(exc)), status_code=409
            )
        return HTMLResponse(render_review_page(preview=out))

    # -- Instance control (Monitoring) ------------------------------------
    # Trusted-orchestrator network effect (law 11), never a registry tool: the
    # Landlock-confined worker cannot resolve a hostname, so a registered tool
    # would silently return nothing — the failure updateWorkOnSite already had.
    def _refresh_times(request: Request) -> Path:
        # Beside the audit log, which is beside the sandbox: outside the worker's
        # reach, and shared by every dashboard on this machine.
        return Path(request.app.state.dash.audit.path).with_name("instance-refreshes.json")

    @app.get("/instances", response_class=HTMLResponse)
    def instances_page(request: Request) -> HTMLResponse:
        from .ux.forms import render_instances_page

        # The hub's Monitoring nav item lands here. Nothing runs on GET: a link
        # that fired a refresh would also fire on a browser prefetch.
        from .ux.hub_chrome import hub_chrome

        return HTMLResponse(render_instances_page(
            targets=instances_val["targets"],
            refreshes=load_refreshes(_refresh_times(request)),
            chrome=hub_chrome(_hub_html(), "Monitoring"),
        ))

    @app.post("/api/instances/{action}")
    async def instances_run(action: str, request: Request, target: str = "") -> JSONResponse:
        """Run one action against one server, or all of them at once.

        The request names a TARGET; it never supplies a URL. The token minted
        for this call authenticates against whatever host it is sent to, so
        accepting a URL here would make the dashboard an SSRF proxy with the
        deployer's credential attached. `resolve_target` matches against the
        configured list and nothing else.
        """
        from .instances import ACTIONS, InstanceError, call_all, resolve_target

        if action not in ACTIONS:
            # Stop/cestfini lands here: there is no code path to it, and the
            # refusal names what IS available rather than hinting at more.
            return JSONResponse(
                {"error": f"unknown action {action!r}", "actions": list(ACTIONS)},
                status_code=404,
            )
        try:
            chosen = ([resolve_target(target, instances_val["targets"])]
                      if target else instances_val["targets"])
        except InstanceError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        if not chosen:
            return JSONResponse({"error": "no instances configured"}, status_code=404)

        try:
            results = await run_in_threadpool(
                partial(
                    call_all, chosen, action,
                    secrets_path=instances_val["secrets_path"],
                    timeout=instances_val["timeout_s"],
                    opener=instance_opener,
                )
            )
        except InstanceError as exc:
            # Could not be attempted at all — a missing secrets file, say. That
            # is a deployment fault, not a server being down, so it is one error
            # rather than N identical failures.
            return JSONResponse({"error": str(exc)}, status_code=503)

        # Audited like any other outward effect. The TOKEN never appears here:
        # it is a live credential with a 30-second life, and an append-only
        # hash-chained log is exactly the wrong place for one.
        dash: Dashboard = request.app.state.dash
        for r in results:
            dash.audit.record(
                "instance.command",
                {"action": action, "target": r["name"], "elapsed_ms": r["elapsed_ms"]},
                "ok" if r["ok"] else f"error:{r.get('error', '')[:40]}",
            )
        times = _refresh_times(request)
        await run_in_threadpool(record_refreshes, times, results)
        known = load_refreshes(times)
        for r in results:
            r["last_refresh"] = known.get(r["name"])
        return JSONResponse({"results": results})

    # -- Workflow board ------------------------------------------------------
    def _draft_guids(app_) -> dict:
        """{guid: is_new} for every undistributed record: the board's overlay.
        Read trusted-side, like the Drafts page, because it is git."""
        idx = _drafts_for(app_)
        if idx is None:
            return {}
        try:
            drafts, _ = idx.list()
        except Exception:
            return {}
        return {d["guid"]: bool(d.get("new")) for d in drafts}

    @app.get("/workflows", response_class=HTMLResponse)
    async def workflows_page(request: Request, wf: str = "",
                             finished: str = "") -> HTMLResponse:
        """One row per work, one column per step, derived from the records
        through the `workflow.board` tool (law 10)."""
        from .ux.board_page import render_board_page

        got = await run_in_threadpool(
            request.app.state.dash.dispatch, "workflow.board",
            {"include_finished": finished == "1"})
        drafts = await run_in_threadpool(_draft_guids, request.app)
        work_dir = layout.dir("work_ttl").strip("/")
        return HTMLResponse(render_board_page(
            got.get("result") if got.get("ok") else None,
            selected=wf, drafts=drafts,
            error="" if got.get("ok") else (got.get("error") or {}).get("message", "failed"),
            edit_link=lambda guid: "/edit/open?" + urlencode(
                {"path": f"{work_dir}/{guid}.ttl", "kind": "work"}),
        ))

    @app.post("/api/workflows/mark")
    async def workflows_mark(request: Request) -> JSONResponse:
        """Tick or untick a MANUAL step. The tool refuses any other kind."""
        try:
            body = await request.json()
        except Exception:
            body = None
        if not isinstance(body, dict):
            return JSONResponse({"ok": False, "error": {"code": "bad_json",
                                 "message": "body must be a JSON object"}}, status_code=400)
        args = {k: body[k] for k in ("workflow", "step", "work", "done") if k in body}
        resp = await run_in_threadpool(
            request.app.state.dash.dispatch, "workflow.mark_step", args)
        return JSONResponse({"ok": resp["ok"], "result": resp.get("result"),
                             "error": resp.get("error")})

    @app.post("/api/workflows/skip")
    async def workflows_skip(request: Request) -> JSONResponse:
        """Dismiss a step for one work as not needed, or restore it."""
        try:
            body = await request.json()
        except Exception:
            body = None
        if not isinstance(body, dict):
            return JSONResponse({"ok": False, "error": {"code": "bad_json",
                                 "message": "body must be a JSON object"}}, status_code=400)
        args = {k: body[k] for k in ("workflow", "step", "work", "skip", "reason")
                if k in body}
        resp = await run_in_threadpool(
            request.app.state.dash.dispatch, "workflow.skip_step", args)
        return JSONResponse({"ok": resp["ok"], "result": resp.get("result"),
                             "error": resp.get("error")})

    # -- cwva-py viewer --------------------------------------------------------
    # Trusted orchestrator, like Instance Control: it starts a process, so it
    # is a route and never a registry tool (laws 2 and 10).
    @app.get("/viewer", response_class=HTMLResponse)
    async def viewer_page(request: Request) -> HTMLResponse:
        from .ux.viewer_page import render_viewer_page

        v = request.app.state.viewer
        status = await run_in_threadpool(v.status) if v is not None else None
        return HTMLResponse(render_viewer_page(
            status, log=v.log_tail() if v is not None else "",
            label=(request.app.state.environment or {}).get("label", "")))

    @app.get("/api/viewer")
    async def viewer_status(request: Request) -> JSONResponse:
        v = request.app.state.viewer
        if v is None:
            return JSONResponse({"error": "no viewer configured"}, status_code=404)
        status = await run_in_threadpool(v.status)
        return JSONResponse({**status, "log": v.log_tail(15)})

    @app.post("/api/viewer/{action}")
    async def viewer_action(action: str, request: Request) -> JSONResponse:
        from .viewer import ViewerError

        v = request.app.state.viewer
        if v is None:
            return JSONResponse({"error": "no viewer configured"}, status_code=404)
        if action not in ("start", "stop", "reload"):
            return JSONResponse({"error": f"unknown action {action!r}"}, status_code=404)
        try:
            status = await run_in_threadpool(getattr(v, action))
        except ViewerError as exc:
            request.app.state.dash.audit.record(
                "viewer." + action, {"port": v.settings.port}, f"error:{str(exc)[:40]}")
            return JSONResponse({"error": str(exc)}, status_code=409)
        request.app.state.dash.audit.record(
            "viewer." + action, {"port": v.settings.port, "sandbox": status["sandbox"]}, "ok")
        return JSONResponse(status)

    # -- Files-tab utilities (#27/#28 syntax checks, #29 markdown) -----------
    # A file handed to these is read from the request, passed to a registry tool
    # as TEXT, and never stored: nothing here enters the sandbox (law 12) or
    # leaves it (law 1). The answer goes back to the browser.
    _UPLOAD_MAX = 20_000_000

    async def _uploaded_text(request: Request) -> tuple[str, str, str]:
        """(filename, text, error) from the form's `fileupload` field."""
        form = await request.form()
        up = form.get("fileupload")
        if up is None or not hasattr(up, "read"):
            return "", "", "no file was sent"
        data = await up.read(_UPLOAD_MAX + 1)
        name = Path(getattr(up, "filename", "") or "file").name
        if len(data) > _UPLOAD_MAX:
            return name, "", f"the file is larger than {_UPLOAD_MAX // 1_000_000} MB"
        try:
            return name, data.decode("utf-8-sig"), ""
        except UnicodeDecodeError as exc:
            return name, "", f"not UTF-8 text (byte {exc.start})"

    @app.post("/check", response_class=HTMLResponse)
    async def check_syntax_route(request: Request) -> HTMLResponse:
        """Syntax Check RDF/JSON: the parser is chosen by the file's extension."""
        from .tools.check_tools import EXTENSIONS
        from .ux.utility_pages import render_check_page

        name, text, err = await _uploaded_text(request)
        kind = EXTENSIONS.get(Path(name).suffix.lower(), "")
        if not err and not kind:
            err = ("cannot tell the format from the extension; use one of "
                   + " ".join(sorted(EXTENSIONS)))
        if err:
            return HTMLResponse(render_check_page(name, kind, None, error=err))
        got = await run_in_threadpool(request.app.state.dash.dispatch, "check.syntax",
                                      {"text": text, "kind": kind})
        return HTMLResponse(render_check_page(
            name, kind, got.get("result") if got.get("ok") else None,
            error="" if got.get("ok") else (got.get("error") or {}).get("message", "failed")))

    @app.post("/md2html")
    async def markdown_to_html(request: Request):
        """The converted document opens in a new tab (the hub form targets
        one): displayed, never saved, and without the instance banner, since
        it is the document and not a dashboard page."""
        from .ux.banner import NO_BANNER
        from .ux.utility_pages import render_check_page

        name, text, err = await _uploaded_text(request)
        if not err:
            got = await run_in_threadpool(request.app.state.dash.dispatch,
                                          "doc.render_markdown", {"text": text})
            if got.get("ok"):
                return HTMLResponse(got["result"]["html"], headers={NO_BANNER: "1"})
            err = (got.get("error") or {}).get("message", "conversion failed")
        return HTMLResponse(render_check_page(name, "markdown", None, error=err,
                                              heading="Markdown to HTML"),
                            status_code=400)

    def _download_name(name: str, suffix: str, ext: str, default: str = "image") -> str:
        # A header is latin-1 and a quote would end the value: keep the name
        # readable and safe rather than exact.
        stem = re.sub(r'[^\w .-]', "_", Path(name).stem, flags=re.ASCII).strip()
        return f"{stem or default}{suffix}{ext}"

    @app.post("/image/{op}")
    async def image_transform(op: str, request: Request):
        """Scale Image / Convert Image (#32/#33): the result downloads, named
        for the original; nothing is stored."""
        import base64

        from fastapi.responses import Response

        from .ux.utility_pages import render_check_page

        if op not in ("scale", "convert"):
            raise HTTPException(status_code=404)
        heading = "Scale Image" if op == "scale" else "Convert Image"
        form = await request.form()
        up = form.get("fileupload")
        err, name = "", ""
        if up is None or not hasattr(up, "read"):
            err = "no file was sent"
        else:
            name = Path(getattr(up, "filename", "") or "image").name
            data = await up.read(_UPLOAD_MAX * 2 + 1)
            args = {"data_b64": base64.b64encode(data).decode("ascii"), "op": op}
            try:
                if op == "scale":
                    args["factor"] = float(form.get("scale") or 0)
                else:
                    args["format"] = str(form.get("format") or "")
            except ValueError:
                err = "the scale factor must be a number, e.g. 0.25"
            if not err:
                got = await run_in_threadpool(request.app.state.dash.dispatch,
                                              "image.transform", args)
                if got.get("ok"):
                    r = got["result"]
                    w, h = r["size"]
                    out = _download_name(name, f"-{w}x{h}" if op == "scale" else "",
                                         r["ext"])
                    return Response(
                        base64.b64decode(r["data_b64"]),
                        media_type=f"image/{r['format'].lower()}"
                        if r["format"] != "PDF" else "application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{out}"'})
                err = (got.get("error") or {}).get("message", "failed")
        return HTMLResponse(render_check_page(name, "image", None, error=err,
                                              heading=heading), status_code=400)

    # -- About (the nav bar's last item) --------------------------------------
    @app.get("/about/assistant-guide.md")
    def assistant_guide():
        """The one-file guide to hand an AI assistant (docs/ASSISTANT_GUIDE.md),
        as plain Markdown to save or paste."""
        from fastapi.responses import PlainTextResponse

        guide = Path(__file__).resolve().parents[2] / "docs" / "ASSISTANT_GUIDE.md"
        return PlainTextResponse(guide.read_text(encoding="utf-8"),
                                 media_type="text/markdown; charset=utf-8")

    @app.get("/about", response_class=HTMLResponse)
    @app.get("/about/{slug}", response_class=HTMLResponse)
    def about_page(slug: str = "") -> HTMLResponse:
        """The project's documentation (docs/about/), with the hub's header."""
        from .ux.about_pages import AboutDocs, render_about_page
        from .ux.hub_chrome import hub_chrome

        docs = AboutDocs()
        page = docs.page(slug) if slug else (docs.pages() or [None])[0]
        from . import rson as _rson

        raw = _rson.load(str(docs.root / "contents.rson")) or {}
        upcoming = [p["title"] for p in raw.get("parts", []) if not p.get("pages")]
        return HTMLResponse(
            render_about_page(docs, page, hub_chrome(_hub_html(), "About"),
                              upcoming=upcoming),
            status_code=200 if page else 404)

    # -- Reports (Tools tab) ---------------------------------------------------
    # Documents to print, so no instance banner (Rick, 2026-11-19): NO_BANNER.
    from .ux.banner import NO_BANNER
    @app.get("/report/storage", response_class=HTMLResponse)
    async def storage_report(request: Request, storage_class: str = "") -> HTMLResponse:
        """DispId, title and thumbnail for one storage class, in DI order. Run
        on the production dashboard it is production's data."""
        from .ux.report_pages import render_storage_report

        got = await run_in_threadpool(request.app.state.dash.dispatch, "report.storage",
                                      {"storage_class": storage_class})
        return HTMLResponse(render_storage_report(
            got.get("result") if got.get("ok") else None,
            error="" if got.get("ok") else (got.get("error") or {}).get("message", "failed"),
            instance=(request.app.state.environment or {}).get("label", "")), headers={NO_BANNER: "1"})

    @app.get("/certificate", response_class=HTMLResponse)
    async def certificate_page(request: Request, guid: str = "") -> HTMLResponse:
        """Generate Certificate (#20): the hub form's GET, a work's GUID."""
        from .ux.report_pages import render_certificate

        got = await run_in_threadpool(request.app.state.dash.dispatch,
                                      "report.certificate", {"guid": guid})
        return HTMLResponse(render_certificate(
            got.get("result") if got.get("ok") else None,
            error="" if got.get("ok") else (got.get("error") or {}).get("message", "failed")), headers={NO_BANNER: "1"})

    @app.get("/report/registry", response_class=HTMLResponse)
    async def registry_report(request: Request, profile: str = "") -> HTMLResponse:
        """Print Registry (#19): one artist profile's works, or the profiles."""
        from .ux.report_pages import render_registry_page

        got = await run_in_threadpool(request.app.state.dash.dispatch, "report.registry",
                                      {"profile": profile})
        return HTMLResponse(render_registry_page(
            got.get("result") if got.get("ok") else None,
            error="" if got.get("ok") else (got.get("error") or {}).get("message", "failed"),
            instance=(request.app.state.environment or {}).get("label", "")), headers={NO_BANNER: "1"})

    # -- SPARQL browser (#17) ---------------------------------------------
    @app.get("/sparql", response_class=HTMLResponse)
    async def sparql_page(request: Request, query: str = "",
                          format: str = "HTML") -> HTMLResponse:  # noqa: A002
        """The hub's SPARQL card. Read-only, over the sandbox, through the
        registry like everything else (law 10): GET, so a query is a URL."""
        from .ux.forms import render_sparql_page

        result, error, ms = None, "", 0
        if query.strip():
            started = time.monotonic()
            got = await run_in_threadpool(
                request.app.state.dash.dispatch, "rdf.sparql_store", {"query": query})
            ms = int((time.monotonic() - started) * 1000)
            if got.get("ok"):
                result = got["result"]
            else:
                error = (got.get("error") or {}).get("message", "query failed")
        return HTMLResponse(render_sparql_page(
            query=query, fmt=format, result=result, error=error, ms=ms,
            work_ns=str(work_namespace(domain_val))))

    # -- QA backup --------------------------------------------------------
    # Trusted-orchestrator, like ingest and the promotion tail, and for the same
    # structural reason: it writes OUTSIDE the sandbox. A repository cannot back
    # itself up into itself, so the bundle is built in a temp dir and put in the
    # target's `operational/` prefix — not content, never synced back, not a
    # promotion. Never a registry tool; the confined worker reaches none of it.
    def _backup_context() -> dict:
        from .backup import BUNDLE_NAME, OPERATIONAL_PREFIX, attic_status

        drv = getattr(app.state, "promotion_driver", None)
        ctx = {"attic": attic_status(sandbox_root), "commits": 0, "last": None}
        if drv is None:
            return ctx
        try:
            ctx["commits"] = int(drv.qa._run("rev-list", "--count", "HEAD") or 0)
        except Exception:
            ctx["commits"] = 0
        # Is there a backup in SOT, and how old? Read through the transport's
        # own snapshot so any transport can answer.
        try:
            snap = drv.transport.snapshot()
            key = f"{OPERATIONAL_PREFIX}/{BUNDLE_NAME}"
            if key in snap:
                ctx["last"] = {"updated": "present", "bytes": 0}
        except Exception:
            pass
        return ctx

    @app.get("/backup", response_class=HTMLResponse)
    async def backup_status(request: Request) -> HTMLResponse:
        from .ux.forms import render_backup_page

        ctx = await run_in_threadpool(_backup_context)
        return HTMLResponse(render_backup_page(**ctx))

    @app.post("/backup", response_class=HTMLResponse)
    async def backup_run(request: Request) -> HTMLResponse:
        from .backup import run_backup
        from .ux.forms import render_backup_page

        drv = _driver(request)
        try:
            res = await run_in_threadpool(run_backup, sandbox_root, drv.transport)
            result = res.to_dict()
        except NotImplementedError as exc:
            result = {"ok": False, "error": str(exc)}
        except Exception as exc:  # a backup that fails must say so, not vanish
            result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        ctx = await run_in_threadpool(_backup_context)
        return HTMLResponse(
            render_backup_page(**ctx, result=result),
            status_code=200 if result.get("ok") else 502,
        )

    # -- Edit a record ----------------------------------------------------
    # File-based, not instance-based: a subject's triples are spread across
    # files (the work in its own TTL, its site presence in a snapshot), so
    # "edit this instance" has no single target. What a user can coherently
    # edit is one file — and because the editor shows the WHOLE file, writing
    # it back whole cannot drop what it never rendered.
    @app.get("/edit", response_class=HTMLResponse)
    async def edit_picker(request: Request, kind: str = "") -> HTMLResponse:
        from .ux.forms import render_edit_picker

        group = _edit_kind(kind)
        return HTMLResponse(render_edit_picker(
            records=await _editable(request, group), kind=group))

    def _edit_file_kinds() -> dict:
        from .tools.edit_tools import file_field_kinds

        return file_field_kinds(request_registry())

    def request_registry():
        return app.state.dash.registry

    def _drop_candidates(kind: str) -> list[dict]:
        """What a file field offers: THE DROP FOLDER, and nothing else.

        Everything already in the store got there by being associated with a
        record, so offering it invites pointing two records at one file — which
        passes every gate, because the file genuinely exists. The remedy for a
        wrong image is a new file, and new files arrive in the drop folder.

        Names are shown as they will BE after normalisation, since that is what
        the record ends up citing.
        """
        if inbox_val is None:
            return []
        out = []
        for f in inbox_val.list(kind):
            final = inbox_mod.normalize_filename(f.name)
            out.append({
                "value": final,
                "label": final + ("" if final == f.name else f"  (dropped as {f.name})"),
            })
        return out

    def _same_document(dropped: bytes, stored: bytes | None, kind: str) -> bool:
        """Is the drop-folder copy what is already stored? A stored markdown has
        gained an `[id=…]` line its source does not have, so bytes alone would
        call every markdown changed."""
        if kind != "markdown" or stored is None:
            return dropped == stored
        def body(data: bytes) -> list[str]:
            return [ln for ln in data.decode("utf-8", "replace").splitlines()
                    if not ID_LINE.match(ln)]
        return body(dropped) == body(stored)

    def _edit_candidates(kind: str, current: str, subtree: str) -> list[dict]:
        """What an EDIT form's file picker offers. One function for the rendered
        page and for Refresh list, which used to return raw drop-folder names
        while the page showed normalised ones — so a name with a space could be
        picked after a refresh and nowhere else (2026-11-05).

        A record's document keeps its name and takes new bytes, so the labels
        say what a pick will do. The file with the SAME name is offered only
        when its bytes differ: the drop folder keeps its files forever, so one
        offered unconditionally is an invitation to put an old copy back.
        """
        out = _drop_candidates(kind)
        if kind not in edit_tools.DOCUMENT_KINDS or not current or "," in current:
            return out
        ops = _trusted_fileops(sandbox_root, cfg)
        try:
            stored = ops.read_bytes(f"{subtree.rstrip('/')}/{current}")
        except Exception:
            stored = None  # cited but absent: any drop-folder copy is an update
        offered = []
        for cand in out:
            if cand["value"] != current:
                offered.append({**cand, "label": f"{cand['label']} — replaces {current}"})
                continue
            source = inbox_val.resolve(_drop_source_for(current, kind), kind)
            if not _same_document(source.read_bytes(), stored, kind):
                offered.append({
                    "value": edit_tools.REPLACE_WITH + current,
                    "label": f"{current} — replace with the drop-folder version",
                })
        return offered

    def _offer_files(instance: dict) -> dict:
        """Give every file field on a rendered edit form its candidates."""
        for f in instance.get("fields", []):
            if f.get("kind") == "file":
                f["candidates"] = _edit_candidates(
                    f.get("file_kind", "image"),
                    str(f.get("value") or "").strip(),
                    f.get("subtree") or layout.dir("image"),
                )
        return instance

    def _edit_kind(value) -> str:
        """The record GROUP being listed, from a query string that anyone can
        type. Anything unrecognised reads as works — the default group, not an
        error page: a mistyped `?kind=` should show you a list, not a refusal."""
        return ENTITIES if str(value or "").lower() == ENTITIES else WORKS

    async def _editable(request: Request, kind: str = WORKS) -> list:
        """The dropdown's contents. One dispatch, served from the shared file
        cache — the same list the picker page shows, because it is now the same
        widget on both.

        ``kind`` selects the group: works (typed as an `vad:ArtForm` subclass)
        or entities (`skos:inScheme the:entities`). One group at a time, because
        a merged list of 187 works and 161 entities is a list nobody scrolls.
        """
        got = await run_in_threadpool(
            request.app.state.dash.dispatch, "record.list_editable", {"kind": kind}
        )
        return (got.get("result") or {}).get("records", []) if got.get("ok") else []

    @app.get("/edit/open", response_class=HTMLResponse)
    async def edit_open(request: Request, path: str = "",
                        kind: str = "") -> HTMLResponse:
        from .ux.forms import render_edit_form

        group = _edit_kind(kind)
        got = await run_in_threadpool(
            request.app.state.dash.dispatch, "record.read_instance",
            {"path": path, "file_kinds": _edit_file_kinds()},
        )
        if not got.get("ok"):
            err = got.get("error") or {}
            return HTMLResponse(
                render_edit_form(
                    instance={"editable": False,
                              "reason": f"{err.get('code')}: {err.get('message')}"},
                    records=await _editable(request, group), kind=group,
                ),
                status_code=400,
            )
        instance = got["result"]
        # THE RECORD DECIDES WHICH LIST IT IS IN, not the URL. `?kind=` is a
        # hint anyone can omit — the Drafts page did — and a wrong one shows
        # the wrong tab over a dropdown that does not contain the record being
        # edited, so the browser displays its first option and Open navigates
        # somewhere else entirely (Rick, 2026-10-01).
        group = instance.get("group") or group
        _offer_files(instance)
        # No BRANDING picker: the answer is in the artist record, not in a
        # question. The record picker is a different thing and rides at the top
        # of the form, so changing which record you are editing does not mean
        # going back to a list.
        return HTMLResponse(render_edit_form(
            instance=instance, signatures=[],
            records=await _editable(request, group), kind=group,
            episode=_episode(request),
        ))

    @app.post("/edit/save", response_class=HTMLResponse)
    async def edit_save(request: Request) -> HTMLResponse:
        """Rewrite the file, then stop at the Distribute review like every other
        writer. Nothing reaches the SOT until it is approved."""
        from .ux.forms import render_edit_form, render_review_page

        form = await request.form()
        path = str(form.get("path") or "")
        _begin_episode(request, "edit_record", path)
        # `kind` is which LIST the record was picked from, carried so a refusal
        # re-renders the group the user is standing in rather than snapping back
        # to works. Keyed out of `values` with `path` and the signature, or
        # `write_instance` would try to assert it as a predicate.
        group = _edit_kind(form.get("kind"))
        values = {k: str(v) for k, v in form.items()
                  if k not in ("path", "kind", "brand_signature")}
        # An instruction about the arriving FILE, not a predicate of the record —
        # keyed out of `values` or write_instance would try to assert it.
        # Derived, not asked. `current` is the instance as it stands, read just
        # above for the collision check.
        brand_signature = ""

        # INGEST first, trusted-side: the drop folder is outside the sandbox and
        # the confined worker cannot read it (law 12). Only files whose field
        # actually changed are copied, so opening and saving a record does not
        # re-ingest everything it mentions.
        file_kinds = _edit_file_kinds()
        current = await run_in_threadpool(
            request.app.state.dash.dispatch, "record.read_instance",
            {"path": path, "file_kinds": file_kinds},
        )
        brand_signature = _brand_for_record(request.app, current.get("result") or {})
        # COLLISION CHECK BEFORE INGEST, exactly as the entry forms do, and for a
        # sharper reason here. A drop-folder file can NORMALISE onto a name
        # already in the store: `Spirited Tree.jpg` becomes `SpiritedTree.jpg`,
        # which may be another record's image. `copy_into` overwrites when the
        # bytes differ, so without this a save silently replaced a published
        # work's picture and every gate passed. Restricting the picker to the
        # drop folder removed the obvious route to that; it did not remove this
        # one.
        changed_files: list[tuple[dict, str]] = []
        #: submitted drop-folder name -> the name it is stored under, for a
        #: one-for-one replacement. The ingest reads the FIRST and writes the
        #: SECOND, which is the whole of the rule.
        replacements: dict[str, str] = {}
        same_name_replacements: set[str] = set()
        # The RECORD says which group it is in, not the form field — a save is
        # the wrong place to trust a hidden input about what kind of thing is
        # being edited.
        record_group = ((current.get("result") or {}).get("group")
                        if current.get("ok") else group) or group
        if current.get("ok"):
            for f in (current["result"].get("fields") or []):
                if f.get("kind") != "file":
                    continue
                # A multi-valued file field posts one name per SLOT, and the
                # collision check has to see every file the save would ingest —
                # joined the same way `write_instance` joins them, or a second
                # image could be ingested with no check at all. That is the
                # exact fault the entry form had when it named `image`
                # literally and let `image3d` through unchecked.
                #
                # A NEWLY PICKED name is normalised here, whatever the form sent:
                # a tab rendered before a refresh can still post a raw drop-folder
                # name. What the record already cites is left alone — the store's
                # `.JPG` references are not this save's business.
                existing = str(f.get("value") or "").strip()
                cited = {n.strip() for n in existing.split(",")}
                for key in ([it["name"] for it in f.get("items") or []]
                            or [f["predicate"]]):
                    picked = str(values.get(key, "")).strip()
                    if picked.startswith(edit_tools.REPLACE_WITH):
                        picked = picked[len(edit_tools.REPLACE_WITH):]
                        same_name_replacements.add(f["predicate"])
                    elif not picked or picked in cited:
                        continue
                    values[key] = inbox_mod.normalize_filename(picked)
                submitted = str(edit_tools.submitted_value(f, values)).strip()
                if f["predicate"] not in same_name_replacements and (
                        not submitted or submitted == existing):
                    continue
                names = [n.strip() for n in submitted.split(",") if n.strip()]

                # A ONE-FOR-ONE REPLACEMENT KEEPS THE NAME IT REPLACES (Rick,
                # 2026-10-07): "the replacement file gets the same name as the
                # file it replaces, no RDF update, just the replacement file
                # overwriting the binary in the SOT."
                #
                # Which is the right shape for a work: the record's image is
                # named after the record, so a new photograph of the same work
                # is still that work's image and should not acquire a second
                # name. The RDF does not change at all, the bytes are replaced
                # in place, and the superseded ones go to the attic.
                #
                # Narrow on purpose. For images, WORK records only, because an
                # entity's image is a reference to something with its own name
                # and entity has its own rules. And only when one value is
                # replaced by one value — a multi-valued field has no one-for-one
                # to speak of, and that is the deferred case.
                #
                # DOCUMENTS, on any record (Rick, 2026-11-05). A PDF or markdown
                # is an updated version of itself, and its name is the URL people
                # already hold: whichever file is picked supplies the bytes.
                file_kind = f.get("file_kind", "image")
                one_for_one = (
                    (file_kind in edit_tools.DOCUMENT_KINDS
                     or (file_kind == "image"
                         and record_group == edit_tools.WORKS))
                    and not f.get("items")        # a multi-slot field is not one
                    and len(names) == 1
                    and existing
                    and "," not in existing
                )
                if one_for_one:
                    # The RDF keeps citing the old name, so put it back into the
                    # values the writer will use. Keyed by PREDICATE, which is
                    # how `submitted_value` reads a single-valued field.
                    values[f["predicate"]] = existing
                    replacements[names[0]] = existing
                    changed_files.append((f, existing))
                    continue

                for name in names:
                    changed_files.append((f, name))

        if changed_files:
            base_for = {
                "markdown": docs_base_val, "pdf": docs_base_val,
            }
            uniq = await run_in_threadpool(
                request.app.state.dash.dispatch,
                "record.check_uniqueness",
                {
                    "files": [
                        base_for.get(f.get("file_kind", "image"), image_base_val) + n
                        for f, n in changed_files
                    ],
                    "exclude_subject": current["result"].get("subject_uri", ""),
                },
            )
            taken = set((uniq.get("result") or {}).get("files_taken") or [])
            if taken:
                clash = [
                    n for f, n in changed_files
                    if base_for.get(f.get("file_kind", "image"), image_base_val) + n in taken
                ]
                reread = await run_in_threadpool(
                    request.app.state.dash.dispatch, "record.read_instance",
                    {"path": path, "file_kinds": file_kinds},
                )
                inst = _offer_files(
                    reread.get("result") or {"editable": False, "reason": ""})
                # Renaming is the remedy only when the new file has a name of its
                # own. A replacement lands on the name this record cites, so no
                # rename can move it off the other record's file.
                remedy = (
                    "Replacing it would change that record's document too, so "
                    "nothing has been replaced."
                    if set(clash) <= set(replacements.values()) else
                    "Saving would overwrite that record's file with this one. "
                    "Rename it in your drop folder and reopen this record."
                )
                return HTMLResponse(
                    render_edit_form(
                        instance=inst, signatures=[],
                        records=await _editable(request, group), kind=group,
                        error=(
                            f"{', '.join(repr(c) for c in clash)} is already used by "
                            f"another record. {remedy}"
                        ),
                    ),
                    status_code=409,
                )

        async def _refused(err: dict) -> HTMLResponse:
            reread = await run_in_threadpool(
                request.app.state.dash.dispatch, "record.read_instance",
                {"path": path, "file_kinds": file_kinds},
            )
            return HTMLResponse(
                render_edit_form(
                    instance=_offer_files(
                        reread.get("result") or {"editable": False, "reason": ""}),
                    records=await _editable(request, group), kind=group,
                    error=f"{err.get('code', 'error')}: {err.get('message', '')}",
                ),
                status_code=400,
            )

        write_args = {"path": path, "values": values, "file_kinds": file_kinds,
                      "image_base": image_base_val, "documents_base": docs_base_val}
        # BEFORE THE INGEST: a refused save must leave nothing behind. It used to
        # copy the file first, so the refusal left a stray binary staged, and the
        # next approval of anything would have distributed it (2026-11-05).
        checked = await run_in_threadpool(
            request.app.state.dash.dispatch, "record.write_instance",
            {**write_args, "validate_only": True},
        )
        if not checked.get("ok"):
            return await _refused(checked.get("error") or {})

        # stored name -> the drop-folder name to read it from
        _submitted_for = {stored: sub for sub, stored in replacements.items()}
        ingested: list[str] = []
        not_replaced: list[str] = []
        if inbox_val is not None:
            for f, name in changed_files:
                if True:
                    try:
                        res = await run_in_threadpool(
                            partial(
                                inbox_val.copy_into,
                                _drop_source_for(
                                    _submitted_for.get(name, name),
                                    f.get("file_kind", "image")),
                                _trusted_fileops(sandbox_root, cfg),
                                f.get("subtree") or layout.dir("image"),
                                kind=f.get("file_kind", "image"),
                                dest_name=name,
                            )
                        )
                    except InboxError:
                        # Not in the drop folder; the gate will judge a new name.
                        # A replacement cites a file that exists, so no gate would
                        # notice that the new version never arrived.
                        if name in _submitted_for:
                            not_replaced.append(name)
                        continue
                    if res.get("copied"):
                        ingested.append(res["path"])
                        _rec_ingest(request, res["path"])

        # Brand what just arrived (inventory #7). Only images, only files this
        # save actually copied in, and only when asked — the same three limits
        # the entry path applies, for the same reason: the stamp is destructive
        # and stamping twice writes the signature over itself.
        branded: list[tuple[str, str]] = []
        if ingested:
            image_paths = {
                (f.get("subtree") or layout.dir("image")).rstrip("/") + "/" + name
                for f, name in changed_files if f.get("file_kind", "image") == "image"
            }
            for path_ in ingested:
                if path_ not in image_paths:
                    continue
                if not brand_signature:
                    branded.append((path_.rsplit("/", 1)[-1], ""))
                    continue
                stamp = await run_in_threadpool(
                    request.app.state.dash.dispatch, "image.brand",
                    {"path": path_, "signature": brand_signature},
                )
                short = path_.rsplit("/", 1)[-1]
                branded.append(
                    (short, brand_signature) if stamp.get("ok")
                    else (short, f"NOT branded — "
                          f"{(stamp.get('error') or {}).get('message', 'failed')}")
                )

        # A replaced video's DURATION is a fact about the new file, so it is
        # read from the file rather than asked for — trusted-side, because the
        # probe shells out to ffprobe and the confined worker has no exec
        # (law 2). Same split as the entry route: the effect here, the pure
        # answer passed to the tool as data.
        derived: dict = {}
        for f, name in changed_files:
            if f.get("file_kind") != "video":
                continue
            probed = await run_in_threadpool(
                probe_duration,
                sandbox_root / (f.get("subtree") or layout.dir("image")).strip("/") / name,
            )
            if probed:
                derived[f["predicate"]] = {"duration": probed}

        got = await run_in_threadpool(
            request.app.state.dash.dispatch,
            "record.write_instance",
            {**write_args, "derived": derived},
        )
        if not got.get("ok"):
            return await _refused(got.get("error") or {})

        result = got["result"] or {}

        # The record cites `vad:qrcode`; the file has to be there. Entry
        # generates it on submit, and an edit that rewrites a record whose QR is
        # missing must too — otherwise the only way to fix a dangling QR is to
        # enter the work again, which is what Rick had to try (2026-09-17). The
        # tool leaves an existing one alone, so this is cheap and idempotent.
        # `subject` comes back as the editor renders it — a CURIE (`work:w3`),
        # not a URI — so the GUID is the tail after the last separator of
        # EITHER kind. Taking only the path tail made a QR named after the
        # prefix, which is a second dangling reference, not a fix.
        subject = str(result.get("subject") or (current.get("result") or {}).get("subject_uri") or "")
        guid = subject.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]
        cites_qr = any(
            f.get("predicate") == "http://visualartsdna.org/model/qrcode"
            for f in ((current.get("result") or {}).get("fields") or [])
        )
        qr_note = ""
        if cites_qr and guid:
            made = await run_in_threadpool(
                request.app.state.dash.dispatch, "image.qrcode", {"guid": guid},
            )
            if not made.get("ok"):
                # Said out loud rather than left to the gate: the gate reports a
                # dangling reference, which is the symptom; this is the cause.
                qr_note = (" The QR code could not be generated: "
                           f"{(made.get('error') or {}).get('message', 'failed')}.")

        # The id line derivation and tagging read to find a document's entity.
        # The entry route stamps it; a file arriving here needs it just the same,
        # or replacing a markdown would silently disconnect it from its record.
        annotated: list[tuple[str, str]] = []
        stamp_note = ""
        for f, name in changed_files:
            if f.get("file_kind") != "markdown" or name in not_replaced:
                continue
            curie = f"work:{guid}"
            stamped = await run_in_threadpool(
                request.app.state.dash.dispatch, "doc.set_id",
                {"path": f"{(f.get('subtree') or layout.dir('document')).rstrip('/')}/{name}",
                 "curie": curie},
            )
            if not stamped.get("ok"):
                stamp_note += (f" {name} could not be stamped with {curie}: "
                               f"{(stamped.get('error') or {}).get('message', 'failed')}.")
            elif (stamped["result"] or {}).get("changed"):
                annotated.append((name, curie))

        warning = " ".join(result.get("warnings") or []) + qr_note + stamp_note
        if ingested:
            warning += (" Copied in from the drop folder: "
                        + ", ".join(p.rsplit("/", 1)[-1] for p in ingested) + ".")
        if not_replaced:
            warning += (" NOT replaced, because the file is no longer in the drop "
                        "folder: " + ", ".join(not_replaced) + ".")
        if result.get("cleared"):
            warning += (" Cleared: " + ", ".join(result["cleared"])
                        + ". Those statements were removed from the record.")
        preview = await run_in_threadpool(
            partial(
                _driver(request).preview,
                workflow="edit_record",
                description=f"Edit {result.get('subject', path)}",
                context={"values": {"path": path}, "minted": []},
            )
        )
        return HTMLResponse(
            render_review_page(
                preview=preview,
                created=[result.get("path")] if result.get("path") else [],
                warning=warning.strip(), branded=branded, annotated=annotated,
                back={"href": f"/edit/open?path={path}&kind={group}",
                      "label": "Back to the record"},
            )
        )

    # -- Annotate Work (#6, TCAP) ----------------------------------------
    def _drop_source_for(final_name: str, kind: str) -> str:
        """The drop-folder file whose NORMALISED name is `final_name`.

        The picker shows post-normalisation names, because that is what the
        record will cite; ingest needs the name on disk to read it back.
        """
        if inbox_val is None:
            return final_name
        for f in inbox_val.list(kind):
            if inbox_mod.normalize_filename(f.name) == final_name:
                return f.name
        return final_name

    def _annotate_context(request: Request) -> dict:
        dash: Dashboard = request.app.state.dash
        works = dash.dispatch("concept.list_annotatable", {})
        concepts = dash.dispatch("concept.list_concepts", {})
        res = (concepts.get("result") or {}) if concepts.get("ok") else {}
        return {
            "works": (works.get("result") or {}).get("works", []) if works.get("ok") else [],
            "schemes": res.get("schemes", []),
            "narrowed_by": res.get("narrowed_by", []),
            "tags_not_schemes": res.get("tags_not_schemes", []),
        }

    def _current_annotations(request: Request, work: str) -> tuple:
        """What already annotates this work: the ticks, and what lies outside
        the schemes this picker shows."""
        if not work:
            return set(), []
        got = request.app.state.dash.dispatch(
            "concept.current_annotations", {"subject": work}
        )
        if not got.get("ok"):
            return set(), []
        res = got.get("result") or {}
        return set(res.get("concepts", [])), list(res.get("outside", []))

    @app.get("/annotate", response_class=HTMLResponse)
    async def annotate_form(request: Request) -> HTMLResponse:
        """The picker, opened on what the work already says.

        Annotate Work EDITS an annotation now (Rick, 2026-09-18), so the page
        has to open ticked: submitting makes the selection the whole of the
        record's annotation, and a page that showed an empty selection would be
        a Clear button wearing an Annotate label.

        `?concepts=…` still wins when it is there — that is the review stop
        sending the user back with a selection they had not saved yet, and
        replacing it with the record's would throw away their work.
        """
        from .ux.forms import render_annotate_page

        ctx = await run_in_threadpool(_annotate_context, request)
        params = request.query_params
        # No `?work=`, and the page still has to be honest about which work its
        # Annotate button will rewrite: that is whatever the dropdown shows,
        # which is the first option.
        work = str(params.get("work") or "")
        if not work and ctx["works"]:
            work = str(ctx["works"][0]["value"])
        current, outside = await run_in_threadpool(
            _current_annotations, request, work)
        selected = (set(params.getlist("concepts")) if "concepts" in params
                    else current)
        return HTMLResponse(render_annotate_page(
            **ctx, selected_work=work, selected=selected, outside=outside,
            episode=_episode(request),
        ))

    @app.post("/annotate", response_class=HTMLResponse)
    async def annotate_submit(request: Request) -> HTMLResponse:
        """Annotate, then stop at the Distribute review like every other writer.

        The placement is the interesting part, so the review page shows what
        TCAP decided — which property each concept landed on, and any tie it
        refused to break — beside the usual gates and preview.
        """
        from .ux.forms import render_annotate_page, render_review_page

        form = await request.form()
        work = str(form.get("work") or "").strip()
        loaded_for = str(form.get("loaded_for") or "").strip()
        concepts = [c for c in form.getlist("concepts") if str(c).strip()]

        # THE PAGE MUST HAVE BEEN LOADED FOR THIS WORK. Submitting replaces the
        # work's whole annotation, and the ticks on screen are the ticks of
        # whatever work the page opened on — so a dropdown changed without a
        # reload (no JavaScript, or a tab left open since before) would write one
        # work's concepts over another's and call it an edit.
        if work and loaded_for and work != loaded_for:
            ctx = await run_in_threadpool(_annotate_context, request)
            return HTMLResponse(
                render_annotate_page(
                    **ctx, selected_work=work,
                    selected=(await run_in_threadpool(
                        _current_annotations, request, work))[0],
                    error=("You changed the work after this page loaded. Here it "
                           "is again with that work's own concepts ticked — what "
                           "was selected belonged to the one before it."),
                ),
                status_code=409,
            )

        # An EMPTY selection means "this work has no annotations" — which is a
        # real edit now that the page replaces rather than appends, and the only
        # way to undo an annotation. It is refused only when the work has none
        # to begin with, which is the original trap: a submit that writes
        # nothing and looks like it worked.
        current = ((await run_in_threadpool(_current_annotations, request, work))[0]
                   if work and not concepts else set())
        if not work or (not concepts and not current):
            ctx = await run_in_threadpool(_annotate_context, request)
            return HTMLResponse(
                render_annotate_page(
                    **ctx, selected_work=work, selected=set(concepts),
                    error=("Pick a work and at least one concept. Annotating with "
                           "nothing selected would write nothing and look like it "
                           "worked."),
                ),
                status_code=400,
            )

        _begin_episode(request, "annotate_work", work)
        resp = await run_in_threadpool(
            request.app.state.dash.dispatch,
            "concept.annotate_work",
            {"subject": work, "concepts": concepts},
        )
        if not resp["ok"]:
            err = resp.get("error") or {}
            ctx = await run_in_threadpool(_annotate_context, request)
            return HTMLResponse(
                render_annotate_page(
                    **ctx, selected_work=work, selected=set(concepts),
                    error=f"{err.get('code', 'error')}: {err.get('message', '')}",
                ),
                status_code=400,
            )

        result = resp.get("result") or {}
        preview = await run_in_threadpool(
            partial(
                _driver(request).preview,
                workflow="annotate_work",
                description=f"Annotate {work}",
                context={"values": {"work": work}, "minted": []},
            )
        )
        # Back to THIS page, with the selection intact — the selection you
        # submitted, not the record's, because that is the thing you might want
        # to adjust. Re-annotating REPLACES now, so going back and submitting
        # again is a complete correction rather than an addition to what the
        # first attempt did.
        from urllib.parse import urlencode

        back_url = "/annotate?" + urlencode(
            [("work", work)] + [("concepts", c) for c in concepts]
        )
        # The note that used to live here — "this is already written in QA and
        # leaving does not put it back" — was true, unguessable, and is now
        # false: leaving discards (promotion/episode.py). Rick, 2026-09-18:
        # "no user will understand it."
        return HTMLResponse(
            render_review_page(
                preview=preview,
                created=[result.get("path")] if result.get("path") else [],
                annotation=result,
                back={"href": back_url, "label": "Back to annotation"},
            )
        )

    # -- updateWorkOnSite (#9) ------------------------------------------
    # The ONE workflow that reaches outside the sandbox (law 11, read-only HTTP
    # to config-listed sites). It gets a confirm-first page for the same reason
    # promotion does: an effect the user never saw is an effect they cannot
    # judge. GET shows what is configured, POST performs the reads.
    @app.get("/site/update", response_class=HTMLResponse)
    def site_update_form(request: Request) -> HTMLResponse:
        from .tools.record_tools import work_namespace
        from .ux.forms import render_site_page

        # The page states the ACTUAL rule, built from the same namespace the
        # matcher uses. Describing it in prose let the copy outlive the rule: it
        # still advertised the 3D-viewer link and the bare CURIE a day after
        # both were dropped.
        return HTMLResponse(render_site_page(
            sites=list(sites_val or []),
            work_base=str(work_namespace(domain_val)),
        ))

    @app.post("/site/update", response_class=HTMLResponse)
    async def site_update_run(request: Request) -> HTMLResponse:
        from .ux.forms import render_site_page

        if not sites_val:
            return HTMLResponse(
                render_site_page(sites=[], error="No sites configured."),
                status_code=400,
            )
        # The FETCH is trusted-orchestrator work, like ingest and the promotion
        # tail. Not a policy choice: the Landlock-confined worker cannot resolve
        # a hostname — glibc's resolver needs /etc/resolv.conf and the NSS
        # libraries, which confinement denies — so a run from inside it returned
        # two empty snapshots and no reason. Measured: an IP-literal fetch from
        # the worker succeeds and a named-host fetch fails with EAI_AGAIN.
        #
        # What crosses into the worker is a list of GUIDs: data, not capability.
        # Extraction is a pure function over the fetched bytes, so performing it
        # here grants nothing the worker gives up.
        from .workflows.update_work_on_site import (
            UrllibFetcher,
            malformed_ref_pattern,
            observe_sites,
            work_ref_pattern,
        )

        # A work's canonical URI IS its subject URI, so the pattern is derived
        # from the work namespace rather than rebuilt. `host` covers a
        # deployment serving the catalogue somewhere other than the domain the
        # data names; they are equal when DNS is set.
        dom = domain_val
        serving = cfgmod.host(cfg) if cfg else None
        pattern = work_ref_pattern(dom, host=serving)
        observed = await run_in_threadpool(
            observe_sites, list(sites_val), site_fetcher or UrllibFetcher(),
            pattern, malformed_ref_pattern(dom, host=serving),
        )
        resp = await run_in_threadpool(
            request.app.state.dash.dispatch,
            "workflow.update_work_on_site",
            {"observations": [
                {"site": r.site, "declared": sorted(r.declared)} for r in observed
            ]},
        )
        if not resp["ok"]:
            err = resp.get("error") or {}
            return HTMLResponse(
                render_site_page(
                    sites=list(sites_val),
                    error=f"{err.get('code', 'error')}: {err.get('message', '')}",
                ),
                status_code=502,
            )
        # Pages read and errors seen belong to the trusted pass, so they are
        # merged back for the report rather than round-tripped through the tool.
        by_site = {r.site: r for r in observed}
        runs = []
        for run in (resp.get("result") or {}).get("runs", []):
            seen = by_site.get(run["site"])
            runs.append({
                **run,
                "pages": list(seen.pages) if seen else [],
                "errors": list(seen.errors) if seen else [],
                "malformed": list(seen.malformed) if seen else [],
            })
        from .tools.record_tools import work_namespace

        return HTMLResponse(
            render_site_page(runs=runs, work_base=str(work_namespace(dom)))
        )

    @app.post("/api/inbox/open")
    async def inbox_open(request: Request) -> JSONResponse:
        """Show the drop folder in the desktop's file manager.

        POST, not GET: a GET is something a prefetch, a back button or a link
        preview can fire, and this starts a process. The folder is the CONFIGURED
        one and is never taken from the request — a caller who could name a
        directory could name any directory, and "open this in a file manager" is
        a fine way to find out what is on a disk.

        It opens on whatever machine runs the dashboard, which is the user's own
        desktop in the deployment this is for, and is why the answer always
        carries the path: when there is nothing to launch, naming the folder is
        the whole point anyway.
        """
        from .inbox import open_folder

        if inbox_val is None:
            return JSONResponse({"ok": False, "error": "no drop folder configured"},
                                status_code=404)
        result = await run_in_threadpool(open_folder, inbox_val.root)
        dash.audit.record("inbox.open", {"path": result.get("path", ""),
                                         "opener": result.get("opener", "")},
                          "ok" if result.get("ok") else "error:open")
        return JSONResponse(result, status_code=200 if result.get("ok") else 503)

    @app.get("/api/health")
    def health(request: Request) -> dict:
        dash: Dashboard = request.app.state.dash
        return {
            "sandbox_root": str(sandbox_root),
            "landlock_abi": dash.worker.landlock_abi,
            "landlock_enforced": dash.worker.landlock_enforced,
            "tools": dash.registry.names(),
        }

    @app.get("/api/tools")
    def tools(request: Request) -> list[dict]:
        # MCP-shaped descriptors; the UX renders itself from these.
        return request.app.state.dash.registry.schemas()

    def _entity_ref_candidates(request: Request, referent: str) -> list[dict]:
        """Candidates for an ``x-entity-ref`` field, via the registry (law 10)."""
        resp = request.app.state.dash.dispatch(
            "record.list_referents", {"referent": referent}
        )
        if not resp.get("ok"):
            return []
        return (resp.get("result") or {}).get("candidates", [])

    def _file_ref_candidates(
        request: Request, subtree: str, kind: str = "image"
    ) -> list[dict]:
        """The files an `x-file-ref` field offers.

        ONE function, used by both the server-rendered form and the refresh
        endpoint. They must not drift: a picker that refreshes from a different
        source than it was rendered from is the offered-set divergence this
        project keeps paying for.
        """
        from .ux.affordance import (
            load_model_live,
            resolve_field_terms,
            resolve_file_ref,
        )
        from .tools.record_tools import WORK_FIELD_PROPERTIES

        if inbox_val is not None:
            return [f.to_dict() for f in inbox_val.list(kind)]
        # Sandbox fallback: filter to the same kind, or a 3D picker would list
        # every JPEG in the tree.
        allowed = tuple(
            (inbox_mod.DEFAULT_EXTENSIONS.get(kind) or ())
        )
        found = resolve_file_ref(request.app.state.dash.dispatch, subtree)
        if not allowed:
            return found
        return [f for f in found if f["value"].lower().endswith(allowed)]

    @app.get("/api/affordance/file-ref")
    async def file_ref(
        request: Request, subtree: str = "", kind: str = "image",
        edit: bool = False, current: str = "",
    ) -> JSONResponse:
        # Re-read on demand so a file renamed in the drop folder can be picked
        # up WITHOUT reloading the form — reloading would discard everything
        # typed, which is the whole reason this endpoint is called from the page.
        if edit and inbox_val is not None:
            # The edit form's own answer, so a refresh offers what the page did.
            cands = await run_in_threadpool(_edit_candidates, kind, current, subtree)
        else:
            cands = await run_in_threadpool(_file_ref_candidates, request, subtree, kind)
        return JSONResponse({"candidates": cands})

    @app.get("/api/affordance/vocabulary/{name}")
    def vocabulary(request: Request, name: str) -> JSONResponse:
        # x-vocabulary candidates by the same query the gate enforces (picker and
        # gate agree). Best-effort: empty until the vocabulary is synced.
        from .ux.affordance import resolve_vocabulary

        return JSONResponse(
            {"candidates": resolve_vocabulary(live["vocab_graph"], name)}
        )

    # -- the promotion tail (A0) ------------------------------------------
    # NOT registry tools, deliberately: promotion is the single gated exit
    # (law 1) and stays in the trusted orchestrator, so these routes call the
    # driver directly rather than dispatching into the confined worker. The
    # review STOP lives in the driver — /preview never converges, /approve
    # converges only the change that was reviewed.
    def _driver(request: Request):
        drv = getattr(request.app.state, "promotion_driver", None)
        if drv is None:
            raise HTTPException(
                status_code=503,
                detail="no promotion target configured (needs a SOT transport)",
            )
        return drv

    @app.post("/api/promotion/preview")
    async def promotion_preview(request: Request) -> JSONResponse:
        body = await _json_body(request)
        out = await run_in_threadpool(
            _driver(request).preview,
            workflow=body.get("workflow", "entry"),
            description=body.get("description", ""),
        )
        return JSONResponse(out)

    @app.post("/api/promotion/approve")
    async def promotion_approve(request: Request) -> JSONResponse:
        body = await _json_body(request)
        token = body.get("token")
        if not token:
            raise HTTPException(status_code=400, detail="token is required")
        try:
            out = await run_in_threadpool(_driver(request).approve, token)
        except PromotionDriverError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if out.get("status") not in ("stale",):
            _rec(request, "workflow.promote",
                 {"workflow": out.get("workflow") or "staged",
                  "description": out.get("description") or ""})
        # A stale approval is a refusal, not a success: the reviewed change is
        # not what is on disk any more, and nothing was converged.
        return JSONResponse(out, status_code=409 if out["status"] == "stale" else 200)

    @app.post("/api/promotion/reject")
    async def promotion_reject(request: Request) -> JSONResponse:
        body = await _json_body(request)
        token = body.get("token")
        if not token:
            raise HTTPException(status_code=400, detail="token is required")
        try:
            out = await run_in_threadpool(_driver(request).reject, token)
        except PromotionDriverError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return JSONResponse(out)

    @app.get("/api/promotion/pending")
    def promotion_pending(request: Request) -> JSONResponse:
        return JSONResponse({"pending": _driver(request).pending()})

    @app.get("/staged/preview", response_class=HTMLResponse)
    async def staged_preview(request: Request) -> HTMLResponse:
        """The review stop, reached from the staged tree rather than from a form.

        Every writer already ends here, and approving promotes the WHOLE staged
        tree — so this card adds no capability. What it adds is a door. Work can
        be staged with no form open: a session abandoned before approve, a
        record written and then cycled away from, and later an agent that
        authors while nobody is looking. Until now the only way to distribute
        that was to find something else to write.

        Deliberately GET and read-only: it runs the gates and builds the
        preview, exactly as `preview` does for a form, and converges nothing.
        The approve button on the page is the same one, posting the same token
        to the same route, so there is still exactly one gated exit (law 1).
        """
        from .ux.forms import render_review_page

        preview = await run_in_threadpool(
            partial(
                _driver(request).preview,
                workflow="staged",
                description="Distribute staged work",
                # No form produced this, so there are no values to return to and
                # nothing was minted for a later submit to replace. The review
                # page's back door is the dashboard instead of `Edit form`,
                # which would otherwise reopen a form this never came from.
                context={"values": {}, "minted": []},
            )
        )
        return HTMLResponse(render_review_page(
            preview=preview, back={"href": "/", "label": "dashboard"},
        ))

    def _drafts(request: Request):
        """The draft index over the QA repo, or None with no promotion target."""
        return _drafts_for(request.app)

    def _draft_link(app_, d: dict) -> str:
        """The way back into the editor that made this draft, with the draft in
        it (Rick, 2026-09-18).

        A record written from a profile form reopens in that form, repopulated —
        which is what `/rdf/resume/{guid}` is for, and the only route that can
        show an unfinished entry as its author left it. Anything else opens in
        Edit Record, which reads whatever is in the file. A draft the editor
        refuses (an aggregate, several subjects) gets no link rather than a
        broken one.
        """
        guid = d.get("guid", "")
        if d.get("new") and guid in app_.state.drafts:
            return f"/rdf/resume/{guid}"
        if d.get("subject"):
            return f"/edit/open?path={d['path']}"
        return ""

    # -- DTS: the queue surface and the curation stops --------------------
    #
    # The stages are library code (`dts/`), and these routes bind them the way
    # the annotate routes bind `workflows/annotate.py`. Headless first was
    # deliberate: everything below composes functions that were already driven
    # end to end from the command line.

    def _dts(request: Request):
        """The context every stage needs, from the same `app.state` the
        operator script builds from — so a driven run and a headless one
        cannot disagree about which tree they are in."""
        from .ai_service import AIService
        from .dts.pipeline import DTS

        st = request.app.state
        if getattr(st, "ai_service", None) is None:
            st.ai_service = AIService()
        return DTS(dispatch=st.dash.dispatch, layout=st.layout, domain=st.domain,
                   inbox=st.inbox,
                   trusted_ops=_trusted_fileops(st.dash.sandbox_root, cfg),
                   ai=st.ai_service, root=st.dash.sandbox_root)

    def _dts_store(request: Request):
        """The QA store as one graph. Read directly rather than through the
        tool: one dispatch per file over 460 files is how the ops quota has
        been blown four times."""
        from rdflib import Graph

        g = Graph()
        for path in sorted((Path(request.app.state.dash.sandbox_root)
                            / layout.dir("work_ttl").strip("/")).rglob("*.ttl")):
            try:
                g.parse(path, format="turtle")
            except Exception:
                continue
        for sub in ("vocab_ttl", "model_ttl"):
            for path in sorted((Path(request.app.state.dash.sandbox_root)
                                / layout.dir(sub).strip("/")).rglob("*.ttl")):
                try:
                    g.parse(path, format="turtle")
                except Exception:
                    continue
        return g

    def _dts_entities(graph):
        """Every DTS-eligible entity with its queue, from the stamps alone."""
        from rdflib import URIRef
        from rdflib.namespace import RDFS

        from .dts.state import THE, state_of

        out = []
        for subject in sorted(set(graph.subjects(None, THE.AI)), key=str):
            doc = graph.value(subject, THE.mdDocument)
            out.append({
                "uri": str(subject),
                "guid": str(subject).rstrip("/").rsplit("/", 1)[-1],
                "label": str(graph.value(subject, RDFS.label) or subject),
                "document": str(doc).rsplit("/", 1)[-1] if doc else "",
                "state": state_of(graph, subject),
            })
        return out

    #: The queues, in order, each with the stamp an entity is waiting for and
    #: the verb for what happens next. Data rather than code so the page and
    #: the routes cannot disagree about what a queue is called.
    _DTS_QUEUES = [
        ("derived", "Pending derivation", "entity created, not derived", "Derive"),
        ("derivationCurated", "Pending derivation curation",
         "derived, not curated", "Curate"),
        ("tagged", "Pending tagging", "derivation curated, not tagged", "Tag"),
        ("taggingCurated", "Pending tagging curation",
         "tagged, not curated", "Curate"),
        ("summarized", "Pending summarization",
         "tagging curated, not summarized", "Summarize"),
        ("summaryCurated", "Pending summary curation",
         "summarized, not curated", "Read"),
    ]

    def _dts_queues(graph):
        entities = _dts_entities(graph)
        return [
            {"state": state, "title": title, "rule": rule, "action": action,
             "entities": [e for e in entities if e["state"] == state]}
            for state, title, rule, action in _DTS_QUEUES
        ]

    def _dts_documents(graph) -> list:
        """Queue 0 — a markdown in the drop folder that no entity cites.

        A folder count rather than a rule about an entity, because nothing
        exists yet to carry state (§2.6).
        """
        from .dts.state import THE

        if inbox_val is None:
            return []
        cited = {str(o).rsplit("/", 1)[-1]
                 for o in graph.objects(None, THE.mdDocument)}
        out = []
        for f in inbox_val.list("markdown"):
            if inbox_mod.normalize_filename(f.name) not in cited:
                out.append(f.name)
        return sorted(out)

    @app.get("/dts", response_class=HTMLResponse)
    async def dts_page(request: Request, notice: str = "") -> HTMLResponse:
        from .ux.dts_pages import render_queues_page

        graph = await run_in_threadpool(_dts_store, request)
        return HTMLResponse(render_queues_page(
            queues=_dts_queues(graph),
            documents=_dts_documents(graph),
            notice=notice,
            works=_dts_work_rows(graph),
            unavailable=_dts(request).ai.availability(),
        ))

    async def _dts_entity(request: Request, guid: str):
        """One entity, with the graph it was read from."""
        graph = await run_in_threadpool(_dts_store, request)
        for e in _dts_entities(graph):
            if e["guid"] == guid:
                return e, graph
        raise HTTPException(status_code=404, detail=f"no DTS entity {guid}")

    def _entity_path(guid: str) -> str:
        return f"{layout.dir('work_ttl').rstrip('/')}/{guid}.ttl"

    def _dts_work_rows(graph) -> list:
        """The works a criticism could be about, NEWEST FIRST.

        The ontology says which types are works (`art_form_names`), the same
        answer the Edit Record picker and Annotate Work use — so a criticism
        cannot be tagged onto an artist or another criticism by a fuzzy match.

        **Date descending, undated last** (Rick, 2026-10-01), on the same key
        the Edit Record picker uses: "99% of the time you want to annotate or
        edit a work just entered", and a criticism is written about a work
        while it is still the one you were working on. `schema:datePublished`
        and never the file's mtime — the order has to be one a person can
        recognise, and mtime is when the SANDBOX last wrote the file, which a
        sync rewrites wholesale.
        """
        from rdflib import RDF, URIRef
        from rdflib.namespace import RDFS

        from .tools.record_tools import art_form_names
        from .ux.forms import rev_date

        forms = art_form_names(model_val) or set()
        if not forms:
            return []
        published = URIRef("https://schema.org/datePublished")
        rows = []
        for subject in set(graph.subjects(RDF.type, None)):
            types = {str(t).rsplit("/", 1)[-1] for t in graph.objects(subject, RDF.type)}
            label = graph.value(subject, RDFS.label)
            if not (types & forms and label):
                continue
            date = graph.value(subject, published)
            rows.append({"value": str(subject), "label": str(label),
                         "published": str(date) if date is not None else ""})
        return sorted(rows, key=lambda r: (not r["published"],
                                           rev_date(r["published"]),
                                           r["label"].lower()))

    def _dts_works(graph) -> dict:
        """`{uri: label}`, the shape `match_work` takes.

        A projection of `_dts_work_rows`, so the set the page OFFERS and the
        set the matcher SEARCHES cannot come apart.
        """
        return {r["value"]: r["label"] for r in _dts_work_rows(graph)}

    @app.post("/dts/entity/new", response_class=HTMLResponse)
    async def dts_generate_entity(request: Request) -> HTMLResponse:
        """Queue 0: make the entity the document implies, then open it.

        Derived, not asked for: the material from what the artist said when
        they asked for the criticism, the source from the export's headings,
        the work from the headings that name it. Everything it could not work
        out is left for the editor rather than invented — and it lands IN the
        editor, because the point is that a person corrects it before DTS runs.
        """
        from .dts.incipient import propose_entity
        from .dts.pipeline import create_entity
        from .ux.dts_pages import render_queues_page

        form = await request.form()
        name = str(form.get("doc") or "")
        dts = _dts(request)
        graph = await run_in_threadpool(_dts_store, request)
        if not name or name not in set(_dts_documents(graph)):
            return HTMLResponse(render_queues_page(
                queues=_dts_queues(graph), documents=_dts_documents(graph),
                works=_dts_work_rows(graph),
                error=(f"{name!r} is not a document waiting for an entity. It "
                       "may already have one, or have left the drop folder.")),
                status_code=404)

        try:
            text = await run_in_threadpool(
                lambda: Path(inbox_val.resolve(name, "markdown")).read_text(
                    encoding="utf-8"))
        except Exception as exc:
            return HTMLResponse(render_queues_page(
                queues=_dts_queues(graph), documents=_dts_documents(graph),
                works=_dts_work_rows(graph),
                error=f"{name}: {exc}"), status_code=400)

        proposal = await run_in_threadpool(
            partial(propose_entity, document=name, text=text, graph=graph,
                    works=_dts_works(graph), table=(cfg or {}).get("dts") or {},
                    prefixes={"the": "http://visualartsdna.org/thesaurus/"}))
        if not proposal.ready:
            # A document with no human turn cannot describe itself, and an
            # entity with an empty definition is worse than none.
            return HTMLResponse(render_queues_page(
                queues=_dts_queues(graph), documents=_dts_documents(graph),
                works=_dts_work_rows(graph),
                error=(f"{name}: no human turn found, so there is nothing to "
                       "use as the definition. Create it on the Entity form.")),
                status_code=400)

        # THE WORK THE USER NAMED WINS over the one the headings implied, and
        # supplies the one the matcher could not find. The editor renders one
        # field per predicate the record HAS, so an entity created with no
        # `the:tag` has no field to add one in — which made the derivation
        # note's "set it in the editor" advice unfollowable (Rick, 2026-10-01).
        # Validated against the same set the matcher searched, because a work
        # IRI arriving in a POST is a value from the page, not a fact.
        chosen = str(form.get("work") or "")
        if chosen and chosen not in _dts_works(graph):
            return HTMLResponse(render_queues_page(
                queues=_dts_queues(graph), documents=_dts_documents(graph),
                works=_dts_work_rows(graph),
                error=f"{chosen!r} is not a work in this store."),
                status_code=400)
        work_uri = chosen or proposal.work_uri
        if chosen and chosen != proposal.work_uri:
            # The record's `skos:note` is built from this evidence, so leaving
            # the matcher's "no work matched" line on a record that HAS one
            # would make the record lie about itself tomorrow.
            proposal.evidence = [row for row in proposal.evidence
                                 if row[0] != "work"]
            proposal.evidence.append(
                ("work", 1, [f"named on the generate card: "
                             f"{_dts_works(graph)[chosen]}"]))

        created = await run_in_threadpool(
            partial(create_entity, dts, label=proposal.label,
                    topic=proposal.topics, definition=proposal.definition,
                    md_document=name,
                    tags=[work_uri] if work_uri else None,
                    notes=[{"type": "note", "text": _dts_derivation_note(proposal)}]))
        return RedirectResponse(
            url=f"/edit/open?path={quote(created.path)}&kind=entity",
            status_code=303)

    def _dts_derivation_note(proposal) -> str:
        """What was derived and on what evidence, written onto the record.

        A `skos:note` rather than a screen message: the reviewer may come back
        to this record tomorrow, and "why does it say Digital" is a question
        the record should answer for itself.
        """
        lines = [f"Generated from {proposal.document}."]
        for kind, hits, sample in proposal.evidence:
            if sample:
                lines.append(f"{kind}: {'; '.join(sample)}")
        return clean_text_for_note(" ".join(lines))

    def clean_text_for_note(text: str) -> str:
        from .dts.documents import clean_text

        return clean_text(text)

    @app.get("/dts/entity", response_class=HTMLResponse)
    async def dts_entity(request: Request, guid: str = "") -> HTMLResponse:
        """Whatever this entity's queue calls for — propose, or curate.

        One door per entity rather than one per stage: the state decides what
        happens, which is the same rule the queues are built from, so a stale
        link cannot run the wrong step.
        """
        entity, graph = await _dts_entity(request, guid)
        state = entity["state"]
        if state in ("derived", "tagged", "summarized"):
            return await _dts_propose(request, entity, graph, state)
        if state in ("derivationCurated", "taggingCurated"):
            return await _dts_curate_form(request, entity, state, graph=graph)
        if state == "summaryCurated":
            return await _dts_summary_form(request, entity)
        return RedirectResponse(
            url="/dts?notice=" + quote(f"{entity['label']} is complete."),
            status_code=303)

    async def _dts_propose(request: Request, entity, graph, state) -> HTMLResponse:
        """Run the stage that proposes, then land on its curation screen.

        The call takes 30-60 seconds and runs in the threadpool, which blocks
        this request and nothing else. That is honest for a single-user
        dashboard and is the thing to revisit first when it stops being one:
        the review already notes the step should run off the request thread so
        the screen can say *unavailable until HH:MM* instead of hanging.
        """
        from .ux.dts_pages import render_queues_page

        dts = _dts(request)
        state_now = dts.ai.availability()
        if not state_now["available"]:
            return HTMLResponse(render_queues_page(
                queues=_dts_queues(graph), documents=_dts_documents(graph),
                works=_dts_work_rows(graph),
                unavailable=state_now), status_code=503)
        try:
            await run_in_threadpool(_dts_run_stage, request, dts, entity, graph, state)
        except Exception as exc:  # a stage failure is a message, not a 500
            return HTMLResponse(render_queues_page(
                queues=_dts_queues(graph), documents=_dts_documents(graph),
                works=_dts_work_rows(graph),
                error=f"{entity['label']}: {exc}"), status_code=400)
        return RedirectResponse(url=f"/dts/entity?guid={entity['guid']}",
                                status_code=303)

    def _dts_run_stage(request: Request, dts, entity, graph, state) -> None:
        """Propose, cache, record, stamp — the same four steps the operator
        script runs, composed from the same functions."""
        import json as _json

        from .dts import session as dts_session
        from .dts.derive import derive, record_derivation
        from .dts.summarize import record_summary, summarize
        from .dts.tag import record_tagging, tag
        from .dts.thesaurus import (format_for_prompt, read_label_index,
                                    read_scoped, schemes_for)

        prefixes = {"the": "http://visualartsdna.org/thesaurus/"}
        dts_cfg = (cfg or {}).get("dts") or {}
        path = _entity_path(entity["guid"])
        text = dts.document_text(entity["document"])
        from rdflib import URIRef as _URIRef

        topics = [str(t) for t in
                  graph.objects(_URIRef(entity["uri"]),
                                _URIRef("http://visualartsdna.org/thesaurus/topic"))]
        chosen = schemes_for(topics, dts_cfg, prefixes=prefixes)
        scoped = read_scoped(graph, chosen.get("context") or [], prefixes=prefixes)

        # BEFORE THE MODEL CALL. The recorder checks the order too, but by then
        # the call is paid for and the cached proposals a curator would see have
        # already been overwritten — which left one entity offering one set of
        # concepts while its evidence record stated another (2026-10-01).
        dts.expect_stage(path, entity["uri"], state)

        if state == "derived":
            res = derive(dts, entity_uri=entity["uri"],
                         document_name=entity["document"], document_text=text,
                         existing_block=format_for_prompt(scoped), scheme=chosen,
                         label_index=read_label_index(graph), thesaurus=graph,
                         limit=int(dts_cfg.get("derive_limit") or 0))
            payload = {"proposals": [p.__dict__ for p in res.proposals]}
        elif state == "tagged":
            res = tag(dts, entity_uri=entity["uri"],
                      document_name=entity["document"], document_text=text,
                      existing_block=format_for_prompt(scoped),
                      known_uris={c.uri for c in scoped}, thesaurus=graph,
                      limit=int(dts_cfg.get("tag_limit") or 0))
            payload = {"tags": [t.__dict__ for t in res.tags]}
        else:
            res = summarize(dts, entity_uri=entity["uri"],
                            document_name=entity["document"], document_text=text)
            payload = {"summary": res.summary, "notes": res.notes}
        if not res.ok:
            raise RuntimeError(res.error)

        stage_key = {"derived": "derive", "tagged": "tag",
                     "summarized": "summarize"}[state]
        dts.trusted_ops.write_text(
            f".qa/dts/{entity['guid']}/{stage_key}.json",
            _json.dumps({"entity": res.entity, "document": res.document,
                         "model": res.model, "input_tokens": res.input_tokens,
                         "output_tokens": res.output_tokens, **payload},
                        indent=2, default=lambda o: o.__dict__),
            make_parents=True)
        dts_session.current(dts)  # named now, so the vocab file has a home
        recorder = {"derived": record_derivation, "tagged": record_tagging,
                    "summarized": record_summary}[state]
        recorder(dts, res, entity_path=path)

    def _dts_cached(dts, guid: str, stage: str) -> dict:
        """The proposals a stage left for a curator."""
        import json as _json

        return _json.loads(dts.read_text(f".qa/dts/{guid}/{stage}.json"))

    def _dts_context(document: str, phrase: str):
        """The sentences around a grounding phrase, split for marking.

        Empty when there is no phrase or no document — a missing context is a
        missing context, and inventing a window would put words beside a
        proposal that nobody wrote near it.
        """
        from .dts.documents import sentences_around, split_on_phrase

        if not (document and phrase):
            return None
        context = sentences_around(document, phrase)
        return split_on_phrase(context, phrase) if context else None

    async def _dts_curate_form(request: Request, entity, state, graph=None,
                               error: str = "") -> HTMLResponse:
        """The include / exclude screen, built from what the stage proposed.

        Every default here comes from a finding the dashboard made, and every
        one is overridable — a reading, not a ruling. A duplicate defaults to
        reject because keeping it would create a second concept for a thing
        the store has; a proposal grounded in the artist's own words defaults
        to reject because the critic picked the association up rather than
        making it.
        """
        from .dts.derive import Proposal
        from .dts.grounding import Neighbour
        from .dts.tag import Tag
        from .ux.dts_pages import KEEP, REJECT, render_curation_page

        dts = _dts(request)
        # Read ONCE per screen: the context is computed from the document
        # rather than stored (the phrase is stored; a copy of the prose in
        # every concept would drift from the document it quotes).
        #
        # A document that cannot be read costs the context and NOTHING ELSE.
        # It can legitimately be absent — deleted, not yet synced, renamed —
        # and a curation screen that refused to open would strip a curator of
        # the decision over proposals that are perfectly judgeable without the
        # surrounding prose.
        document = ""
        if entity.get("document"):
            try:
                document = await run_in_threadpool(dts.document_text,
                                                   entity["document"])
            except Exception:
                document = ""
        if state == "derivationCurated":
            cached = _dts_cached(dts, entity["guid"], "derive")
            proposals = []
            for raw in cached["proposals"]:
                raw = dict(raw)
                near = [Neighbour(**n) for n in raw.pop("near", [])]
                proposals.append(Proposal(**{**raw, "near": near}))
            # RE-ASSESSED against the store as it is NOW, not as it was when
            # the model answered. Curating a batch moves the store underneath
            # the proposals: Rick curated one Three Graces document, which
            # minted `the:ThreeGraces`, and the other document's proposal for
            # the same concept was still marked `proposed` from derive time —
            # so the submit hit the mint-collision guard and 500'd instead of
            # the screen simply saying "duplicate" (2026-10-01).
            if graph is not None:
                from .dts.derive import reassess
                from .dts.thesaurus import read_label_index

                await run_in_threadpool(
                    partial(reassess, proposals,
                            label_index=read_label_index(graph), thesaurus=graph))
            items, counts = [], {}
            for p in proposals:
                counts[p.status] = counts.get(p.status, 0) + 1
                items.append({
                    "key": p.label, "label": p.label,
                    "definition": p.definition, "status": p.status,
                    "broader": p.broader_label,
                    "reference": p.reference_title if not p.reference_fits else "",
                    "phrase": p.grounding_phrase,
                    "speaker": ("your words" if p.source_speaker == "user"
                                else "the critic" if p.source_speaker else ""),
                    "near": [f"{n.label} {n.distance:.2f}" for n in p.near],
                    "context": _dts_context(document, p.grounding_phrase),
                    "notes": p.notes,
                    "default": KEEP if p.include_by_default else REJECT,
                    # DEMOTION needs a target, and the nearest thing the store
                    # already has is the only honest candidate. A duplicate
                    # names its own.
                    "demote_to": p.duplicate_of or (p.near[0].uri if p.near else ""),
                    "demote_to_label": (p.duplicate_label
                                        or (p.near[0].label if p.near else "")),
                })
            return HTMLResponse(render_curation_page(
                entity=entity, stage="derivation", items=items, counts=counts,
                action="/dts/curate/derive", error=error),
                status_code=400 if error else 200)

        cached = _dts_cached(dts, entity["guid"], "tag")
        tags = [Tag(**raw) for raw in cached["tags"]]
        if graph is not None:
            from .dts.tag import reassess_tags
            from .dts.thesaurus import read_label_index

            await run_in_threadpool(
                partial(reassess_tags, tags, known_uris=set(read_label_index(graph))))
        items, counts = [], {}
        for t in tags:
            counts[t.status] = counts.get(t.status, 0) + 1
            items.append({
                "key": t.uri, "label": t.label or t.uri, "status": t.status,
                "confidence": t.confidence, "phrase": t.grounding_phrase,
                "context": _dts_context(document, t.grounding_phrase),
                "speaker": ("your words" if t.source_speaker == "user"
                            else "the critic" if t.source_speaker else ""),
                "notes": t.notes,
                "default": KEEP if t.include_by_default else REJECT,
            })
        return HTMLResponse(render_curation_page(
            entity=entity, stage="tagging", items=items, counts=counts,
            action="/dts/curate/tag", error=error),
            status_code=400 if error else 200)

    async def _dts_summary_form(request: Request, entity) -> HTMLResponse:
        from .ux.dts_pages import render_summary_page

        cached = _dts_cached(_dts(request), entity["guid"], "summarize")
        return HTMLResponse(render_summary_page(
            entity=entity, summary=cached["summary"],
            notes=cached.get("notes") or [],
            words=len(str(cached["summary"]).split()),
            action="/dts/curate/summary"))

    def _dts_choices(form, keys) -> dict:
        """What the curator said about each item, defaulting to reject.

        Defaulting to REJECT rather than keep: a radio that did not arrive is
        a decision that was not made, and writing a concept nobody chose is
        the failure that matters. The form always posts all three, so this is
        a guard rather than a path.
        """
        from .ux.dts_pages import REJECT

        return {k: str(form.get(f"choice:{k}") or REJECT) for k in keys}

    @app.post("/dts/curate/derive", response_class=HTMLResponse)
    async def dts_curate_derive(request: Request) -> HTMLResponse:
        from .dts.derive import DerivationResult, Proposal, commit_derivation
        from .dts.grounding import Neighbour
        from .dts.session import current as dts_current
        from .dts.thesaurus import schemes_for
        from .ux.dts_pages import DEMOTE, KEEP

        form = await request.form()
        guid = str(form.get("guid") or "")
        entity, graph = await _dts_entity(request, guid)
        dts = _dts(request)
        cached = _dts_cached(dts, guid, "derive")
        proposals = []
        for raw in cached["proposals"]:
            raw = dict(raw)
            near = [Neighbour(**n) for n in raw.pop("near", [])]
            proposals.append(Proposal(**{**raw, "near": near}))
        res = DerivationResult(entity=cached["entity"], document=cached["document"],
                               model=cached["model"], proposals=proposals,
                               input_tokens=cached.get("input_tokens", 0),
                               output_tokens=cached.get("output_tokens", 0))

        choices = _dts_choices(form, [p.label for p in proposals])
        included = {lbl for lbl, c in choices.items() if c == KEEP}
        demoted = [p for p in proposals if choices.get(p.label) == DEMOTE]

        prefixes = {"the": "http://visualartsdna.org/thesaurus/"}
        dts_cfg = (cfg or {}).get("dts") or {}
        from rdflib import URIRef as _U

        topics = [str(t) for t in graph.objects(
            _U(entity["uri"]), _U("http://visualartsdna.org/thesaurus/topic"))]
        table = schemes_for(topics, dts_cfg, prefixes=prefixes)
        try:
            out = await run_in_threadpool(
                partial(commit_derivation, dts, res, included=included,
                        entity_path=_entity_path(guid),
                        vocab_dir=layout.dir("vocab_ttl"),
                        vocab_name=dts_current(dts).vocab_name,
                        thesaurus=graph, scheme_table=table, prefixes=prefixes,
                        namespace="http://visualartsdna.org/thesaurus"))
        except StageError as exc:
            # The guards are right and a 500 is not how they should speak. Back
            # to the form, which has re-assessed in the meantime, so whatever
            # the guard objected to is now shown as the finding it is.
            return await _dts_curate_form(request, entity, "derivationCurated",
                                          graph=graph, error=str(exc))
        if demoted:
            await run_in_threadpool(_dts_record_demotions, dts, res, demoted,
                                    choices)
        note = (f"{entity['label']}: kept {len(out['kept'])}, "
                f"rejected {len(out['dropped']) - len(demoted)}"
                + (f", {len(demoted)} marked for demotion" if demoted else ""))
        return RedirectResponse(url="/dts?notice=" + quote(note), status_code=303)

    def _dts_record_demotions(dts, result, demoted, choices) -> None:
        """The third answer, written where it will outlive the run.

        `evidence/vocabulary/demotions.ttl` — committed to the QA git and
        excluded from every manifest, so the backlog accumulates with history
        and never reaches the published catalogue. Acting on it is
        `concepts/merge_demote.py`, which is not built; this is the queue that
        will feed it, and the reason it is written now is that the case
        cannot be reconstructed later (Rick, 2026-09-30, of
        `the:SelfStressState` against `the:Prestress`).
        """
        from datetime import datetime, timezone

        from rdflib import BNode, Graph, Literal, Namespace, URIRef
        from rdflib.namespace import RDF, RDFS, XSD

        OPS = Namespace("http://visualartsdna.org/operations/")
        path = "evidence/vocabulary/demotions.ttl"
        g = Graph()
        try:
            g.parse(data=dts.read_text(path), format="turtle")
        except Exception:
            pass
        g.bind("ops", OPS)
        for p in demoted:
            node = BNode()
            g.add((node, RDF.type, OPS.DemotionRequest))
            g.add((node, RDFS.label, Literal(p.label)))
            g.add((node, OPS.entity, URIRef(result.entity)))
            g.add((node, OPS.at, Literal(datetime.now(timezone.utc).isoformat(),
                                         datatype=XSD.dateTime)))
            target = p.duplicate_of or (p.near[0].uri if p.near else "")
            if target:
                g.add((node, OPS.altLabelOf, URIRef(target)))
            if p.definition:
                g.add((node, OPS.definition, Literal(p.definition)))
            g.add((node, RDFS.comment, Literal(
                "proposed during DTS curation; awaiting a vocabulary pass")))
        dts.call("dts.write_evidence",
                 {"path": path, "turtle": g.serialize(format="turtle")})

    @app.post("/dts/curate/tag", response_class=HTMLResponse)
    async def dts_curate_tag(request: Request) -> HTMLResponse:
        from .dts.tag import Tag, TaggingResult, commit_tagging
        from .ux.dts_pages import KEEP

        form = await request.form()
        guid = str(form.get("guid") or "")
        entity, _graph = await _dts_entity(request, guid)
        dts = _dts(request)
        cached = _dts_cached(dts, guid, "tag")
        tags = [Tag(**raw) for raw in cached["tags"]]
        res = TaggingResult(entity=cached["entity"], document=cached["document"],
                            model=cached["model"], tags=tags,
                            input_tokens=cached.get("input_tokens", 0),
                            output_tokens=cached.get("output_tokens", 0))
        choices = _dts_choices(form, [t.uri for t in tags])
        included = {uri for uri, c in choices.items() if c == KEEP}
        if not included:
            return await _dts_curate_form(request, entity, "taggingCurated")
        try:
            out = await run_in_threadpool(
                partial(commit_tagging, dts, res, included=included,
                        entity_path=_entity_path(guid)))
        except StageError as exc:
            return await _dts_curate_form(request, entity, "taggingCurated",
                                          graph=_graph, error=str(exc))
        note = (f"{entity['label']}: placed {len(out['kept'])}, "
                f"rejected {len(out['dropped'])}")
        return RedirectResponse(url="/dts?notice=" + quote(note), status_code=303)

    @app.post("/dts/curate/summary", response_class=HTMLResponse)
    async def dts_curate_summary(request: Request) -> HTMLResponse:
        from .dts.summarize import SummaryResult, commit_summary

        form = await request.form()
        guid = str(form.get("guid") or "")
        entity, _graph = await _dts_entity(request, guid)
        dts = _dts(request)
        cached = _dts_cached(dts, guid, "summarize")
        res = SummaryResult(entity=cached["entity"], document=cached["document"],
                            model=cached["model"], summary=cached["summary"],
                            input_tokens=cached.get("input_tokens", 0),
                            output_tokens=cached.get("output_tokens", 0),
                            notes=cached.get("notes") or [])
        try:
            out = await run_in_threadpool(
                partial(commit_summary, dts, res, entity_path=_entity_path(guid)))
        except StageError as exc:
            return RedirectResponse(
                url="/dts?notice=" + quote(f"{entity['label']}: {exc}"),
                status_code=303)
        note = (f"{entity['label']}: summary accepted "
                f"({out['written']['words']} words). DTS complete.")
        return RedirectResponse(url="/dts?notice=" + quote(note), status_code=303)

    @app.get("/drafts", response_class=HTMLResponse)
    async def drafts_page(request: Request) -> HTMLResponse:
        """Everything written and not distributed, as records."""
        from .ux.forms import render_drafts_page

        idx = _drafts(request)
        if idx is None:
            raise HTTPException(status_code=503,
                                detail="no promotion target configured")
        drafts, orphans = await run_in_threadpool(idx.list)
        return HTMLResponse(render_drafts_page(
            drafts=drafts, orphans=orphans,
            back_for=lambda d: _draft_link(request.app, d),
        ))

    @app.get("/drafts/view", response_class=HTMLResponse)
    async def draft_view(request: Request, guid: str = "") -> HTMLResponse:
        """One draft's triples and its diff against the distributed version."""
        from .ux.forms import render_draft_page

        idx = _drafts(request)
        if idx is None:
            raise HTTPException(status_code=503,
                                detail="no promotion target configured")
        draft = await run_in_threadpool(idx.detail, guid)
        return HTMLResponse(
            render_draft_page(
                draft=draft,
                back=_draft_link(request.app, draft) if draft else "",
            ),
            status_code=200 if draft else 404,
        )

    # -- recording a session as a replayable scenario (Phase 5) ------------
    #
    # Competency is measured by replaying recorded human sessions through the
    # agent driver, never by a model's self-report — so the recordings have to
    # exist before the driver does. Eight acceptance runs and a 2.5-hour
    # production run were lost for want of this.

    @app.get("/api/record")
    async def record_status(request: Request) -> JSONResponse:
        rec = getattr(request.app.state.dash, "recorder", None)
        return JSONResponse(rec.summary() if rec else {"recording": False})

    @app.post("/api/record/start")
    async def record_start(request: Request) -> JSONResponse:
        """Begin. An explicit act, not always-on.

        1622 tool calls in a production day, 23 of them authoring. Slicing an
        episode out of a continuous stream afterwards means guessing where it
        began; saying so costs one click and removes the guess.
        """
        from .scenarios.recorder import Recorder, safe_name

        body = await _json_body(request)
        dash = request.app.state.dash
        if getattr(dash, "recorder", None) is not None:
            raise HTTPException(
                status_code=409,
                detail=f"already recording {dash.recorder.name!r}; stop it first")
        dash.recorder = Recorder(
            name=safe_name(body.get("name") or ""),
            description=str(body.get("description") or ""),
        )
        return JSONResponse(dash.recorder.summary())

    @app.post("/api/record/stop")
    async def record_stop(request: Request) -> JSONResponse:
        """Finish, capture the end state, write the scenario.

        The END STATE is read now rather than accumulated, because that is what
        `assert_end_state` compares against: the SOT's paths, whether QA is
        clean, and the pipeline queue counts. Reading it at stop is also the
        only honest moment — it is the state the session actually produced.
        """
        import json as _json

        from .backup import OPERATIONAL_PREFIX
        from .scenarios.recorder import SCENARIO_DIR

        dash = request.app.state.dash
        rec = getattr(dash, "recorder", None)
        if rec is None:
            raise HTTPException(status_code=409, detail="not recording")

        driver = _driver(request)
        expected: dict = {}
        if driver is not None:
            snap = await run_in_threadpool(driver.transport.snapshot)
            expected["sot"] = {
                k: None for k in snap
                if not k.startswith(OPERATIONAL_PREFIX + "/")
            }
            expected["qa_clean"] = await run_in_threadpool(driver.qa.is_clean)

        scenario = rec.to_scenario(expected)
        rel = f"{SCENARIO_DIR}/{rec.name}.rson"
        await run_in_threadpool(
            partial(_trusted_fileops(sandbox_root, cfg).write_text, rel,
                    _json.dumps(scenario, indent=4) + "\n", make_parents=True))
        dash.recorder = None
        return JSONResponse({
            "written": rel, "steps": len(scenario["steps"]),
            "reads_dropped": scenario["recorded"]["reads_dropped"],
            # Said plainly: this is a session artifact, not a test. Promoting
            # one to `tests/scenarios/` is a decision a person makes, and the
            # dashboard cannot write to the project tree anyway (law 1).
            "note": ("Written into the sandbox. Copy it to tests/scenarios/ to "
                     "make it a committed fixture."),
        })

    @app.post("/drafts/discard", response_class=HTMLResponse)
    async def drafts_discard(request: Request) -> HTMLResponse:
        """Undo everything uncommitted about the chosen records.

        Not the same act as `Discard changes` on a review, and the page says so:
        this goes back to what the SOT last agreed to, that goes back to where
        the session started.
        """
        from .ux.forms import render_drafts_page

        idx = _drafts(request)
        if idx is None:
            raise HTTPException(status_code=503,
                                detail="no promotion target configured")
        form = await request.form()
        drafts, _orphans = await run_in_threadpool(idx.list)
        guids = ([d["guid"] for d in drafts] if form.get("all")
                 else [str(g) for g in form.getlist("guid")])
        result = await run_in_threadpool(idx.discard, guids)
        # A restore point can only describe a tree that still exists.
        if result.get("discarded"):
            _driver(request).episodes.forget()
            for p in _driver(request).pending():
                await run_in_threadpool(_driver(request).reject, p["token"])
        drafts, orphans = await run_in_threadpool(idx.list)
        return HTMLResponse(render_drafts_page(
            drafts=drafts, orphans=orphans, result=result,
            back_for=lambda d: _draft_link(request.app, d),
        ))

    @app.post("/episode/stage", response_class=HTMLResponse)
    async def episode_stage(request: Request) -> HTMLResponse:
        """Keep this record as a draft and carry on — the third answer.

        Approve distributes, Discard destroys, and a batch of related records
        needs neither yet: make them all, review them together, approve once
        (Rick, 2026-09-27). The record is already written; what this changes is
        the SESSION around it.

        The restore point goes, deliberately. An open session and a draft are
        two different things with two different undos — *Discard changes* puts
        the sandbox back to where a session started, *Discard draft* removes a
        record — and saying "leave it staged" is the moment one becomes the
        other. Keeping both would leave a session bar on the next form naming
        the record before last.

        The pending token goes too: the tree it described will change as soon as
        the next record is written, so it could only ever be answered with
        `stale`. Saying so now is more honest than finding out later.
        """
        drv = _driver(request)
        await run_in_threadpool(drv.episodes.forget)
        for pending in drv.pending():
            try:
                await run_in_threadpool(drv.reject, pending["token"])
            except PromotionDriverError:
                pass
        return HTMLResponse(status_code=303, content="",
                            headers={"Location": "/drafts"})

    @app.post("/episode/abandon", response_class=HTMLResponse)
    async def episode_abandon(request: Request) -> HTMLResponse:
        """Leave without saving: the sandbox goes back to where the work started.

        The counterpart to Approve & distribute, and the reason that button is
        the save point rather than a formality. Modified records are restored,
        records the session created are deleted, and binaries follow their
        sidecars back out of the attic (promotion/episode.py).
        """
        from .ux.forms import render_discarded_page

        out = await run_in_threadpool(_driver(request).abandon_episode)
        # Any pending token described a tree that no longer exists. Approving it
        # would fail as `stale` anyway; dropping it makes the outcome plain.
        for p in _driver(request).pending():
            await run_in_threadpool(_driver(request).reject, p["token"])
        return HTMLResponse(render_discarded_page(result=out))

    @app.get("/api/episode")
    def episode_state(request: Request) -> JSONResponse:
        return JSONResponse(_driver(request).open_episode())

    @app.get("/api/wip")
    def wip(request: Request) -> JSONResponse:
        return JSONResponse(_driver(request).work_in_progress())

    @app.post("/api/wip/discard")
    async def wip_discard(request: Request) -> JSONResponse:
        out = await run_in_threadpool(_driver(request).discard_work_in_progress)
        return JSONResponse(out)

    @app.get("/wip/discard", response_class=HTMLResponse)
    async def wip_discard_confirm(request: Request) -> HTMLResponse:
        """Show exactly what would be thrown away, then ask.

        Destructive and unrecoverable — the discarded records were never
        committed, so no git history holds them. It therefore gets the same
        shape as promotion: see the change first, act second.
        """
        from .ux.forms import render_discard_page

        out = await run_in_threadpool(_driver(request).work_in_progress)
        return HTMLResponse(render_discard_page(wip=out))

    @app.post("/wip/discard", response_class=HTMLResponse)
    async def wip_discard_submit(request: Request) -> HTMLResponse:
        from .ux.forms import render_discard_page

        out = await run_in_threadpool(_driver(request).discard_work_in_progress)
        return HTMLResponse(render_discard_page(wip=out, done=True))

    def _rec(request: Request, op: str, args: dict | None = None) -> None:
        """Record a TRUSTED-ORCHESTRATOR act.

        The registry tools record themselves in `Dashboard.dispatch`; these do
        not pass through it, because the promotion tail and the sync are law 1
        machinery and deliberately never tools (law 10). They are recorded here
        because `StepExecutor` replays exactly these op names, so a session
        without them replays the authoring and stops short of distributing it.
        """
        rec = getattr(request.app.state.dash, "recorder", None)
        if rec is not None:
            rec.step(op, args or {})

    def _rec_ingest(request: Request, path: str) -> None:
        """Record an INGEST as the arrival of a file.

        The drop folder is outside the sandbox and `copy_into` is trusted-side,
        not a registry tool (law 12), so an ingest leaves no dispatch to
        record — and a replay without it fails the asset-reference gate on a
        file that never arrived.

        Recorded as an `fs.write` of a STAND-IN, which is the convention the
        committed episodes already use: "content is a stand-in so the episode
        is deterministic". A recording is a shape to re-run, not a copy of the
        artist's photographs — keeping 3 MB of JPEG per step would make the
        corpus unusable and the diffs unreadable.
        """
        rec = getattr(request.app.state.dash, "recorder", None)
        if rec is not None:
            rec.step("fs.write", {"path": path, "text": "INGESTED-STAND-IN",
                                  "make_parents": True})

    async def _do_refresh(request: Request) -> dict:
        """The refresh itself, shared by the API route and the page.

        One implementation, because the two are the same act and a page that
        did a slightly different thing from the endpoint would be the worst kind
        of duplication — the kind nobody compares.
        """
        from .sot_sync.sync import refresh as _refresh
        from .ux.affordance import load_vocabulary_graph as _load_vocab

        # The executor has no single `refresh`; it has the two acts a refresh
        # performs, in this order.
        _rec(request, "sot.sync", {})
        _rec(request, "sot.adopt", {})

        # Refresh discards work in progress and pulls SOT wholesale, so any
        # restore point describes a tree that is about to be gone.
        drv = getattr(request.app.state, "promotion_driver", None)
        if drv is None:
            raise HTTPException(status_code=503,
                                detail="no promotion target configured")
        drv.episodes.forget()
        res = await run_in_threadpool(
            _refresh, drv.qa, drv.transport,
            git_content_extensions=drv.git_content_extensions,
        )
        # Content is only half of "make this server current". The ontology and
        # thesaurus that just arrived have to reach the running process too, or
        # the entry form keeps offering the set it read at startup. Both halves
        # of the type enum move together — the parent registry (what the form
        # OFFERS) and the worker's (what dispatch ENFORCES).
        dash: Dashboard = request.app.state.dash
        live["vocab_graph"] = await run_in_threadpool(
            _load_vocab, _sb / layout.dir("vocab_ttl"), _sb / layout.dir("model_ttl")
        )
        reloaded = await run_in_threadpool(dash.reload)
        return {"status": "OK", "stamp": res.stamp, "drift": res.drift.counts,
                "reloaded": reloaded}

    @app.get("/refresh", response_class=HTMLResponse)
    async def refresh_confirm(request: Request) -> HTMLResponse:
        """Show what a refresh would destroy, then ask.

        The API route had neither a card nor a confirmation, which was tolerable
        while a refresh was rare. With a second instance and the legacy
        dashboard publishing to the same SOT it is routine, and it is the single
        action that silently destroys drafts.
        """
        from .ux.forms import render_refresh_page

        idx = _drafts(request)
        drafts = (await run_in_threadpool(idx.list))[0] if idx is not None else []
        wip = await run_in_threadpool(_driver(request).work_in_progress)
        return HTMLResponse(render_refresh_page(
            drafts=drafts, wip=wip,
            environment=request.app.state.environment.get("label", ""),
        ))

    @app.post("/refresh", response_class=HTMLResponse)
    async def refresh_submit(request: Request) -> HTMLResponse:
        from .ux.forms import render_refresh_page

        result = await _do_refresh(request)
        return HTMLResponse(render_refresh_page(
            drafts=[], wip={}, result=result,
            environment=request.app.state.environment.get("label", ""),
        ))

    @app.api_route("/api/refresh", methods=["GET", "POST"])
    async def server_refresh(request: Request, detail: int = 0) -> JSONResponse:
        """Server refresh — the other half of every workflow's tail.

        **GET, because that is the signal in practice.** The refresh signal comes
        from the existing server today and will be issued by this dashboard
        later, including to itself; matching the established convention matters
        more than HTTP purity here. POST is kept as well, so a caller that
        prefers the correct verb for a mutating call is not forced into GET.

        The trade worth knowing: a mutating GET can be triggered by anything
        that follows links — a browser prefetch, a crawler. The app binds to
        localhost for a single user, so the exposure is small, but that is why
        POST remains available.

        Returns ``{"status": "OK"}``. ``?detail=1`` adds what actually happened,
        since a refresh that silently half-worked is the failure mode.
        """
        drv = _driver(request)
        out = await _do_refresh(request)
        if detail:
            return JSONResponse(out)
        return JSONResponse({"status": out["status"]})

    @app.get("/api/workflow-state")
    async def workflow_state(request: Request) -> JSONResponse:
        # The panel is a thin binding over the workflow.state tool (law 10):
        # panel and agent narration are two renderings of one computation.
        resp = await run_in_threadpool(request.app.state.dash.dispatch, "workflow.state", {})
        return JSONResponse(resp.get("result") if resp["ok"] else {"error": resp.get("error")})

    @app.post("/api/tool/{name}")
    async def run_tool(name: str, request: Request) -> JSONResponse:
        raw = await request.body()
        args: object = {}
        if raw:
            try:
                args = await request.json()
            except Exception:
                return JSONResponse(
                    {"ok": False, "error": {"code": "bad_json", "message": "body must be JSON"}},
                    status_code=400,
                )
        if not isinstance(args, dict):
            return JSONResponse(
                {"ok": False, "error": {"code": "bad_args", "message": "args must be an object"}},
                status_code=400,
            )
        resp = await run_in_threadpool(request.app.state.dash.dispatch, name, args)
        return JSONResponse(
            {"ok": resp["ok"], "result": resp.get("result"), "error": resp.get("error")}
        )

    return app
