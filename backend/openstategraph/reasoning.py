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

**A silent profile is not a "no" — unless the provider fills that field in for
somebody else.** Until 2026-08-16 this paragraph stopped at the first clause,
and the omission was a live bug: `claude-haiku-4-5` publishes no
`reasoning_effort_levels`, so the value fell back to the annotation, was sent,
and the *API* answered `400 — This model does not support the effort
parameter`. A dead run, from the module whose stated job is that this degrades
to a warning. Reproduced on `langchain-anthropic` 1.5.4 with both
`claude-haiku-4-5` and `claude-sonnet-4-5`.

The annotation was answering a question nobody asked. `ChatAnthropic.
reasoning_effort` is declared, real, and maps to `output_config.effort` — for
the models Anthropic ships it on. Which models those are is *per model*, and
the annotation is *per class*, so no amount of reading it can tell.

The fact that does tell was already in the profile and was being read past.
`langchain-anthropic`'s own dataset fills `reasoning_effort_levels` in for
eight of its fifteen models; `langchain-openai`'s fills it in for none of
thirty-nine. So the key's absence means opposite things depending on who is
silent, and the question that separates them is one more probe:

3. **Does this integration enumerate at all?** If it publishes tiers for *any*
   model it ships, the field is populated and a model left out was left out on
   purpose — a real "no", and `effort` is not sent. If it publishes them for
   nobody, the field is simply unused there and says nothing, so the fallback
   to the annotation stands exactly as before. `gpt-5` reports the same shape
   as `claude-haiku-4-5` — reasons, no tiers — and genuinely accepts the
   parameter; this is what tells them apart.

So there are four states, not three: supported, unsupported, *excluded*, and
unknown. Only unknown falls back to the annotation.

An enumerating integration therefore refuses a model it has never heard of,
and that direction is chosen rather than conceded. A model released tomorrow
may well accept `effort`; refusing it costs one sentence in the run's
warnings, and sending it to a model that does not costs the run. The two are
not symmetric, and this module exists because of that asymmetry.

**What is deliberately *not* done here: mapping onto `thinking`.** Anthropic's
thinking models reach reasoning through `thinking={"type": "enabled",
"budget_tokens": N}`, which works on exactly the models that reject `effort`.
It is not this parameter under another name. `budget_tokens` is a *number* and
no source publishes what "high" is worth in tokens, so the mapping would be
invented here — the hand-mirrored knowledge CLAUDE.md forbids, in the module
that exists to avoid guessing. It also changes the run rather than tuning it:
the budget must fit under `max_tokens`, `temperature` is fixed while it is on,
and the response gains raw `thinking` blocks the stream would have to carry.
That is a feature — Anthropic extended thinking, configured explicitly and
surfaced in the editor — not this bug's fix. The warning names it so the
developer can reach for it.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib import import_module
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

    Four states, not two, and the distinctions are the whole point:

    - `carries` is False — the integration has no such parameter. Certain.
    - `model_levels` is a tuple — the model publishes its tiers. Certain.
    - `model_levels` is `None` and `levels_enumerated` — the integration lists
      tiers for other models and not this one. A *no*, by omission.
    - `model_levels` is `None` and not `levels_enumerated` — nobody has said.
      *Unknown*, and unknown is not a refusal.
    """

    #: Spellings the integration's own field annotation accepts, or `None`
    #: when the integration declares no `reasoning_effort` field at all.
    parameter_levels: tuple[str, ...] | None

    #: Tiers this model publishes, or `None` when its profile does not say.
    model_levels: tuple[str, ...] | None

    #: The profile's `reasoning_output`, or `None` when the profile is silent.
    reasons: bool | None

    #: Does the integration publish tiers for *any* model it ships? When it
    #: does, this model's silence is an exclusion rather than a gap.
    levels_enumerated: bool = False

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
    def excluded(self) -> bool:
        """Did the integration name the models that take this, and not ours?

        Sibling to `refuses`, and a different fact: `refuses` is the model
        saying it does not reason at all, this is the *provider* saying this
        particular model does not take the parameter. `claude-haiku-4-5`
        reasons and is excluded — which is why one flag could not carry both.
        """
        return self.levels_enumerated and not self.model_levels

    @property
    def accepted(self) -> tuple[str, ...]:
        """The levels a caller may choose, most specific source first.

        The model's published tiers where it has them, else whatever the
        integration's annotation says it can carry. Empty when the value
        cannot be transmitted, the model does not reason, or the integration
        enumerates its reasoning models and this is not one of them.
        """
        if not self.carries or self.refuses or self.excluded:
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


#: Where a partner package keeps the profile dataset it ships, and the name it
#: keeps it under. Both are private, deliberately noted as such: there is no
#: public accessor (`langchain_anthropic.data` exports nothing else), and the
#: alternative to reading it is a hardcoded list of model ids, which CLAUDE.md
#: forbids and which is wrong the week after it is written. A rename here fails
#: `test_the_premise_holds_in_the_installed_packages` rather than silently
#: restoring the 400 — the probe's own fallback is "cannot tell", which reads
#: as unknown, which sends the parameter again.
_PROFILE_DATASET_MODULE = "data._profiles"
_PROFILE_DATASET_NAME = "_PROFILES"


@lru_cache(maxsize=None)
def _integration_enumerates(root_package: str) -> bool:
    """Does this partner package publish tiers for any model it ships?

    Cached on the package name: the answer is a property of the installed
    distribution, not of a model instance, and this runs on the path of every
    compiled node.
    """
    try:
        module = import_module(f"{root_package}.{_PROFILE_DATASET_MODULE}")
    except Exception:
        # No dataset (langchain-ollama ships none), or a package that has moved
        # it. Either way nothing is known, which is not the same as "no".
        return False
    profiles = getattr(module, _PROFILE_DATASET_NAME, None)
    if not isinstance(profiles, dict):
        return False
    return any(
        isinstance(profile, dict) and profile.get("reasoning_effort_levels")
        for profile in profiles.values()
    )


def enumerates_effort_levels(model: Any) -> bool:
    """Whether this model's integration names its reasoning models by tier.

    The question that makes a silent profile readable. Answered from the
    dataset the integration ships, so it moves with the installed package: the
    day `langchain-openai` populates the field, OpenAI models are gated on it
    too, with no edit here.
    """
    return _integration_enumerates(type(model).__module__.split(".")[0])


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
        levels_enumerated=enumerates_effort_levels(model),
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

    if support.excluded:
        return model, (
            f'Reasoning effort "{wanted}" was not sent: "{name}" publishes no '
            "reasoning-effort tiers, and its provider publishes them for the "
            "models that accept the parameter — sending it would fail the "
            "request. It ran at its own default. A model that reasons without "
            "tiers is usually configured through its provider's own thinking "
            "parameter instead."
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
    "enumerates_effort_levels",
]
