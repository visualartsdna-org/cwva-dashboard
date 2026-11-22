"""Every module a tool handler can reach must be imported BEFORE confinement.

Tool handlers run inside the Landlock-confined worker, which may read
`sys.prefix` and `/usr` — so third-party imports still work — but **not the
project tree**, because an editable install lives outside both. A first-party
module imported lazily inside a handler is therefore read from disk for the
first time while confined, and the import fails:

    PermissionError: [Errno 13] Permission denied:
        '…/src/cwva_dashboard/tools/property_map.py'

which is what Rick got opening a record on 2026-09-16, one commit after the
editor started consulting the property map. The fixtures could not catch it:
they run `enforce_landlock=False`, so the worker reads whatever it likes.

This is a property of the deferred-import STYLE, not of one module, so it is
checked by scanning rather than by listing. Deferred imports are otherwise
idiomatic here — they keep import time down and break cycles — and they are
perfectly safe once the module is already in `sys.modules`.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from conftest import TEST_DOMAIN
from cwva_dashboard.tools.fileops_tools import build_default_registry

SRC = Path(__file__).resolve().parents[2] / "src" / "cwva_dashboard"

def handler_modules(registry) -> set:
    """The modules that define registered handlers — DERIVED from the registry,
    not a list of directories.

    The distinction matters twice over. `tools/repl.py` and
    `workflows/promote.py` both defer first-party imports and both are perfectly
    safe, because neither runs confined: the REPL harness drives the worker from
    the parent, and the promotion tail is trusted-orchestrator machinery that is
    never a registry tool (law 1). A directory list called them offenders. What
    actually runs inside the jail is whatever a registered handler is, so ask
    the registry.

    The limit, stated rather than hidden: a handler calling a helper in some
    third module leaves that module unscanned. Every current handler's own
    module is covered, which is where this class of bug has appeared.
    """
    import functools

    mods = set()
    for name in registry.names():
        tool = registry.get(name)
        fn = tool.handler
        while isinstance(fn, functools.partial):
            fn = fn.func
        fn = getattr(fn, "__wrapped__", fn)
        mod = getattr(fn, "__module__", "")
        if mod.startswith("cwva_dashboard"):
            mods.add(mod)
    return mods


def _module_of(path: Path) -> str:
    rel = path.relative_to(SRC).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(["cwva_dashboard", *parts])


def _deferred_first_party(path: Path) -> list[tuple[int, str]]:
    """(line, module) for every first-party import nested inside a function."""
    tree = ast.parse(path.read_text())
    here = _module_of(path)
    found = []

    class Visitor(ast.NodeVisitor):
        def __init__(self):
            self.depth = 0

        def visit_FunctionDef(self, node):
            self.depth += 1
            self.generic_visit(node)
            self.depth -= 1

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_ImportFrom(self, node):
            if self.depth and node.level:  # relative == first-party
                base = here.rsplit(".", node.level)[0]
                found.append((node.lineno, f"{base}.{node.module}" if node.module else base))
            elif self.depth and (node.module or "").startswith("cwva_dashboard"):
                found.append((node.lineno, node.module))

        def visit_Import(self, node):
            if self.depth:
                for alias in node.names:
                    if alias.name.startswith("cwva_dashboard"):
                        found.append((node.lineno, alias.name))

    Visitor().visit(tree)
    return found


def test_nothing_a_handler_imports_is_read_AFTER_confinement():
    """Build the registry exactly as `create_app` does — the trusted parent,
    before the worker forks — then check that every module a handler could
    import lazily is already loaded."""
    registry = build_default_registry(domain=TEST_DOMAIN)
    modules = handler_modules(registry)
    assert modules, "no handler modules resolved — the scan would pass vacuously"

    offenders = []
    for name in sorted(modules):
        path = SRC.joinpath(*name.split(".")[1:]).with_suffix(".py")
        if not path.exists():
            continue
        for lineno, module in _deferred_first_party(path):
            if module not in sys.modules:
                offenders.append(
                    f"{path.relative_to(SRC.parent.parent)}:{lineno} imports "
                    f"{module}, which building the registry does not load — so "
                    f"the confined worker reads it from the project tree and "
                    f"gets EACCES"
                )

    assert not offenders, "\n".join(offenders)


def test_the_scanner_can_actually_SEE_a_deferred_import():
    """A guard whose finder is broken is worse than no guard: it reports clean
    forever. This proves the scan finds what it is looking for."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        fake = Path(tmp) / "fake.py"
        fake.write_text("def f():\n    from .nowhere import thing\n    return thing\n")
        # relative to SRC so `_module_of` resolves; contents are what matter
        target = SRC / "tools" / "_scanner_probe.py"
        try:
            target.write_text(fake.read_text())
            found = _deferred_first_party(target)
        finally:
            target.unlink(missing_ok=True)

    assert found and found[0][1].endswith("nowhere"), found
