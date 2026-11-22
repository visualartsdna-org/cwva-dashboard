"""The shipped config and the code default must list the same file kinds.

`config.inbox()` REPLACES `DEFAULT_EXTENSIONS` with whatever the config names,
so the code default governs only a deployment that omits the block — and the
shipped config does not omit it. Two copies of one closed set, and they drifted
the first time one was edited: `.hdr` was added to the default and the running
dashboard went on offering the seven the config named (2026-09-27).

The config is allowed to differ — that is what it is for. What is not allowed is
for the SHIPPED config, which is this deployment's reference, to disagree with
the default silently.
"""

from __future__ import annotations

from pathlib import Path

from cwva_dashboard import config as cfgmod
from cwva_dashboard.inbox import DEFAULT_EXTENSIONS

# The SHIPPED config is base.rson (2026-11-21): an installation's own file
# extends it, and the file kinds live there.
CONFIG = Path(__file__).resolve().parents[1] / "config" / "base.rson"


def _shipped() -> dict:
    block = (cfgmod.load_config(CONFIG).get("inbox") or {}).get("extensions") or {}
    return {kind: tuple(v) for kind, v in block.items()}


def test_the_same_KINDS_are_offered():
    assert set(_shipped()) == set(DEFAULT_EXTENSIONS)


def test_the_same_EXTENSIONS_per_kind():
    shipped = _shipped()
    for kind, exts in sorted(DEFAULT_EXTENSIONS.items()):
        assert shipped[kind] == exts, kind


def test_the_config_is_what_actually_governs():
    """Not a restatement of the above: it pins the precedence the drift came
    from, so a future change to merge-instead-of-replace is a deliberate one."""
    cfg = {"inbox": {"path": "/tmp/x", "extensions": {"image": [".only"]}}}
    box = cfgmod.inbox(cfg)

    assert box.extensions == {"image": (".only",)}


def test_an_HDR_is_offered_as_an_image():
    assert ".hdr" in _shipped()["image"]
    assert ".hdr" in DEFAULT_EXTENSIONS["image"]
