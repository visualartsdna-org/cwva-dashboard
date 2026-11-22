"""Assemble docs/ASSISTANT_GUIDE.md: one file to hand an AI assistant.

The preface (docs/assistant/preface.md) is written for the assistant: who it is
helping, the ground rules, the decisions that are the person's, how to check
each step. The rest is every About page, in the order docs/about/contents.rson
gives, with each page's headings moved down one level and links between pages
turned into links within the guide. So the guide cannot drift from the docs:
it IS the docs, and `tests/test_assistant_guide.py` fails if this file is out
of date.

    python scripts/build_assistant_guide.py           # write it
    python scripts/build_assistant_guide.py --check   # exit 1 if out of date

Acts on no deployment: it reads only this repository's docs.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cwva_dashboard import rson  # noqa: E402

DOCS = ROOT / "docs"
OUT = DOCS / "ASSISTANT_GUIDE.md"


def _anchor(title: str) -> str:
    text = re.sub(r"[^\w\s-]", "", title.strip().lower())
    return re.sub(r"\s", "-", text)


def build() -> str:
    contents = rson.load(str(DOCS / "about" / "contents.rson")) or {}
    pages = [(part["title"], p) for part in contents.get("parts", [])
             for p in part.get("pages", []) if (DOCS / "about" / p["file"]).is_file()]
    # a link to a page becomes a link to that page's heading in the guide
    page_anchor = {}
    for _part, p in pages:
        first = (DOCS / "about" / p["file"]).read_text(encoding="utf-8").splitlines()[0]
        page_anchor[p["file"]] = _anchor(first.lstrip("# "))

    def relink(m):
        text, target, frag = m.group(1), m.group(2), m.group(3) or ""
        if target in page_anchor:
            return f"[{text}](#{frag[1:] if frag else page_anchor[target]})"
        if target in ("../ASSISTANT_GUIDE.md", "README.md"):
            return text
        return m.group(0)

    out = [(DOCS / "assistant" / "preface.md").read_text(encoding="utf-8").rstrip(), ""]
    part_now = None
    for part, p in pages:
        if part != part_now:
            out += [f"# {part}", ""]
            part_now = part
        body = (DOCS / "about" / p["file"]).read_text(encoding="utf-8")
        lines = []
        fence = False
        for line in body.splitlines():
            if line.startswith("```"):
                fence = not fence
            if not fence and re.match(r"#{1,5} ", line):
                line = "#" + line  # one level down, under its part
            if not fence and line.startswith("Next"):
                continue  # page-to-page navigation means nothing in one file
            lines.append(line)
        text = "\n".join(lines).strip()
        text = re.sub(r"\[([^\]]+)\]\(([\w./-]+\.md)(#[\w-]+)?\)", relink, text)
        out += [text, ""]
    return "\n".join(out).rstrip() + "\n"


def main(argv: list[str]) -> int:
    text = build()
    if "--check" in argv:
        if not OUT.is_file() or OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT} is out of date: run python scripts/build_assistant_guide.py")
            return 1
        print(f"{OUT} is up to date")
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT} ({len(text.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
