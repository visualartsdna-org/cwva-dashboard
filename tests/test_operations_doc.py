"""OPERATIONS.md lists every operator entry point.

The cheat sheet asks future sessions to add new scripts and routes to it. That
is a promise, and this project has learned repeatedly that a promise kept by
comment drifts — the picker/gate tables, the collision check's field list, the
updateWorkOnSite page copy. So the promise is a test.

It checks EXISTENCE, not wording: a route or script must be mentioned, and what
is said about it is a human's job.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = (ROOT / "docs" / "OPERATIONS.md").read_text()


def test_every_route_is_documented():
    src = (ROOT / "src" / "cwva_dashboard" / "main.py").read_text()
    routes = set(re.findall(r'@app\.(?:get|post|api_route)\("([^"]+)"', src))

    missing = sorted(r for r in routes if r not in DOC)
    assert not missing, f"routes missing from OPERATIONS.md: {missing}"


def test_every_operator_script_is_documented():
    scripts = {p.name for p in (ROOT / "scripts").glob("*.py")}

    missing = sorted(s for s in scripts if s not in DOC)
    assert not missing, f"scripts missing from OPERATIONS.md: {missing}"


def test_the_destructive_ones_are_marked_as_such():
    """These three delete or overwrite. Someone skimming the sheet for a command
    must not have to read the prose to find that out."""
    for dangerous in ("reset_to_baseline.py", "/wip/discard", "--force-qa-only"):
        rows = [ln for ln in DOC.splitlines() if dangerous in ln and ln.startswith("|")]
        assert rows, f"{dangerous} is not in a table row"
        # A command can have a read-only rehearsal (--dry-run) alongside the
        # real thing; it is the REAL one that has to carry the warning.
        acting = [ln for ln in rows if "read-only" not in ln.lower()]
        assert acting, f"{dangerous} has only read-only rows, which cannot be right"
        for ln in acting:
            assert re.search(r"destructive|overwrite|writes the shadow", ln, re.I), (
                f"unflagged row for {dangerous}: {ln}"
            )
