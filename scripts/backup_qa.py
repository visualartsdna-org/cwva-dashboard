"""Back up what SOT cannot give back: the QA history and the attic — READ-ONLY
against the content tree.

The QA content tree is reconstructible from SOT. Its commit history is not, and
law 6 makes rollback depend on that history being present; nor is `.qa/attic`,
the superseded binaries kept as the rollback reserve for a replaced image, since
SOT holds the replacement by definition.

Both land in the target's `operational/` prefix, which is excluded from sync —
see `cwva_dashboard.backup` for why that exclusion is load-bearing.

Usage:
    python scripts/backup_qa.py            # bundle + attic -> SOT operational/
    python scripts/backup_qa.py --status   # report what would be backed up
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cwva_dashboard import config as cfgmod  # noqa: E402
from cwva_dashboard.backup import attic_status, run_backup  # noqa: E402


def _transport(cfg):
    """The instance's own target, whichever kind it is (folder, git, bucket)."""
    from cwva_dashboard.promotion.targets import TargetError, build_transport

    target = cfg.get("sot") or cfgmod.shadow_sot(cfg)
    try:
        return build_transport(target, cfgmod.active_layout(cfg))
    except TargetError as exc:
        raise SystemExit(f"error: {exc}") from None


#: `--config`, else `CWVA_DASHBOARD_CONFIG`, else this repo's default. The same
#: precedence `sync_shadow_to_qa.py` and `split_aggregate.py` use.
#:
#: **It was missing, and the omission was silent.** This script called
#: `load_config()` with no argument, so it honoured neither the flag nor the
#: environment variable that SELECTS the production instance — it was hardwired
#: to QA, and a `--config config/production.rson` was accepted and ignored. I
#: ran it that way myself and read QA's numbers as production's (2026-10-01).
def _config_path(argv: list[str]) -> str:
    if "--config" in argv:
        return argv[argv.index("--config") + 1]
    return os.environ.get("CWVA_DASHBOARD_CONFIG") or cfgmod.DEFAULT_CONFIG_PATH


def main(argv: list[str]) -> int:
    config_path = _config_path(argv)
    cfg = cfgmod.load_config(config_path)
    print(f"config : {config_path}")
    root = cfgmod.sandbox_root(cfg)
    attic = attic_status(root)

    if "--status" in argv:
        print(json.dumps({"sandbox": str(root), "attic": attic}, indent=2))
        return 0

    transport = _transport(cfg)
    print(f"sandbox : {root}")
    print(f"target  : {transport.name} operational/")
    print(f"attic   : {attic['files']} file(s), {attic['bytes'] / 1e6:.1f} MB")

    res = run_backup(root, transport)
    print(json.dumps(res.to_dict(), indent=2))
    if not res.ok:
        print("FAILED", file=sys.stderr)
        return 1
    print(f"\nbacked up {res.commits} commits ({res.bundle_bytes / 1e6:.2f} MB)"
          + (f", the ledger ({res.ledger_bytes} bytes)" if res.ledger_bytes else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
