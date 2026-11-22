"""The filesystem tool set — the agent's file vocabulary over :class:`FileOps`.

Each tool is a thin, JSON-safe wrapper: it takes primitive arguments and
returns a plain dict (bytes surface as text or base64, never raw), so results
travel cleanly over the worker IPC and, later, over MCP. Confinement, quotas,
and soft-delete all live in FileOps beneath these — the tools add no policy.
"""

from __future__ import annotations

import base64

from .base import Tool
from .registry import ToolRegistry

__all__ = ["build_default_registry", "FILEOPS_TOOLS"]


def _list(fileops, path="."):
    entries = [
        {
            "name": e.name,
            "path": e.path,
            "is_dir": e.is_dir,
            "is_file": e.is_file,
            "is_symlink": e.is_symlink,
            "size": e.size,
        }
        for e in fileops.list_dir(path)
    ]
    return {"entries": entries}


def _read(fileops, path, binary=False, encoding="utf-8"):
    data = fileops.read_bytes(path)
    if binary:
        return {"base64": base64.b64encode(data).decode("ascii"), "bytes": len(data)}
    return {"text": data.decode(encoding), "bytes": len(data)}


def _write(fileops, path, text, make_parents=False):
    r = fileops.write_text(path, text, make_parents=make_parents)
    return {"path": r.path, "bytes_written": r.bytes_written, "created": r.created}


def _mkdir(fileops, path, parents=False, exist_ok=False):
    return {"path": fileops.mkdir(path, parents=parents, exist_ok=exist_ok)}


def _move(fileops, src, dst, overwrite=False):
    return {"path": fileops.move(src, dst, overwrite=overwrite)}


def _copy(fileops, src, dst, overwrite=False):
    return {"path": fileops.copy(src, dst, overwrite=overwrite)}


def _trash(fileops, path):
    return {"path": fileops.trash(path)}


def _str(desc, **extra):
    return {"type": "string", "description": desc, **extra}


def _bool(desc, default=False):
    return {"type": "boolean", "description": desc, "default": default}


FILEOPS_TOOLS: list[Tool] = [
    Tool(
        name="fs.list",
        description="List a directory inside the sandbox.",
        input_schema={
            "type": "object",
            "properties": {"path": _str("Sandbox-relative directory; '.' for root.", default=".")},
            "required": [],
            "additionalProperties": False,
        },
        handler=_list,
    ),
    Tool(
        name="fs.read",
        description="Read a file. Returns text by default, or base64 when binary=true.",
        input_schema={
            "type": "object",
            "properties": {
                "path": _str("Sandbox-relative file path."),
                "binary": _bool("Return base64 instead of decoded text.", default=False),
                "encoding": _str("Text encoding when binary is false.", default="utf-8"),
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        handler=_read,
    ),
    Tool(
        name="fs.write",
        description="Write (create or overwrite) a text file inside the sandbox.",
        input_schema={
            "type": "object",
            "properties": {
                "path": _str("Sandbox-relative file path."),
                "text": _str("File contents."),
                "make_parents": _bool("Create missing parent directories.", default=False),
            },
            "required": ["path", "text"],
            "additionalProperties": False,
        },
        handler=_write,
        redact=frozenset({"text"}),
    ),
    Tool(
        name="fs.mkdir",
        description="Create a directory inside the sandbox.",
        input_schema={
            "type": "object",
            "properties": {
                "path": _str("Sandbox-relative directory path."),
                "parents": _bool("Create intermediate directories.", default=False),
                "exist_ok": _bool("Do not error if it already exists.", default=False),
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        handler=_mkdir,
    ),
    Tool(
        name="fs.move",
        description="Move/rename a file or directory within the sandbox.",
        input_schema={
            "type": "object",
            "properties": {
                "src": _str("Source sandbox-relative path."),
                "dst": _str("Destination sandbox-relative path."),
                "overwrite": _bool("Replace an existing destination.", default=False),
            },
            "required": ["src", "dst"],
            "additionalProperties": False,
        },
        handler=_move,
    ),
    Tool(
        name="fs.copy",
        description="Copy a file or directory within the sandbox.",
        input_schema={
            "type": "object",
            "properties": {
                "src": _str("Source sandbox-relative path."),
                "dst": _str("Destination sandbox-relative path."),
                "overwrite": _bool("Replace an existing destination.", default=False),
            },
            "required": ["src", "dst"],
            "additionalProperties": False,
        },
        handler=_copy,
    ),
    Tool(
        name="fs.trash",
        description="Soft-delete a path into the in-sandbox trash (recoverable).",
        input_schema={
            "type": "object",
            "properties": {"path": _str("Sandbox-relative path to trash.")},
            "required": ["path"],
            "additionalProperties": False,
        },
        handler=_trash,
    ),
]


def build_default_registry(
    standing_queries=None, domain: str = "", sites=None, *, model=None,
    entry_forms=None, layout=None, artist_profile=None, profiles=None,
    artists=None, workflows=None,
) -> ToolRegistry:
    """The default tool vocabulary: filesystem ops, the ported utility functions
    (RDF, image, doc, record), the workflow-state tools, and updateWorkOnSite.
    Newly registered tools surface in the UX with no UX code change (law 10).
    ``standing_queries`` / ``domain`` / ``sites`` are loaded as data in the
    orchestrator (§7.1, §13, §7.2). ``model`` (ontology graph) + ``entry_forms``
    (per-form type_root config) resolve `type` to an ontology-backed enum; absent,
    `type` falls back to an unenforced suggested set.

    ``layout`` is the active target's placement map (B1, CE_DESIGN §3.6). One
    Layout is threaded into every builder that names a mirror path, so readers
    and writers cannot disagree about where content lives — the QA tree adopts
    its target's layout, and a tool defaulting to the module constant would write
    beside the synced content instead of into it."""
    from ..workflow_state.definitions import DEFAULT_STANDING_QUERIES
    from ..workflows.annotate import build_annotate_tools
    from ..workflows.update_work_on_site import build_scrape_tools
    from .dts_tools import build_dts_tools
    from .edit_tools import build_edit_tools
    from .doc_tools import DOC_TOOLS
    from .image_tools import build_image_tools
    from .provenance_tools import build_provenance_tools
    from .rdf_tools import RDF_TOOLS, build_store_query_tool
    from .record_tools import build_record_tools
    from .bootstrap_tools import build_bootstrap_tools
    from .check_tools import CHECK_TOOLS
    from .report_tools import build_report_tools
    from .record_tools import work_namespace
    from .profile_tools import build_profile_tools
    from .workflow_tools import build_board_tools, build_workflow_tools

    if not domain:
        # No default. The domain is the sovereign `work:` namespace (CE_DESIGN
        # §13.2), and a fallback here was one deployment's identity reachable by
        # omission — every record minted under it would carry the wrong
        # namespace, which is not correctable later without a rebase (§13.6).
        raise ValueError(
            "build_default_registry requires `domain` — the deployer's "
            "canonical domain, from config (CE_DESIGN §13.4a)."
        )
    reg = ToolRegistry()
    tools = (
        *FILEOPS_TOOLS, *RDF_TOOLS, *CHECK_TOOLS, *build_report_tools(layout=layout, work_ns=str(work_namespace(domain))), build_store_query_tool(domain, layout=layout), *build_image_tools(domain, layout=layout, sites=sites,
                          brands=[p.brand for p in (profiles or []) if p.brand]), *DOC_TOOLS,
        *build_record_tools(domain, model=model, entry_forms=entry_forms,
                            layout=layout, artist_profile=artist_profile),
        *build_workflow_tools(standing_queries or DEFAULT_STANDING_QUERIES, layout=layout),
        *build_board_tools(workflows, layout=layout),
        *build_scrape_tools(sites or [], domain, layout=layout),
        # Both pickers ask the MODEL which types are works, so both need it.
        *build_annotate_tools(domain, layout=layout, model=model),
        *build_edit_tools(layout=layout, model=model, domain=domain),
        *build_provenance_tools(domain, layout=layout, model=model),
        # DTS writers. The stages think trusted-side (the provider call,
        # the drop folder) and write here, so confinement, audit and the
        # path chokepoint apply to everything that lands in the tree.
        *build_dts_tools(layout=layout, domain=domain),
        # One record tool per artist profile, generated from its
        # template (CE_DESIGN §14). Absent `profiles`, none — the
        # three hand-written forms are still there.
        *build_profile_tools(profiles or [], domain, model=model, layout=layout),
        # The two hand-written bootstrap forms — an artist, and a profile for
        # one of the things they make. Generation cannot help here: a new
        # deployment's first act is making the profile everything else is
        # generated from.
        *build_bootstrap_tools(domain, model=model, layout=layout, artists=artists or []),
    )
    for tool in tools:
        reg.register(tool)
    return reg
