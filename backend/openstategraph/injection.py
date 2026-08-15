"""Prompt-injection screening, as an optional extra that names its own cost.

Guardrails ticket 04. The Guardrail node handles **shapes**: `email`,
`credit_card` with its Luhn checksum, `ip`, `mac_address`, `url`. Every one
of those is a pattern, and none of them is a judgement. Nothing in it detects
an injected instruction, and the docs must not imply otherwise.

The middleware that does is `BastionGuardrailMiddleware`, from
`bastion-prompt-protection`. Three things make adopting it a decision rather
than a default, and all three were read off the published wheel rather than
recalled:

1. **It is AGPL-3.0-or-later**, and its commercial weights are gated on the
   Hugging Face Hub. That is a licence position an adopter takes
   deliberately, in their own deployment, or does not take at all. It is the
   single strongest reason this is never in `[all]`.
2. **It is a local model.** `onnxruntime`, `huggingface-hub`, `numpy` and
   `tokenizers` arrive with it, in a product whose install proof currently
   fits in a clean venv and whose dependency floor is four packages.
3. **It runs inside the agent.** Screening happens in `before_model`, which
   fires for the user's turn *and* after tools return — so it covers
   indirect injection carried in a fetched page, which is where the
   dangerous case actually arrives. No node at the edges of the canvas can
   reach that, however visible we make it.

`docs/decisions/injection-screening.md` is the record.

## The shape, and why it is this one

This is the `ProviderSpec.readiness()` pattern (workflow-gallery ticket 38)
applied to a second wall: a **value** describing what is missing, one
sentence naming the exact command, and never a traceback for a condition we
detected ourselves. It is not a `ProviderSpec` — that type is about vendors
of models and carries credentials and endpoints this has none of — but it
answers the same question the same way, deliberately.

## Where a workflow asks for it

`document.settings.injectionScreening`, a **workflow** setting, compiled to
graph assembly — the same place `retry_policy`, the checkpointer and the
memory settings live. Not a node field, because the thing it protects is
inside every agent's loop; not a per-agent checkbox, because that is the
duplication the Guardrail node exists to abolish.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import Any, Mapping

#: The PyPI distribution. `pip install` says this.
DISTRIBUTION = "bastion-prompt-protection"

#: The importable module. `import` says this, and the two differ — which is
#: exactly why `ProviderSpec` declares `integration_module` rather than
#: deriving it from `extra`.
MODULE = "bastion_prompt_protection"

#: The extra in `backend/pyproject.toml`. Never in `[all]`; see the module
#: docstring, and `test_injection_screening.py` asserts it.
EXTRA = "bastion"

#: The middleware slot this fills. **First** in `AbstractAgentNode.SLOT_ORDER`,
#: because `before_*` hooks run first to last and screening that ran after
#: another middleware had already acted on the injected text would be
#: screening after the fact.
SLOT = "injection-screening"

#: The document setting that turns it on.
SETTING = "injectionScreening"


@dataclass(frozen=True)
class ScreeningGap:
    """Why a workflow that asked for screening is not getting it.

    A value, not an exception, for the reason `ProviderGap` is one: this
    module is the catalogue and knows the *copy*; whether an unscreened run
    should proceed is the compiler's call, and it proceeds — refusing to run
    a workflow because an optional extra is absent would turn a missing
    dependency into an outage.
    """

    @property
    def message(self) -> str:
        """One line, naming the consequence first and then the fix.

        The consequence leads because it is the part a developer can act on
        *now*: the run went ahead without screening. "Import failed" describes
        our machinery; "this ran unscreened" describes their system.
        """
        return (
            "This workflow asked for prompt-injection screening and ran without it — "
            f"the {DISTRIBUTION} integration is not installed "
            f"(pip install 'openstategraph[{EXTRA}]')."
        )


def is_installed() -> bool:
    """Whether the screening package is importable.

    `find_spec`, not `import_module`, for the reason `ProviderSpec.is_installed`
    gives: importing it drags in `onnxruntime` and loads a model, which would
    undo the lean core the extra exists to protect.
    """
    try:
        return importlib.util.find_spec(MODULE) is not None
    except (ImportError, ValueError):  # pragma: no cover - a broken install
        return False


def readiness() -> ScreeningGap | None:
    """What stands between this machine and screening, or `None`."""
    return None if is_installed() else ScreeningGap()


def requested(settings: Mapping[str, Any] | None) -> bool:
    """Whether a document asked for screening.

    Absent means no. Screening is never on by default: it is a licence
    position and a local model, and neither is something to acquire on a
    developer's behalf.
    """
    if not settings:
        return False
    return bool(settings.get(SETTING))


def middleware() -> Any:
    """The screening middleware instance, constructed with library defaults.

    Every parameter is left alone deliberately. `check_input` and
    `check_tool_results` both default to `True`, which is the configuration
    the indirect-injection case needs, and `exit_behavior="end"` ends the run
    with the library's own violation message rather than raising — the same
    errors-are-data posture the rest of this compiler takes. Surfacing
    `preset` or `threshold` as a workflow setting would be exposing a knob we
    have no evidence for calibrating.
    """
    from bastion_prompt_protection.integrations.langchain import (  # type: ignore[import-not-found]
        BastionGuardrailMiddleware,
    )

    return BastionGuardrailMiddleware()


def contribution(*, requested: bool) -> tuple[dict[str, Any], ScreeningGap | None]:
    """The named slot to merge, and the gap to report — either may be empty.

    Returns `({}, None)` when nothing was asked for, so the overwhelmingly
    common case is silent: a warning on every run of every workflow is one
    nobody reads (`compile/diagnostics.py` states the rule).
    """
    if not requested:
        return {}, None
    gap = readiness()
    if gap is not None:
        return {}, gap
    return {SLOT: middleware()}, None


__all__ = [
    "DISTRIBUTION",
    "EXTRA",
    "MODULE",
    "SETTING",
    "SLOT",
    "ScreeningGap",
    "contribution",
    "is_installed",
    "middleware",
    "readiness",
    "requested",
]
