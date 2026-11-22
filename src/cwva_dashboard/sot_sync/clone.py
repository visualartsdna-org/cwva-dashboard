"""Seeding a disposable shadow SOT from live production content (§2b/§2c).

The shadow SOT exists so the dashboard can be driven by a human against
*realistic* content — real drift, real orphans, real legacy quirks — rather than
fixtures. It is seeded by cloning production, and the clone runs **through the
sync machinery rather than around it**: `snapshot()` to enumerate, `fetch()` to
read, and the target's own `converge()` to write, so the seed exercises the same
code paths a promotion does instead of an ad-hoc copy loop that could diverge
from them.

Direction is enforced by type, not by care (§2e): the production side arrives as
a :class:`ReadOnlySource`, which has no ``converge`` method at all, so "push to
production" is not something this function could do even if asked.

Objects are staged in bounded batches rather than materializing the whole bucket
locally — a real SOT is multi-gigabyte, and peak disk should not scale with it.
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..promotion.transports import ReadOnlySource, Transport
from ..promotion.unit import ChangeManifest

__all__ = ["clone_source_to_target", "CloneReport", "MirrorPlan", "plan_mirror",
           "mirror_source_to_target", "MAX_DELETE_FRACTION"]

ProgressFn = Callable[["CloneReport"], None]


@dataclass
class CloneReport:
    """What the clone did, and what it cost (§2d: measure, don't optimize)."""

    objects: int = 0
    bytes_copied: int = 0
    batches: int = 0
    skipped: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    elapsed_s: float = 0.0
    source_objects: int = 0

    @property
    def mb(self) -> float:
        return self.bytes_copied / 1e6

    @property
    def rate_mb_s(self) -> float:
        return (self.mb / self.elapsed_s) if self.elapsed_s else 0.0

    def summary(self) -> str:
        return (
            f"{self.objects}/{self.source_objects} objects, {self.mb:.1f} MB "
            f"in {self.elapsed_s:.1f}s ({self.rate_mb_s:.2f} MB/s), "
            f"{len(self.skipped)} skipped, {len(self.failures)} failed"
        )

    def to_dict(self) -> dict:
        return {
            "objects": self.objects,
            "source_objects": self.source_objects,
            "bytes_copied": self.bytes_copied,
            "mb": round(self.mb, 2),
            "batches": self.batches,
            "elapsed_s": round(self.elapsed_s, 2),
            "rate_mb_s": round(self.rate_mb_s, 3),
            "skipped": self.skipped,
            "failures": self.failures,
        }


def clone_source_to_target(
    source: ReadOnlySource,
    target: Transport,
    staging: str | Path,
    *,
    include: Callable[[str], bool] | None = None,
    batch_objects: int = 50,
    batch_bytes: int = 256 * 1024 * 1024,
    progress: ProgressFn | None = None,
) -> CloneReport:
    """Copy every object ``source`` exposes into ``target``, batching through
    ``staging``.

    ``include`` optionally filters source relpaths (e.g. to seed RDF before
    images). Filtered paths are recorded in ``report.skipped`` so the report
    describes the shadow's actual contents rather than an intention.

    A per-object failure is recorded and the clone continues: on a multi-
    thousand-object bucket, aborting the whole seed for one unreadable blob
    wastes everything already transferred. The report is the authority on
    whether the shadow is complete.
    """
    if hasattr(source, "converge"):  # pragma: no cover - defense against misuse
        raise TypeError(
            "clone source must be read-only (a ReadOnlySource); refusing a writable source"
        )

    staging = Path(staging)
    staging.mkdir(parents=True, exist_ok=True)
    report = CloneReport()
    started = time.monotonic()

    paths = sorted(source.snapshot())
    report.source_objects = len(paths)

    pending: list[str] = []
    pending_bytes = 0

    def flush() -> None:
        nonlocal pending, pending_bytes
        if not pending:
            return
        target.converge(staging, ChangeManifest(adds=sorted(pending)), message="shadow seed")
        report.batches += 1
        for rel in pending:
            fp = staging / rel
            if fp.exists():
                fp.unlink()
        pending = []
        pending_bytes = 0
        report.elapsed_s = time.monotonic() - started
        if progress:
            progress(report)

    for rel in paths:
        if include is not None and not include(rel):
            report.skipped.append(rel)
            continue
        try:
            data = source.fetch(rel)
        except Exception as exc:
            report.failures.append(f"{rel}: {type(exc).__name__}: {exc}")
            continue
        dest = staging / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        pending.append(rel)
        pending_bytes += len(data)
        report.objects += 1
        report.bytes_copied += len(data)
        if len(pending) >= batch_objects or pending_bytes >= batch_bytes:
            flush()

    flush()
    report.elapsed_s = time.monotonic() - started

    # Staging is scratch, never a second copy of the SOT.
    shutil.rmtree(staging, ignore_errors=True)
    return report


# -- mirror: make the shadow EQUAL to production -------------------------------
#
# The clone above is adds-only, so the shadow keeps everything QA ever promoted
# to it: a second "Fairy Pool 3", a record called "junk", two concepts
# production never had (measured 2026-11-18: 20 shadow-only objects). Those make
# QA disagree with production for reasons that have nothing to do with the code
# under test. A mirror also deletes what production does not have, and copies
# only what is new or changed, so a re-seed stops costing a full image copy.
#
# NOTHING from QA survives a mirror (Rick, 2026-11-19: "Prod should be copied
# over QA in its entirety"). That includes `operational/`: after a mirror the
# QA history bundle there describes a tree that no longer exists, and restoring
# it would undo the very clone that was asked for. Production's backups come
# across like any other object. Not deleted: a `qa_only` path held deliberately ahead, and
# anything outside the prefix filter — a mirror of `ttl/` says nothing about
# `images/`.

#: A mirror that would delete more than this share of the shadow's content is
#: refused. The likely cause is the wrong bucket, a wrong prefix, or a listing
#: that came back empty, and the cost of being wrong is the whole shadow.
MAX_DELETE_FRACTION = 0.25


@dataclass
class MirrorPlan:
    new: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    delete: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)  # shadow-only, deliberately kept
    unchanged: int = 0
    source_objects: int = 0
    target_objects: int = 0

    @property
    def copy(self) -> list[str]:
        return sorted([*self.new, *self.changed])

    def refusal(self, max_fraction: float = MAX_DELETE_FRACTION) -> str | None:
        """Why this plan must not run, or None."""
        if self.source_objects == 0:
            return ("production listed NO objects: wrong bucket, wrong prefix or no "
                    "access. A mirror of nothing would empty the shadow.")
        content = self.target_objects - len(self.kept)
        if self.delete and content and len(self.delete) > max_fraction * content:
            return (f"{len(self.delete)} of {content} shadow objects would be deleted, "
                    f"more than {max_fraction:.0%}. Check the buckets and prefix.")
        return None

    def to_dict(self) -> dict:
        return {"new": self.new, "changed": self.changed, "delete": self.delete,
                "kept": self.kept, "unchanged": self.unchanged,
                "source_objects": self.source_objects,
                "target_objects": self.target_objects}


def plan_mirror(source_snapshot: dict, target_snapshot: dict, *,
                include: Callable[[str], bool] | None = None,
                keep: Callable[[str], bool] | None = None) -> MirrorPlan:
    """What a mirror would do, from two ``{relpath: fingerprint}`` snapshots.

    Pure, so the dry run and the real run are the same computation.
    ``include`` is the prefix filter (paths outside it are neither copied nor
    deleted); ``keep`` marks shadow paths that must survive. The script passes
    none: a mirror keeps nothing of QA's.
    """
    plan = MirrorPlan(source_objects=len(source_snapshot),
                      target_objects=len(target_snapshot))
    for rel, fp in sorted(source_snapshot.items()):
        if include is not None and not include(rel):
            continue
        if rel not in target_snapshot:
            plan.new.append(rel)
        elif target_snapshot[rel] != fp:
            plan.changed.append(rel)
        else:
            plan.unchanged += 1
    for rel in sorted(target_snapshot):
        if rel in source_snapshot:
            continue
        if (keep is not None and keep(rel)) or (include is not None and not include(rel)):
            plan.kept.append(rel)
        else:
            plan.delete.append(rel)
    return plan


def mirror_source_to_target(source: ReadOnlySource, target: Transport, staging,
                            plan: MirrorPlan, *, progress: ProgressFn | None = None,
                            max_fraction: float = MAX_DELETE_FRACTION) -> CloneReport:
    """Carry out ``plan``: copy what is new or changed, then delete what
    production does not have. Refuses a plan :meth:`MirrorPlan.refusal`
    objects to, before writing anything."""
    why = plan.refusal(max_fraction)
    if why:
        raise ValueError(f"mirror refused: {why}")
    wanted = set(plan.copy)
    report = clone_source_to_target(source, target, staging,
                                    include=lambda rel: rel in wanted,
                                    batch_objects=100, progress=progress)
    report.skipped = []  # everything unchanged; not news
    if plan.delete:
        Path(staging).mkdir(parents=True, exist_ok=True)
        target.converge(staging, ChangeManifest(deletes=list(plan.delete)),
                        message="shadow mirror: remove what production does not have")
    return report
