"""Printable reports (the hub's Tools tab). Light pages, because they are
read on paper as often as on screen."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from .forms import _esc

__all__ = ["render_storage_report", "render_registry_page", "render_certificate"]

from urllib.parse import quote as _quote

_CSS = """
body{font:14px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:#111;
margin:1.5rem auto;max-width:56rem;padding:0 1rem}
h1{font-size:1.3rem;margin:0}
.meta{color:#555;margin:.2rem 0 1rem}
.bar{display:flex;gap:1rem;align-items:center;margin-bottom:1rem}
.bar a,.bar button{font:inherit;color:#1a5fb4}
.bar button{background:none;border:1px solid #bbb;border-radius:6px;padding:.2rem .6rem;cursor:pointer}
table{border-collapse:collapse;width:100%}
th,td{border-bottom:1px solid #ddd;padding:.3rem .5rem;text-align:left;vertical-align:middle}
th{border-bottom:2px solid #999}
td.di{font-family:ui-monospace,monospace;white-space:nowrap}
td.img{width:58px}
.err{color:#b00}
@media print{.bar{display:none} body{margin:0;max-width:none}}
"""


def render_storage_report(result: Mapping[str, Any] | None, *, error: str = "",
                          instance: str = "", now: datetime | None = None) -> str:
    now = now or datetime.now()
    cls = (result or {}).get("storage_class", "")
    which = f"storage class “{cls}”" if cls else "default storage"
    rows = (result or {}).get("rows") or []
    body = ""
    if error:
        body = f'<p class="err">{_esc(error)}</p>'
    elif not rows:
        body = f"<p>No provenance records in {_esc(which)}.</p>"
    else:
        trs = []
        for r in rows:
            img = ""
            if r["thumbnail"]:
                img = (f'<img src="{_esc(r["thumbnail"])}" width="50" alt="" loading="lazy" '
                       f'onerror="this.onerror=null;this.src=\'{_esc(r["image"])}\'">')
            trs.append(f'<tr><td class="di">{_esc(r["di"])}</td>'
                       f'<td>{_esc(r["title"]) or "<em>untitled</em>"}</td>'
                       f'<td class="img">{img}</td></tr>')
        body = ("<table><thead><tr><th>DispId</th><th>Title</th><th>Image</th></tr></thead>"
                f"<tbody>{''.join(trs)}</tbody></table>")
    src = f" &middot; {_esc(instance)} sandbox, drafts included" if instance else ""
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Storage report &mdash; {_esc(which)}</title>
<style>{_CSS}</style></head><body>
<div class="bar"><a href="/#tools">&larr; Tools</a>
<button onclick="window.print()">Print</button></div>
<h1>Storage report: {_esc(which)}</h1>
<p class="meta">{len(rows)} work{'s' if len(rows) != 1 else ''}, in DispId order
&middot; {now:%Y-%m-%d %H:%M}{src}</p>
{body}
</body></html>"""


def _img(thumb: str, full: str, alt: str = "") -> str:
    if not thumb:
        return ""
    fallback = (f' onerror="this.onerror=null;this.src=\'{_esc(full)}\'"'
                if full and full != thumb else "")
    return (f'<a href="{_esc(full or thumb)}"><img src="{_esc(thumb)}" width="50" '
            f'alt="{_esc(alt)}" loading="lazy"{fallback}></a>')


def render_registry_page(result: Mapping[str, Any] | None, *, error: str = "",
                         instance: str = "", now: datetime | None = None) -> str:
    """The register of one profile's works; with no profile chosen, the list
    of profiles to choose from (inventory #19)."""
    now = now or datetime.now()
    src = f" &middot; {_esc(instance)} sandbox, drafts included" if instance else ""
    result = result or {}
    if error:
        title, body = "Register", f'<p class="err">{_esc(error)}</p>'
    elif "profiles" in result:
        title = "Register"
        items = "".join(
            f'<li><a href="/report/registry?profile={_quote(p["profile"], safe="")}">'
            f'{_esc(p["label"])}</a> &mdash; {_esc(p["artist"]) or "no artist"}, '
            f'{p["count"]} work{"s" if p["count"] != 1 else ""}</li>'
            for p in result["profiles"])
        body = (f'<p class="meta">Choose an artist profile.{src}</p>'
                f'<ul>{items or "<li>No artist profiles.</li>"}</ul>')
    else:
        title = f"Register &mdash; {_esc(result['label'])}"
        rows = "".join(
            f'<tr><td>{_esc(r["title"]) or "<em>untitled</em>"}</td>'
            f'<td class="img">{_img(r["thumbnail"], r["image"], r["title"])}</td>'
            f'<td class="img">{_img(r["qrcode"], r["qrcode"], "QR code")}</td>'
            f'<td>{_esc(r["year"])}</td><td>{_esc(r["description"])}</td></tr>'
            for r in result["rows"])
        by = f"by {_esc(result['artist'])}" if result.get("artist") else ""
        body = (f'<p class="meta">{by} &middot; {result["count"]} works, by title '
                f'&middot; {now:%Y-%m-%d %H:%M}{src}</p>'
                "<table><thead><tr><th>Title</th><th>Image</th><th>QR code</th>"
                f"<th>Year</th><th>Description</th></tr></thead><tbody>{rows}</tbody></table>")
    back = ('<a href="/report/registry">&larr; Profiles</a>' if "rows" in result
            else '<a href="/#tools">&larr; Tools</a>')
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>{_CSS}</style></head><body>
<div class="bar">{back}<button onclick="window.print()">Print</button></div>
<h1>{title}</h1>
{body}
</body></html>"""


_CERT_CSS = """
body{font:17px/1.5 Georgia,'Times New Roman',serif;color:#111;max-width:46rem;
margin:2rem auto;padding:0 1.5rem}
h1{text-align:center;font-weight:normal;letter-spacing:.06em;font-size:1.6rem;margin:0}
h2{text-align:center;font-weight:normal;font-size:1.25rem;margin:.4rem 0 1.5rem}
h2 a{color:inherit;text-decoration:none}
table{border-collapse:collapse;width:100%;font-size:.95rem}
td{padding:.3rem .5rem;vertical-align:top;border-bottom:1px solid #e3e3e3}
td.p{font-style:italic;color:#444;width:13rem}
tr:nth-child(even){background:#f8f8f8}
td a{color:#1a4f8a;text-decoration:none}
.sign{margin-top:3rem;line-height:3}
.bar{font:14px system-ui,sans-serif;display:flex;gap:1rem;margin-bottom:1.5rem}
.bar a,.bar button{color:#1a5fb4;font:inherit}
.bar button{background:none;border:1px solid #bbb;border-radius:6px;padding:.2rem .6rem;cursor:pointer}
.err{color:#b00}
@media print{.bar{display:none} body{margin:0 auto}}
"""


def render_certificate(result: Mapping[str, Any] | None, *, error: str = "") -> str:
    """Certificate of Authenticity (#20), laid out as the Groovy did: the
    title, the record as Property / Value, then lines to sign and date."""
    if error or not result:
        body = f'<p class="err">{_esc(error or "no such work")}</p>'
        title = "Certificate of Authenticity"
    else:
        title = f"Certificate of Authenticity &mdash; {_esc(result['title'])}"
        trs = []
        for r in result["rows"]:
            cells = []
            for v in r["values"]:
                if v.get("image"):
                    cells.append(f'<a href="{_esc(v["href"])}"><img src="{_esc(v["image"])}" '
                                 f'width="{int(v["width"])}" alt=""></a>')
                elif v.get("href"):
                    cells.append(f'<a href="{_esc(v["href"])}">{_esc(v["text"])}</a>')
                else:
                    cells.append(_esc(v["text"]))
            trs.append(f'<tr><td class="p">{_esc(r["property"])}</td>'
                       f'<td>{", ".join(cells)}</td></tr>')
        body = (f'<h2><a href="{_esc(result["work"])}">{_esc(result["title"])}</a></h2>'
                f'<table><tbody>{"".join(trs)}</tbody></table>'
                '<div class="sign">Signed: _________________________________<br>'
                'Date: _______________________</div>')
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>{_CERT_CSS}</style></head><body>
<div class="bar"><a href="/#tools">&larr; Tools</a>
<button onclick="window.print()">Print</button></div>
<h1>Certificate of Authenticity</h1>
{body}
</body></html>"""
