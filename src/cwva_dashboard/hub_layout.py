"""The hub's card order: how Rick has arranged a section, kept between visits.

A preference, not content: it lives beside the audit log, outside the sandbox
and outside any SOT, in one file shared by every dashboard on this machine, so
QA and production show the same arrangement. Cards are named by their link
(``edit``, ``rdf/profile/<guid>``), which is what stays the same when a card's
words change. A card the saved order does not name keeps its place after the
named ones, so a new profile card appears rather than vanishing.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

__all__ = ["load_layout", "save_order", "SECTIONS", "LayoutError"]

#: The sections whose cards can be moved. One, for now.
SECTIONS = ("content",)
_MAX_CARDS = 200
_MAX_KEY = 300


class LayoutError(ValueError):
    pass


def load_layout(path: Path) -> dict:
    """``{section: [card key, ...]}``; empty when nothing was saved, or the
    file is unreadable (a broken preference must never break the hub)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: [str(x) for x in v] for k, v in data.items()
            if k in SECTIONS and isinstance(v, list)}


def save_order(path: Path, section: str, order) -> list:
    """Replace one section's order; ``[]`` resets it to the page's own."""
    if section not in SECTIONS:
        raise LayoutError(f"unknown section {section!r}")
    if not isinstance(order, list) or len(order) > _MAX_CARDS:
        raise LayoutError("order must be a list of card keys")
    keys = []
    for k in order:
        if not isinstance(k, str) or not k or len(k) > _MAX_KEY:
            raise LayoutError("a card key must be a short non-empty string")
        if k not in keys:
            keys.append(k)
    layout = load_layout(path)
    if keys:
        layout[section] = keys
    else:
        layout.pop(section, None)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".hub-layout-")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(layout, fh, indent=2)
    os.replace(tmp, path)  # whole file or nothing: a torn write reads as {}
    return keys
