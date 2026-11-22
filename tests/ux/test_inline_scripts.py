"""The inline scripts are real JavaScript, and nothing else here proves it.

Every page-behaviour test in this suite runs through TestClient, which executes
no JavaScript — so a script can be syntactically broken and every test still
passes. That happened: `out.join('\\n')` was written into a non-raw Python
string, so the page shipped a literal newline INSIDE a JS string literal. An
unterminated string is a parse error, and a parse error kills the whole block —
the unsaved-edits guard would have been silently absent on every page.

This is not a JavaScript engine. It is the one check that catches that class:
inside a `<script>`, a quoted string may not run past the end of its line.
"""

from __future__ import annotations

import re

import pytest

from cwva_dashboard.ux import forms

from cwva_dashboard.ux import board_page, hub_cards, viewer_page

# Every page module's inline script, not only forms.py's: the board, the
# viewer and the hub's card mover were each written after this test and none
# was in its scope (2026-11-19).
_MODULES = {"forms": forms, "board_page": board_page, "viewer_page": viewer_page}
_BODIES = {
    f"{mod}.{name}": getattr(m, name)
    for mod, m in _MODULES.items() for name in dir(m)
    if name.endswith("_SCRIPT") and isinstance(getattr(m, name), str)
}
_BODIES["hub_cards.render_card_mover"] = hub_cards.render_card_mover(
    "content", ["edit", "a</script>b"])[len(hub_cards._CSS):]
SCRIPTS = sorted(_BODIES)


def _unescaped(line: str, quote: str) -> int:
    return len(re.findall(rf"(?<!\\){quote}", line))


@pytest.mark.parametrize("name", SCRIPTS)
def test_no_string_literal_runs_past_its_line(name):
    body = _BODIES[name]
    assert "<script>" in body, name
    for lineno, line in enumerate(body.splitlines(), 1):
        # A comment may say anything; only code is checked.
        code = line.split("//", 1)[0]
        for quote in ("'", '"'):
            assert _unescaped(code, quote) % 2 == 0, (
                f"{name} line {lineno}: unbalanced {quote} — a string literal "
                f"cannot span a newline in JavaScript:\n  {line}"
            )


@pytest.mark.parametrize("name", SCRIPTS)
def test_delimiters_balance(name):
    body = _BODIES[name]
    inner = body[body.index(">") + 1:body.rindex("</script>")]
    for opener, closer in ("()", "{}", "[]"):
        assert inner.count(opener) == inner.count(closer), f"{name}: {opener}{closer}"
