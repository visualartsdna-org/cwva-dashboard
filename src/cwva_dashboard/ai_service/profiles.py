"""Task profiles: which model answers which question, and how dearly.

Law 7 — AI calls go through this module only, *driven by task profiles in
config*. The profile is the seam: a workflow names a TASK ("derive_concepts")
and never a model, so changing model, tier or budget is a config edit rather
than a code change, and the same workflow runs against an OpenAI-compatible
endpoint for CI without knowing it did.

The concept agent had the opposite arrangement — `MODEL_SONNET =
"claude-sonnet-4-6"` fixed in source — and both of its identifiers were stale
against the current model family by the time anyone looked (2026-09-29). That
is the failure mode a config seam prevents: not a wrong answer, but a silently
outdated one that nothing fails on.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..rson import loads

__all__ = ["TaskProfile", "load_profiles", "DEFAULT_PROFILES_PATH"]

DEFAULT_PROFILES_PATH = Path(__file__).resolve().parents[3] / "config" / "ai_profiles.rson"


@dataclass(frozen=True)
class TaskProfile:
    """Everything one task needs from a provider, and nothing about prompts."""

    task: str
    provider: str
    model: str
    max_tokens: int
    #: OMITTED from the payload unless a profile asks for one. The current
    #: Claude models reject it outright — "`temperature` is deprecated for this
    #: model", HTTP 400, measured 2026-09-29 against both configured models —
    #: so a harmless-looking default would have failed every call.
    temperature: float | None = None
    timeout_s: int = 120
    #: A ceiling this task may not exceed in one call, in input+output tokens.
    #: Advisory today — recorded on the completion so a run can be costed —
    #: and the hook a real budget hangs on later.
    budget_tokens: int = 0
    #: How hard the model should think before it answers: `"low"`, `"medium"`
    #: or `"high"`. Empty leaves the provider's default.
    #:
    #: This is not a tuning knob, it is a correctness one. Left at the default,
    #: a derivation against a 23 KB criticism spent its ENTIRE 16,384-token
    #: output budget on reasoning and returned an empty text block — which
    #: arrives as "the reply was cut off", because that is exactly what it was.
    #:
    #: Expressed as effort rather than as a token budget because that is the
    #: control the current models take: `thinking.type.enabled` with a budget
    #: is rejected outright ("use `thinking.type.adaptive` and
    #: `output_config.effort`"), measured 2026-09-30.
    effort: str = ""

    @property
    def agent_name(self) -> str:
        """How this profile identifies itself in `prov:` attribution."""
        return f"{self.provider}-{self.model}"


def load_profiles(path=None) -> dict[str, TaskProfile]:
    """`{task: TaskProfile}` from RSON.

    **No code-side default for the model**, the same rule `domain` follows
    (CE_DESIGN §13.4a): a wrong model is valid, runs, costs money and produces
    plausible output that nothing complains about. A missing profile raises.
    """
    src = Path(path or DEFAULT_PROFILES_PATH)
    if not src.exists():
        raise FileNotFoundError(
            f"no AI profiles at {src}. Every task names a profile; there is no "
            "code-side default model, because a wrong one is valid, runs, and "
            "costs money."
        )
    block = loads(src.read_text(encoding="utf-8"))
    defaults = dict(block.get("defaults") or {})
    out: dict[str, TaskProfile] = {}
    for task, spec in (block.get("tasks") or {}).items():
        merged = {**defaults, **(spec or {})}
        missing = [k for k in ("provider", "model", "max_tokens") if k not in merged]
        if missing:
            raise ValueError(f"AI profile {task!r} is missing {', '.join(missing)}")
        out[task] = TaskProfile(
            task=task,
            provider=str(merged["provider"]),
            model=str(merged["model"]),
            max_tokens=int(merged["max_tokens"]),
            temperature=(None if merged.get("temperature") is None
                         else float(merged["temperature"])),
            timeout_s=int(merged.get("timeout_s", 120)),
            budget_tokens=int(merged.get("budget_tokens", 0)),
            effort=str(merged.get("effort") or ""),
        )
    return out
