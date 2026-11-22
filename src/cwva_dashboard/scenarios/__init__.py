"""Scenario harness — replayable, **driver-agnostic** workflow episodes.

A scenario is a sequence of steps, each a **registry-tool or workflow invocation
with arguments** (never an HTTP call or UI action). That is deliberate: Phase 5's
comparison method is "same scenarios, two drivers" — a human driving the UX and
the agent driving the tools replay the *identical* step list. Because steps are
tool calls, that property is free.

Steps run through a :class:`StepExecutor` that routes registry tools to the
registry and workflow ops (promote / rollback / sync / adopt) to the
orchestrator. The expected end state (SOT contents, QA clean, queue positions)
is transport-agnostic, so one scenario replays across files / git_local /
gcp_bucket unchanged.
"""

from .harness import Scenario, ScenarioEnv, Step, StepExecutor, assert_end_state, replay

__all__ = ["Scenario", "Step", "StepExecutor", "ScenarioEnv", "replay", "assert_end_state"]
