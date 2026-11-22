"""Every operator script must be pointable at a deployment.

Three of them were not. `gate_baseline.py`, `backup_qa.py` and
`reset_to_baseline.py` called `cfgmod.load_config()` with no argument, so they
honoured neither `--config` nor `CWVA_DASHBOARD_CONFIG` — the environment
variable that SELECTS the production instance. They were hardwired to QA, and a
`--config config/production.rson` was accepted and ignored in silence.

I ran `gate_baseline.py --config config/production.rson` and read QA's gate
numbers as production's (2026-10-01). The dangerous one is
`reset_to_baseline.py`, which OPERATIONS.md marks **destructive, both sides**:
pointed at production it would have rolled back QA instead, and reported
success.

The scope is DERIVED from the scripts directory, so a new script cannot miss
this, and the test is about the ability to select — not about any one script.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
SRC = Path(__file__).resolve().parents[1] / "src" / "cwva_dashboard"

#: Scripts that legitimately take no config: they act on this repo or on
#: arguments alone, never on a deployment's sandbox.
NO_CONFIG: frozenset[str] = frozenset()


def _scripts():
    return sorted(p for p in SCRIPTS.glob("*.py") if not p.name.startswith("_"))


def _src_entry_points():
    """CLI entry points that live in the PACKAGE rather than in `scripts/`.

    `tools/repl.py` is one, and it had both defects this file tests for: it
    called `load_config()` with no argument, so a REPL pointed at production
    minted records into QA's sovereign namespace, and its audit path was a
    fixed filename shared with whatever dashboard was running. Neither was
    visible here, because the scope above is `scripts/` and this module is
    `src/` — the test was right about the rule and wrong about where the rule
    applies (2026-10-29).

    Derived the same way, so the next `python -m` entry point cannot miss it:
    anything with a `__main__` guard.
    """
    out = []
    for f in sorted(SRC.rglob("*.py")):
        if '__name__ == "__main__"' in f.read_text(encoding="utf-8"):
            out.append(f)
    return out


def _loads_config(tree) -> bool:
    """Does it call `load_config` at all?"""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            name = getattr(f, "attr", None) or getattr(f, "id", None)
            if name == "load_config":
                return True
    return False


def _bare_load_config(tree) -> bool:
    """`load_config()` with NO path — the defect. It silently means QA."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            name = getattr(f, "attr", None) or getattr(f, "id", None)
            if name == "load_config" and not node.args and not node.keywords:
                return True
    return False


def test_there_are_scripts_to_check():
    """A scope derived from a glob is worth nothing if the glob is empty."""
    assert len(_scripts()) > 5


@pytest.mark.parametrize("path", _scripts(), ids=lambda p: p.name)
def test_a_script_that_reads_config_can_be_POINTED_at_a_deployment(path):
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    if not _loads_config(tree) or path.name in NO_CONFIG:
        pytest.skip("acts on no deployment")

    assert "--config" in src, (
        f"{path.name} reads config but cannot be pointed at a deployment; "
        "it will silently act on the default one"
    )


@pytest.mark.parametrize("path", _scripts(), ids=lambda p: p.name)
def test_no_script_calls_load_config_with_NO_path(path):
    """The exact shape of the defect, which `--config` in the source does not
    rule out: a script can parse the flag and still call `load_config()`."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    if path.name in NO_CONFIG:
        pytest.skip("acts on no deployment")

    assert not _bare_load_config(tree), (
        f"{path.name} calls load_config() with no path, which is "
        "config/dashboard.rson whatever the operator asked for"
    )


@pytest.mark.parametrize("path", _scripts(), ids=lambda p: p.name)
def test_the_ENV_VAR_is_honoured_where_the_flag_is(path):
    """`CWVA_DASHBOARD_CONFIG` is how the production instance is selected
    (`uvicorn` reads it), so an operator who exported it expects a script to
    follow. Either the script resolves it itself, or it goes through
    `create_app`, which does."""
    src = path.read_text(encoding="utf-8")
    if "--config" not in src or path.name in NO_CONFIG:
        pytest.skip("takes no config")

    assert ("CWVA_DASHBOARD_CONFIG" in src or "create_app" in src), (
        f"{path.name} takes --config but ignores CWVA_DASHBOARD_CONFIG, so the "
        "two ways of selecting a deployment disagree"
    )


def test_the_DESTRUCTIVE_script_is_covered():
    """Named explicitly, because this is the one where getting it wrong rolls
    back the wrong deployment and reports success."""
    src = (SCRIPTS / "reset_to_baseline.py").read_text(encoding="utf-8")

    assert "--config" in src
    assert "CWVA_DASHBOARD_CONFIG" in src


@pytest.mark.parametrize("name", ["gate_baseline", "backup_qa",
                                  "reset_to_baseline"])
def test_each_fixed_script_REPORTS_which_config_it_used(name):
    """An operator who cannot see which deployment a script chose has to trust
    it — the same rule the record pickers follow about their sort order."""
    src = (SCRIPTS / f"{name}.py").read_text(encoding="utf-8")

    assert "config : " in src, f"{name} does not say which config it used"


# --- the same two rules, for CLI entry points inside the package ----------


def test_there_are_src_entry_points_to_check():
    """`tools/repl.py` at least. An empty scope would pass silently."""
    assert _src_entry_points(), "no __main__ entry point found under src/"


@pytest.mark.parametrize("path", _src_entry_points(), ids=lambda p: p.name)
def test_a_package_entry_point_can_be_POINTED_at_a_deployment(path):
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    if not _loads_config(tree):
        pytest.skip("acts on no deployment")
    assert "--config" in src, (
        f"{path.name} reads config but cannot be pointed at a deployment"
    )


@pytest.mark.parametrize("path", _src_entry_points(), ids=lambda p: p.name)
def test_no_package_entry_point_calls_load_config_with_NO_path(path):
    """The defect `tools/repl.py` carried: it parsed `--config`, resolved the
    SANDBOX from it, and then took identity from `load_config()` — so the two
    halves of one run could come from different deployments."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assert not _bare_load_config(tree), (
        f"{path.name} calls load_config() with no path, which is "
        "config/dashboard.rson whatever the operator asked for"
    )


def test_no_entry_point_hardcodes_an_AUDIT_PATH():
    """One audit log per instance, named after its sandbox.

    `tools/repl.py` used a fixed `~/.local/state/cwva-dashboard/audit.jsonl`,
    so a REPL on production and a dashboard on QA wrote one file. The chain
    reads its tail once at construction, so two writers each link onto the tail
    as they found it and `verify()` reports a break — which is how Rick's log
    failed from 2026-08-25. Everything that opens an `AuditLog` must derive the
    name from the sandbox, which is what `audit.default_path` is for.
    """
    HELPERS = {"default_path", "_default_audit_path"}

    def _derives(node) -> bool:
        """Is this expression a call to the helper (possibly via `x or f(y)`)?"""
        if isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            return name in HELPERS
        if isinstance(node, ast.BoolOp):          # `audit_path or default_path(root)`
            return any(_derives(v) for v in node.values)
        return False

    offenders = []
    for path in _src_entry_points() + _scripts():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name != "AuditLog" or not node.args:
                continue
            if not _derives(node.args[0]):
                offenders.append(f"{path.name}:{node.lineno}")

    # Checked on the AST, not by searching the text. The first version of this
    # test asked whether "default_path" appeared anywhere in the file, which
    # the IMPORT line satisfies — so it passed against a deliberately
    # hardcoded path. A substring sniff standing in for a structural claim is
    # the same mistake this file is about.
    assert not offenders, (
        f"{offenders} pass an AuditLog path that is not derived from the "
        "sandbox; two deployments would share one chain"
    )
