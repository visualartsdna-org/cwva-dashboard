"""Document utility tools (Phase 4.5 port of inventory #29).

``doc.md_to_html`` renders a sandbox markdown file to HTML via mistune. Pure
read; returns the HTML rather than writing it, leaving placement to the caller.

``doc.set_id`` stamps a markdown file with the CURIE of the record that
references it. Concept derivation and tagging read that line to find the entity
a document belongs to, and it has been a manual step until now — 5 of the 70
markdown files in the store carry it.
"""

from __future__ import annotations

import re

import mistune

from .base import Tool, ToolError

__all__ = ["DOC_TOOLS", "ID_LINE"]

_render = mistune.create_markdown()

# `[id=work:abc123]` alone on its line. Anchored at both ends because the
# convention is exactly that: no other characters on the line.
ID_LINE = re.compile(r"^\[id=([^\]]*)\]\s*$")


def _md_to_html(fileops, path):
    text = fileops.read_text(path)
    return {"html": _render(text)}


# A standalone page for a converted document (the hub's Markdown to HTML,
# 2026-11-19): readable as saved, with nothing fetched from anywhere.
_PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
body{{max-width:46rem;margin:2rem auto;padding:0 1.25rem;
font:16px/1.6 Georgia,'Times New Roman',serif;color:#222}}
h1,h2,h3{{line-height:1.25}} pre,code{{font-family:ui-monospace,monospace;font-size:.9em}}
pre{{background:#f5f5f5;padding:.75rem;overflow-x:auto}} img{{max-width:100%}}
table{{border-collapse:collapse}} td,th{{border:1px solid #ccc;padding:.25rem .5rem}}
blockquote{{border-left:3px solid #ccc;margin-left:0;padding-left:1rem;color:#555}}
</style></head>
<body>
{body}
</body></html>
"""

_MAX_MD_CHARS = 10_000_000


def render_markdown_body(text: str) -> str:
    """Markdown to an HTML fragment (no page around it)."""
    return _render(text)


def render_markdown_page(text: str, title: str = "") -> str:
    """A whole HTML document from markdown text. The title is the given one,
    else the first heading, else "Document"."""
    if len(text) > _MAX_MD_CHARS:
        raise ToolError("too_large", f"more than {_MAX_MD_CHARS:,} characters")
    if not title:
        m = re.search(r"^#{1,6}\s+(.+?)\s*#*\s*$", text, re.M)
        title = m.group(1) if m else "Document"
    safe = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return _PAGE.format(title=safe, body=_render(text))


def _render_markdown(fileops, text, title=""):
    return {"html": render_markdown_page(str(text), str(title))}


def _set_id(fileops, path, curie):
    """Write ``[id=<curie>]`` as the document's id line.

    **Line 2 by convention**, which the real documents follow without exception:
    line 1 is the ``# Title`` and the id sits directly beneath it. An existing
    id line is REPLACED WHERE IT IS rather than moved — if a document keeps it
    somewhere else, that is the author's arrangement and rewriting the file's
    shape is not this tool's business.

    Idempotent, because entry can be re-run: stamping a document that already
    carries the same id changes nothing and reports ``changed: false``. Without
    that, a second submission would append a second id line and the derivation
    step would have two answers to choose between.
    """
    if not str(curie).strip():
        raise ToolError("bad_args", "curie must not be empty")
    line = f"[id={curie}]"

    text = fileops.read_text(path)
    # keepends=False; the trailing-newline state is restored on write.
    lines = text.splitlines()
    had_trailing_newline = text.endswith("\n") or not text

    existing = next((i for i, ln in enumerate(lines) if ID_LINE.match(ln)), None)
    if existing is not None:
        if lines[existing] == line:
            return {"path": path, "changed": False, "line": existing + 1, "id": curie}
        lines[existing] = line
        at = existing
    else:
        # Line 2 for a document that has a first line; line 1 for an empty file.
        at = 1 if lines else 0
        lines.insert(at, line)

    out = "\n".join(lines) + ("\n" if had_trailing_newline else "")
    res = fileops.write_text(path, out)
    return {"path": res.path, "changed": True, "line": at + 1, "id": curie}


DOC_TOOLS: list[Tool] = [
    Tool(
        name="doc.render_markdown",
        description=("Render markdown TEXT (not a sandbox file) to a whole, "
                     "standalone HTML document. Writes nothing."),
        input_schema={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The markdown."},
                "title": {"type": "string", "default": "",
                          "description": "Page title; default the first heading."},
            },
            "required": ["text"],
            "additionalProperties": False,
        },
        handler=_render_markdown,
        redact=frozenset({"text"}),
    ),
    Tool(
        name="doc.md_to_html",
        description="Render a markdown file to HTML.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Sandbox-relative .md file."}
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        handler=_md_to_html,
    ),
    Tool(
        name="doc.set_id",
        description=(
            "Stamp a markdown document with the CURIE of the record that "
            "references it, as `[id=work:<guid>]` on its own line (line 2 by "
            "convention). Idempotent; replaces an existing id line in place."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Sandbox-relative .md file."},
                "curie": {
                    "type": "string",
                    "description": "The record CURIE, e.g. work:abc123.",
                },
            },
            "required": ["path", "curie"],
            "additionalProperties": False,
        },
        handler=_set_id,
    ),
]
