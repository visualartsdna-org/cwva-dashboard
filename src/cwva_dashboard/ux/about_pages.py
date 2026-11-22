"""The About pages (/about): the project's documentation, read in the dashboard.

The pages are Markdown files in ``docs/about/``, listed in order by
``contents.rson``. The same files are the documentation on GitHub, so a link
between them is written as GitHub reads it (``key-ideas.md``) and rewritten
here to the page's address. Rendered trusted-side: they are this project's own
files, not content.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .. import rson
from ..tools.doc_tools import render_markdown_body
from .forms import _esc

__all__ = ["AboutDocs", "render_about_page"]

DOCS = Path(__file__).resolve().parents[3] / "docs" / "about"


@dataclass(frozen=True)
class Page:
    slug: str
    file: str
    title: str
    part: str


class AboutDocs:
    def __init__(self, root: Path = DOCS):
        self.root = Path(root)

    def contents(self) -> list[tuple[str, list[Page]]]:
        """``[(part title, [pages])]``, parts with no pages left out."""
        raw = rson.load(str(self.root / "contents.rson")) or {}
        out = []
        for part in raw.get("parts", []):
            pages = [Page(p["slug"], p["file"], p.get("title", p["slug"]), part["title"])
                     for p in part.get("pages", [])
                     if (self.root / p["file"]).is_file()]
            if pages:
                out.append((part["title"], pages))
        return out

    def pages(self) -> list[Page]:
        return [p for _part, ps in self.contents() for p in ps]

    def page(self, slug: str) -> Page | None:
        return next((p for p in self.pages() if p.slug == slug), None)

    def html(self, page: Page) -> str:
        by_file = {p.file: p.slug for p in self.pages()}
        body = render_markdown_body((self.root / page.file).read_text(encoding="utf-8"))

        def relink(m):
            target, frag = m.group(2), m.group(3) or ""
            if target in by_file:
                return f'{m.group(1)}"/about/{by_file[target]}{frag}"'
            if target == "README.md":
                return f'{m.group(1)}"/about{frag}"'
            if target == "../ASSISTANT_GUIDE.md":
                return f'{m.group(1)}"/about/assistant-guide.md"'
            return m.group(0)

        body = re.sub(r'(href=)"((?:\.\./)?[\w.-]+\.md)(#[\w-]*)?"', relink, body)
        # GitHub gives every heading an anchor; mistune does not, and a link
        # to a section has to work in both places.
        return re.sub(r"<(h[1-4])>(.*?)</\1>",
                      lambda m: f'<{m.group(1)} id="{_anchor(m.group(2))}">{m.group(2)}</{m.group(1)}>',
                      body)


def _anchor(heading_html: str) -> str:
    """GitHub's heading anchor: lower case, punctuation dropped, spaces to -."""
    text = re.sub(r"<[^>]+>", "", heading_html)
    text = re.sub(r"&[a-z]+;|&#\d+;", "", text).strip().lower()
    return re.sub(r"\s", "-", re.sub(r"[^\w\s-]", "", text))


_CSS = """
.about{display:flex;gap:2.5rem;max-width:1200px;margin:2rem auto;padding:0 2rem}
.about nav.toc{flex:0 0 15rem;position:sticky;top:6rem;align-self:flex-start;
font-size:.9rem}
.toc h3{font-size:.72rem;text-transform:uppercase;letter-spacing:.08em;
color:var(--text-muted);margin:1.2rem 0 .4rem}
.toc a{display:block;padding:.25rem .6rem;border-radius:6px;color:var(--text-secondary);
text-decoration:none}
.toc a:hover{background:var(--bg-card);color:var(--text-primary)}
.toc a.on{background:var(--bg-card);color:var(--text-primary);
border-left:2px solid var(--accent-blue)}
.toc .soon{padding:.25rem .6rem;color:var(--text-muted);font-style:italic}
article{flex:1;min-width:0;max-width:46rem;line-height:1.7;color:var(--text-primary)}
article h1{font-size:1.8rem;margin:0 0 1rem;font-weight:600}
article h2{font-size:1.25rem;margin:2rem 0 .6rem;font-weight:600}
article h3{font-size:1.05rem;margin:1.5rem 0 .5rem}
article p,article li{color:var(--text-secondary)}
article strong{color:var(--text-primary)}
article a{color:var(--accent-blue)}
article code{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:.85em;
background:var(--bg-card);padding:.1rem .35rem;border-radius:4px}
article pre{background:var(--bg-card);padding:1rem;border-radius:8px;overflow-x:auto}
article ul{padding-left:1.4rem}
body{margin:0}
@media (max-width:900px){.about{flex-direction:column}.about nav.toc{position:static}}
"""


def render_about_page(docs: AboutDocs, page: Page | None, chrome: tuple,
                      upcoming=()) -> str:
    links, hub_css, header = chrome
    toc = []
    for part, pages in docs.contents():
        toc.append(f"<h3>{_esc(part)}</h3>")
        for p in pages:
            on = " on" if page and p.slug == page.slug else ""
            toc.append(f'<a class="{on.strip()}" href="/about/{p.slug}">{_esc(p.title)}</a>')
    for part in upcoming:
        toc.append(f'<h3>{_esc(part)}</h3><div class="soon">to come</div>')
    body = docs.html(page) if page else "<h1>Not found</h1><p>No such page.</p>"
    title = page.title if page else "Not found"
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>About &mdash; {_esc(title)}</title>{links}
<style>{hub_css}
body{{font-family:'Outfit',sans-serif;background:var(--bg-primary);color:var(--text-primary)}}
{_CSS}</style></head>
<body>
{header}
<div class="about"><nav class="toc">{"".join(toc)}</nav>
<article>{body}</article></div>
</body></html>"""
