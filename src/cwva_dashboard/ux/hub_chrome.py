"""The hub's header — logo and navigation bar — for a page that is not the hub.

Monitoring is a top-level destination in the nav bar but a page of its own,
and it was the one destination that dropped the bar and the logo (Rick,
2026-11-19). The header is cut out of ``html/function.html`` itself rather
than copied, so the two cannot drift: a nav item added to the hub appears here
too. The hub's tab buttons become links back to the hub that open on that tab
(``/#tools``), and the page's own item is lit.
"""

from __future__ import annotations

import re

__all__ = ["hub_chrome"]

_CSS_START = ":root {"
_CSS_HEADER = "/* Header */"
_CSS_END = "/* Main Layout */"
_FONTS = re.compile(r'<link href="https://fonts\.googleapis\.com[^>]*>')



def hub_chrome(hub_html: str, active: str) -> tuple[str, str, str]:
    """``(head links, css, header html)`` cut from the hub, with ``active``
    (the nav item's label) lit and every tab button turned into a link."""
    s = hub_html.index(_CSS_START)
    root_end = hub_html.index("}", s) + 1
    h, e = hub_html.index(_CSS_HEADER), hub_html.index(_CSS_END)
    # The page's own stylesheet must come AFTER this and restate the few rules
    # its bare `header` selector overrides (forms._HUB_FIX).
    css = hub_html[s:root_end] + "\n" + hub_html[h:e]

    a, b = hub_html.index('<header class="header">'), hub_html.index("</header>")
    header = hub_html[a:b + len("</header>")]
    header = header.replace("nav-tab active", "nav-tab")
    header = re.sub(r'<button class="nav-tab" data-tab="([\w-]+)">([^<]*)</button>',
                    r'<a class="nav-tab" href="/#\1">\2</a>', header)
    # The hub's own links are relative ("instances"), which a page one level
    # down (/about/tour) would resolve to /about/instances.
    header = re.sub(r'(<a class="nav-tab" href=")(?![/#]|https?:)', r'\1/', header)
    header = re.sub(r'(<a class="nav-tab)(" href="[^"]*">)(' + re.escape(active) + r')</a>',
                    r'\1 active\2\3</a>', header)
    # The logo is the way home, as it is everywhere else.
    header = header.replace('<div class="logo">',
                            '<a class="logo" href="/" style="color:inherit;'
                            'text-decoration:none">', 1)
    # ...closed where the logo's <div> closed: after the title AND the version
    header = re.sub(r'(<a class="logo"[^>]*>.*?)</div>', r'\1</a>', header,
                    count=1, flags=re.S)
    fonts = _FONTS.search(hub_html)
    return (fonts.group(0) if fonts else ""), css, header
