"""Reasoning effort: is it supported here, and what happens when it is not.

**The interesting half of this feature is the degradation.** Two failures are
possible when a reasoning parameter meets a model that has none, they look
nothing alike, and both are bad:

- **It raises.** `ChatOpenAI(model="gpt-4.1-mini", reasoning_effort="high")`
  constructs happily and then the *API call* rejects the parameter — a run that
  died for a setting nobody meant to make load-bearing.
- **It is silently dropped.** `ChatOllama` has no `reasoning_effort` field at
  all. Passing one raises nothing, warns nothing, and `model_dump()` does not
  contain it. Verified in this repo's own environment against
  `langchain-ollama` 1.1.0 — and Ollama is this project's zero-configuration
  default provider, so this is the *common* case, not the exotic one. A
  developer sets "high", the card says "high", and the model never hears it.

So neither "just pass it through" nor "catch the exception" is the fix. The
parameter is sent only where it is *known* to be carried, and where it is not,
the drop is stated in the run's warnings — the same "degrade loud, never
silent" rule `extensions.py` follows for tools and `runtime_warnings()` reports
for unresolved bindings.

**Capability is discovered, never listed.** CLAUDE.md forbids hand-mirroring
knowledge that has a real source, and a hardcoded set of reasoning-capable
model ids is wrong the week after it is written. There are two real sources and
they answer different questions, so both are consulted:

1. **The integration's own parameter.** `reasoning_effort` is a *standard*
   parameter in `langchain-core>=1.5.2`, declared by the partner package as a
   pydantic field whose annotation enumerates the spellings that package
   accepts — `Optional[Literal['max','xhigh','high','medium','low']]` on
   `ChatAnthropic`, absent entirely on `ChatOllama`. This answers *can this
   integration carry the value at all*.
2. **The model profile.** `model.profile["reasoning_effort_levels"]` and
   `["reasoning_effort_default"]`, powered by the models.dev dataset shipped
   and refreshed inside each partner package. This answers *does this
   particular model reason, and at which tiers*. `gpt-4.1-mini` reports
   `reasoning_output: False`; `claude-sonnet-4-6` reports
   `['low','medium','high','max']`.

Both move with the installed packages rather than with this file. A model
released tomorrow becomes selectable the moment its profile ships, and a
provider that gains the parameter needs no edit here.

**A silent profile is not a "no".** `claude-haiku-4-5` reasons but publishes no
`reasoning_effort_levels`, and an unknown model id yields an empty profile
`{}`. Treating either as "unsupported" would refuse a setting that would have
worked. So the three states are kept distinct — supported, unsupported,
unknown — and only the *middle* one refuses. Unknown falls back to what the
integration's annotation says it can carry, which is a fact rather than a
guess.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, get_args

#: The node-data key the editor writes. One spelling, shared across the
#: boundary exactly as `model` is — see `src/nodes/effortField.ts`.
REASONING_EFFORT_KEY = "reasoningEffort"

#: The constructor parameter every LangChain integration that supports this
#: spells the same way (`langchain-core>=1.5.2` standard parameter).
REASONING_EFFORT_PARAM = "reasoning_effort"


@dataclass(frozen=True)
class EffortSupport:
    """What is known about one *model instance* and reasoning effort.

    Three states, not two, and the distinction is the whole point:

    - `carries` is False — the integration has no such parameter. Certain.
    - `model_levels` is a tuple — the model publishes its tiers. Certain.
    - `model_levels` is `None` — the profile is silent or absent. *Unknown*,
      and unknown is not a refusal.
    """

    #: Spellings the integration's own field annotation accepts, or `None`
    #: when the integration declares no `reasoning_effort` field at all.
    parameter_levels: tuple[str, ...] | None

    #: Tiers this model publishes, or `None` when its profile does not say.
    model_levels: tuple[str, ...] | None

    #: The profile's `reasoning_output`, or `None` when the profile is silent.
    reasons: bool | None

    @property
    def carries(self) -> bool:
        """Can the integration transmit the parameter at all?"""
        return self.parameter_levels is not None

    @property
    def refuses(self) -> bool:
        """Does the model's own profile say it does not reason?

        Only an explicit `reasoning_output: False` counts. An absent profile
        says nothing, and nothing is not a no.
        """
        return self.reasons is False

    @property
    def accepted(self) -> tuple[str, ...]:
        """The levels a caller may choose, most specific source first.

        The model's published tiers where it has them, else whatever the
        integration's annotation says it can carry. Empty when the value
        cannot be transmitted or the model does not reason.
        """
        if not self.carries or self.refuses:
            return ()
        if self.model_levels:
            return self.model_levels
        return self.parameter_levels or ()


def _literal_levels(annotation: Any) -> tuple[str, ...]:
    """Every string in a `Literal[...]`, `Optional[...]` unwrapped.

    Walks the annotation tree rather than matching a shape, because the
    partner packages do not agree on one: `Optional[Literal[...]]` today,
    a bare `Literal[...]` or a union with `str` just as plausible tomorrow.
    A parameter typed loosely as `str | None` yields no levels, which reads
    correctly as "carries it, publishes no list".
    """
    found: list[str] = []
    for arg in get_args(annotation):
        if isinstance(arg, str):
            found.append(arg)
        else:
            found.extend(_literal_levels(arg))
    # Deduplicated, first spelling wins, order preserved — the annotation's
    # own order is the provider's documented order and worth keeping.
    return tuple(dict.fromkeys(found))


def effort_support(model: Any) -> EffortSupport:
    """Everything discoverable about `model` and reasoning effort.

    Deliberately total: an object that is not a pydantic chat model, or one
    whose `profile` access raises, reports "cannot carry it" rather than
    propagating. This runs on the path of every compiled node, and a
    capability *probe* that can take a run down is a worse defect than the
    one it exists to prevent.
    """
    fields = getattr(type(model), "model_fields", None)
    field = fields.get(REASONING_EFFORT_PARAM) if isinstance(fields, dict) else None
    parameter_levels = _literal_levels(field.annotation) if field is not None else None

    profile: Any = None
    try:
        profile = getattr(model, "profile", None)
    except Exception:  # pragma: no cover - defensive; profile is a plain attr
        profile = None
    if not isinstance(profile, dict):
        profile = {}

    raw_levels = profile.get("reasoning_effort_levels")
    model_levels = (
        tuple(str(level) for level in raw_levels)
        if isinstance(raw_levels, (list, tuple)) and raw_levels
        else None
    )
    raw_reasons = profile.get("reasoning_output")
    reasons = bool(raw_reasons) if isinstance(raw_reasons, bool) else None

    return EffortSupport(
        parameter_levels=parameter_levels,
        model_levels=model_levels,
        reasons=reasons,
    )


def _model_name(model: Any) -> str:
    """The best human name for a model instance, for a warning message."""
    for attribute in ("model", "model_name"):
        value = getattr(model, attribute, None)
        if isinstance(value, str) and value:
            return value
    return type(model).__name__


def apply_reasoning_effort(model: Any, effort: str) -> tuple[Any, str | None]:
    """`(model, warning)` — the model to run, and what was lost, if anything.

    Never raises and never returns a model carrying a value the integration
    would reject: the level is validated against the field's own annotation
    before it is set, so an editor that offers a stale tier degrades to a
    warning rather than to a pydantic error mid-run.

    `model_copy` rather than reconstruction because the caller's model is
    already built — the shared default arrives fully configured with its
    client, and rebuilding it here would mean re-deriving credentials,
    base urls and every other constructor argument this module has no
    business knowing.
    """
    wanted = str(effort or "").strip()
    if not wanted:
        # Nothing asked for. The parameter is not sent at all, so the model's
        # own documented default applies — which is not the same as sending a
        # level that happens to equal it.
        return model, None

    support = effort_support(model)
    name = _model_name(model)

    if not support.carries:
        return model, (
            f'Reasoning effort "{wanted}" was not sent: the '
            f"{type(model).__name__} integration has no {REASONING_EFFORT_PARAM} "
            f'parameter, so "{name}" ran at its own default.'
        )

    if support.refuses:
        return model, (
            f'Reasoning effort "{wanted}" was not sent: "{name}" reports no '
            "reasoning support, and the provider rejects the parameter on a "
            "model that has none. It ran without it."
        )

    accepted = support.accepted
    if accepted and wanted not in accepted:
        return model, (
            f'Reasoning effort "{wanted}" was not sent: "{name}" accepts '
            f"{', '.join(accepted)}. It ran at its own default."
        )

    try:
        return model.model_copy(update={REASONING_EFFORT_PARAM: wanted}), None
    except Exception as error:  # pragma: no cover - model_copy on a pydantic model
        return model, (
            f'Reasoning effort "{wanted}" could not be applied to "{name}" '
            f"({type(error).__name__}). It ran at its own default."
        )


__all__ = [
    "REASONING_EFFORT_KEY",
    "REASONING_EFFORT_PARAM",
    "EffortSupport",
    "apply_reasoning_effort",
    "effort_support",
]
