"""RSON — JSON with ``#`` comments (whole-line or inline).

Faithful to cwva_core's ``util/rson.py`` so dashboard and cwvaServer-py configs
are the **same language** (project convention: configs are RSON, not YAML). When
``cwva_core`` is packaged this can defer to it; until then it is a small,
self-contained port.

Limitation (shared with cwva_core): ``#`` is stripped even inside string values,
so config strings must not contain ``#``. RDF namespace URIs end in ``#`` (e.g.
``rdf-schema#``), so **SPARQL is not inlined in RSON** — it lives in separate
``.sparql`` files referenced by config (as cwvaServer-py does with
``res/*.sparql``).
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

__all__ = ["load", "loads"]

_COMMENT = re.compile(r"\s*#.*$")


def _strip_comments(raw: str) -> str:
    return "\n".join(_COMMENT.sub("", line) for line in raw.splitlines())


def loads(text: str) -> Any:
    """Parse RSON text (JSON + ``#`` comments)."""
    return json.loads(_strip_comments(text))


def load(path: str | os.PathLike[str]) -> Any:
    """Parse an RSON file."""
    with open(path, "r", encoding="utf-8") as fh:
        return loads(fh.read())
