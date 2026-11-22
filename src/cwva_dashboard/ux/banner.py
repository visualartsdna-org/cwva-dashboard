"""Which dashboard am I looking at — on every page, without exception.

Two instances run side by side (Rick, 2026-09-26): QA against the shadow SOT on
:8100, and PRODUCTION against the real one on :8102. They render the same pages
from the same code against the same `work:` namespace, so **nothing in a window
says which SOT an Approve will write to** — and one of the two cannot be undone.

**Both are labelled, not only the dangerous one.** If only production carried a
banner, its absence would have to mean "this is QA", and absence is exactly what
a rendering fault produces: the two cases would be indistinguishable at the
moment it matters most. With both labelled, a window with no banner is a window
to stop and look at.

**Injected as middleware rather than rendered by each page**, which is a
deliberate trade. The pages are rendered by a dozen functions plus a handful of
ad-hoc `HTMLResponse` strings, and a banner threaded through all of them would
be missing from whichever one is written next — quietly, and only on the
instance nobody tests. One interception point cannot miss a page, and "no
banner means something is wrong" stays true.

The markup carries its own styles: it sits above both the hub's stylesheet and
the forms' `_STYLE`, and it must not depend on either.
"""

from __future__ import annotations

import re

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

__all__ = ["EnvironmentBanner", "banner_html", "COLOURS", "NO_BANNER"]

#: A response carrying this header is a DOCUMENT, not a page of the dashboard —
#: a report to print, a converted markdown file — and gets no banner (Rick,
#: 2026-11-19). The header is removed on the way out.
NO_BANNER = "X-Cwva-No-Banner"

_BODY = re.compile(r"<body\b[^>]*>", re.IGNORECASE)

# Named colours resolve to the palette both stylesheets already use; anything
# else is passed through as CSS, so a deployment can say "#b45309" and be
# obeyed rather than silently ignored.
COLOURS = {
    "amber": "#ffb454",
    "green": "#3ecf8e",
    "red": "#ff6b6b",
    "blue": "#4da3ff",
}


def banner_html(label: str, colour: str = "") -> str:
    tone = COLOURS.get(colour.lower(), colour or COLOURS["blue"])
    safe = (label.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    return (
        '<div data-env-banner="1" style="position:sticky;top:0;z-index:9999;'
        f"background:#11161f;border-bottom:2px solid {tone};color:{tone};"
        "font:600 13px/1.1 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;"
        'letter-spacing:.2em;padding:.5rem 1rem;text-align:center">'
        f"{safe}</div>"
    )


class EnvironmentBanner(BaseHTTPMiddleware):
    """Put the banner at the top of every HTML response this app sends."""

    def __init__(self, app, *, label: str, colour: str = ""):
        super().__init__(app)
        self.html = banner_html(label, colour)

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if "text/html" not in response.headers.get("content-type", ""):
            return response
        # A download is the user's document, not a page of this dashboard:
        # the banner would end up inside the saved file. A response marked as
        # a document is the same case without the download.
        if "attachment" in response.headers.get("content-disposition", "").lower():
            return response
        if NO_BANNER in response.headers:
            del response.headers[NO_BANNER]
            return response

        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        text = body.decode("utf-8", errors="replace")
        if 'data-env-banner="1"' not in text:
            # After the <body> tag, attributes and all: a banner put ahead of
            # the doctype would drop the page into quirks mode.
            m = _BODY.search(text)
            text = (text[:m.end()] + self.html + text[m.end():]
                    if m else self.html + text)

        # Content-length and content-type are re-derived: the body just changed
        # length, and a stale length truncates the page in the browser rather
        # than failing loudly.
        headers = {k: v for k, v in response.headers.items()
                   if k.lower() not in ("content-length", "content-type")}
        return Response(content=text.encode("utf-8"),
                        status_code=response.status_code,
                        headers=headers,
                        media_type="text/html; charset=utf-8")
