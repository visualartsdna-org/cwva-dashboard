"""Scenario model, executor, and replay/assert (see package docstring)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from ..promotion.gates import Assertion
from ..promotion.qa_git import QAGit
from ..promotion.rollback import rollback_unit
from ..promotion.transports import (
    FilesTransport,
    GcpBucketTransport,
    GitLocalTransport,
    Transport,
    _git,
    _git_commit,
)
from ..sandbox.pointers import DEFAULT_GIT_CONTENT_EXTENSIONS
from ..sot_sync.sync import adopt_external, sync
from ..workflows.promote import run_promotion

__all__ = ["Step", "Scenario", "ScenarioEnv", "StepExecutor", "replay", "assert_end_state"]


@dataclass
class Step:
    op: str  # a registry tool name, or a workflow op (workflow.*, sot.*, env.*)
    args: dict = field(default_factory=dict)
    # optional subset-match against the step's result, for episodes whose point
    # is an intermediate observation (e.g. that sot.sync *saw* the drift) rather
    # than the end state alone.
    expect: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {"op": self.op, "args": self.args}
        if self.expect:
            d["expect"] = self.expect
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Step":
        return cls(op=d["op"], args=dict(d.get("args", {})), expect=dict(d.get("expect", {})))


@dataclass
class Scenario:
    name: str
    steps: list  # list[Step]
    expected: dict = field(default_factory=dict)  # sot / qa_clean / queues
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "steps": [s.to_dict() for s in self.steps],
            "expected": self.expected,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, d: dict) -> "Scenario":
        return cls(
            name=d["name"],
            description=d.get("description", ""),
            steps=[Step.from_dict(s) for s in d.get("steps", [])],
            expected=dict(d.get("expected", {})),
        )


@dataclass
class ScenarioEnv:
    """The live environment a scenario runs against: the confined tool surface
    (registry + fileops over the QA content) and the orchestrator machinery
    (QA git + transport). One env per transport family."""

    fileops: object
    registry: object
    qa: QAGit
    transport: Transport
    git_content_extensions: frozenset = DEFAULT_GIT_CONTENT_EXTENSIONS


class StepExecutor:
    def __init__(self, env: ScenarioEnv):
        self.env = env
        # workflow cursor: pre-work QA stamp + SOT baseline for the next promote
        self._base = env.qa.head()
        self._stamp = env.transport.current_stamp()
        self._last_unit = None

    def run_all(self, steps) -> list:
        results = []
        for step in steps:
            result = self.run(step)
            for key, want in step.expect.items():
                got = result.get(key)
                assert got == want, f"{step.op}: {key} == {got!r}, expected {want!r}"
            results.append(result)
        return results

    def run(self, step: Step) -> dict:
        op, args = step.op, step.args
        if op == "workflow.begin":
            self._base = self.env.qa.head()
            self._stamp = self.env.transport.current_stamp()
            return {"base": self._base}
        if op == "workflow.promote":
            return self._promote(args)
        if op == "workflow.rollback":
            return self._rollback(args)
        if op == "sot.sync":
            r = sync(self.env.qa, self.env.transport, git_content_extensions=self.env.git_content_extensions)
            return {"clean": r.clean, "drift": r.drift.counts}
        if op == "sot.adopt":
            adopt_external(self.env.qa)
            self._base = self.env.qa.head()
            self._stamp = self.env.transport.current_stamp()
            return {"adopted": True}
        if op.startswith("env."):
            return self._env(op, args)
        # otherwise a registry tool
        dr = self.env.registry.dispatch(op, dict(args), self.env.fileops)
        return {"ok": dr.ok, "result": dr.result, "error": dr.error}

    def _promote(self, args) -> dict:
        assertions = [Assertion(**a) for a in args.get("assertions", [])] or None
        res = run_promotion(
            self.env.qa,
            self.env.transport,
            workflow=args.get("workflow", "entry"),
            base_commit=self._base,
            description=args.get("description", ""),
            provenance=args.get("provenance"),
            assertions=assertions,
            expected_stamp=self._stamp,
            git_content_extensions=self.env.git_content_extensions,
        )
        if res.ok:
            self._last_unit = res.unit
            self._stamp = res.applied.sot_stamp
            self._base = self.env.qa.head()
        return {"status": res.status}

    def _rollback(self, args) -> dict:
        if self._last_unit is None:
            raise RuntimeError("workflow.rollback with no prior promotion")
        rb = rollback_unit(
            self._last_unit,
            self.env.qa,
            self.env.transport,
            expected_stamp=self._stamp,
            git_content_extensions=self.env.git_content_extensions,
        )
        self._stamp = rb.sot_stamp
        self._base = self.env.qa.head()
        return {"status": "rolled_back"}

    def _env(self, op, args) -> dict:
        # environment perturbations (not driver actions): an out-of-band SOT
        # edit, for drift scenarios. Applied straight to the transport's SOT,
        # bypassing the dashboard channel — that is what "out of band" means.
        if op == "env.external_sot_edit":
            _external_edit(self.env.transport, args["path"], args["content"].encode("utf-8"))
            return {"edited": args["path"]}
        if op == "env.external_sot_delete":
            _external_delete(self.env.transport, args["path"])
            return {"deleted": args["path"]}
        raise NotImplementedError(f"env op not supported: {op}")


def _external_edit(transport: Transport, path: str, data: bytes) -> None:
    if isinstance(transport, GcpBucketTransport):
        import os
        import tempfile

        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(data)
            tmp = tf.name
        transport._bucket.blob(transport._key(path)).upload_from_filename(tmp)
        os.unlink(tmp)
    elif isinstance(transport, GitLocalTransport):  # also covers git_remote
        dst = transport.target / path
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        _git(transport.target, "add", "-A")
        _git_commit(transport.target, "external edit")
    elif isinstance(transport, FilesTransport):
        dst = transport.target / path
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
    else:
        raise NotImplementedError(f"external edit for {type(transport).__name__}")


def _external_delete(transport: Transport, path: str) -> None:
    if isinstance(transport, GcpBucketTransport):
        try:
            transport._bucket.blob(transport._key(path)).delete()
        except Exception:
            pass
    elif isinstance(transport, GitLocalTransport):
        (transport.target / path).unlink(missing_ok=True)
        _git(transport.target, "add", "-A")
        _git_commit(transport.target, "external delete")
    elif isinstance(transport, FilesTransport):
        (transport.target / path).unlink(missing_ok=True)
    else:
        raise NotImplementedError(f"external delete for {type(transport).__name__}")


# -- replay + assertions ----------------------------------------------------


def replay(scenario: Scenario, env: ScenarioEnv) -> StepExecutor:
    ex = StepExecutor(env)
    ex.run_all(scenario.steps)
    return ex


def _queue_count(fileops, directory: str) -> int:
    try:
        entries = fileops.list_dir(directory)
    except (FileNotFoundError, NotADirectoryError):
        return 0
    return sum(1 for e in entries if e.is_file)


def assert_end_state(scenario: Scenario, env: ScenarioEnv) -> None:
    """Assert the transport-agnostic end state. ``expected.sot`` maps SOT
    relpaths to an expected content string, or ``null`` for presence-only (used
    for RDF, where byte-exactness is defeated by blank-node serialization —
    correctness there is the promotion machinery's isomorphic round-trip)."""
    from ..backup import OPERATIONAL_PREFIX

    exp = scenario.expected
    exp_sot = exp.get("sot", {})
    # A scenario describes what the CONTENT channel published. `operational/`
    # holds the QA history backup, which a successful promotion now writes: not
    # content, never synced back, and not something a scenario should have to
    # enumerate. Excluded here rather than in each scenario file, so adding
    # another operational artifact does not mean editing every scenario.
    actual = {k for k in env.transport.snapshot()
              if not k.startswith(OPERATIONAL_PREFIX + "/")}
    assert actual == set(exp_sot), f"SOT paths {sorted(actual)} != expected {sorted(exp_sot)}"
    for path, content in exp_sot.items():
        if content is not None:
            got = env.transport.fetch(path).decode()
            assert got == content, f"{path}: {got!r} != {content!r}"
    if "qa_clean" in exp:
        assert env.qa.is_clean() is exp["qa_clean"]
    for directory, n in exp.get("queues", {}).items():
        assert _queue_count(env.fileops, directory) == n
