"""Result pages for the hub's Files-tab utilities."""

from __future__ import annotations

from typing import Any, Mapping

from ..tools.check_tools import KIND_NAMES
from .forms import _STYLE, _esc

__all__ = ["render_check_page"]

_CSS = """
.verdict{font-size:1.05rem;font-weight:600;margin:0 0 .6rem}
.verdict.ok{color:var(--ok)}.verdict.bad{color:var(--bad)}
.facts{color:var(--muted);font-size:.9rem}
pre.ctx{background:#0d121c;border:1px solid var(--line);border-radius:8px;
padding:.6rem;font-size:.85rem;overflow-x:auto;margin:.6rem 0 0}
pre.ctx .here{background:rgba(255,107,107,.15);color:var(--ink)}
pre.ctx .n{color:var(--muted);display:inline-block;min-width:3.5rem;user-select:none}
"""

_NAMES = {**KIND_NAMES, "markdown": "Markdown", "image": "image"}


def render_check_page(filename: str, kind: str, result: Mapping[str, Any] | None,
                      error: str = "", heading: str = "Syntax check") -> str:
    name = _NAMES.get(kind, kind)
    if error:
        body = f'<p class="verdict bad">{_esc(error)}</p>'
    elif result and result.get("ok"):
        if kind != "json":
            facts = (f'{result["triples"]:,} triples about {result["subjects"]:,} '
                     f'named subject{"s" if result["subjects"] != 1 else ""}, '
                     f'{result["lines"]:,} lines')
            if result.get("graphs") is not None:
                facts += f' in {result["graphs"]:,} named graph{"s" if result["graphs"] != 1 else ""}'
            if result.get("prefixes"):
                facts += " &middot; prefixes " + _esc(", ".join(result["prefixes"]))
        else:
            size = result.get("size")
            what = {"dict": "an object", "list": "an array"}.get(result["top"],
                                                               f'a {result["top"]}')
            facts = (f"{what}" + (f" of {size:,} item{'s' if size != 1 else ''}"
                                  if size is not None else "")
                     + f', {result["lines"]:,} lines')
        body = (f'<p class="verdict ok">&#10003; Well-formed {_esc(name)}</p>'
                f'<p class="facts">{facts}</p>')
    else:
        err = (result or {}).get("error") or {}
        where = ""
        if err.get("line"):
            where = f' at line {err["line"]}' + (
                f', column {err["column"]}' if err.get("column") else "")
        ctx = "".join(
            f'<span class="{"here" if c["here"] else ""}"><span class="n">{c["n"]}</span>'
            f'{_esc(c["text"])}</span>\n' for c in err.get("context") or [])
        body = (f'<p class="verdict bad">&#10007; Not well-formed {_esc(name)}{where}</p>'
                f'<p>{_esc(err.get("message", ""))}</p>'
                + (f'<pre class="ctx">{ctx}</pre>' if ctx else ""))
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{_esc(heading)} &mdash; {_esc(filename)}</title>
<style>{_STYLE}{_CSS}</style></head>
<body>
<header><h1>{_esc(heading)}</h1><span class="sub">{_esc(filename)} &middot; {_esc(name)}
&middot; nothing was stored</span>
<span style="margin-left:auto"><a href="/#files">&larr; Files</a></span></header>
<main><section class="card">{body}</section></main></body></html>"""
