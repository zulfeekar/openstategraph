"""The orchestrator ladder: ``IOrchestrator`` → ``BaseOrchestrator`` → ``Orchestrator``.

This is the **graph-engineering** half of the pattern documented in
`.scratch/fullstack-langgraph/decisions/loop-graph-harness.md`. An orchestrator's
job is narrow and mechanical: turn one instruction into a **bounded list of named
subtasks**. It does not run them — that is a graph concern (`Send` fan-out to a
declared worker node, ticket 27) — and it does not judge the results — that is the
grader's job. One reason to change: how an instruction becomes subtasks.

Same shape as Router and Grader, for the same reason: the mechanics (bounding the
count, giving every subtask an id, falling back to a single subtask rather than
zero) are not domain knowledge, so they are declared once on the base.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from dyflow.abc.prompt import SystemPrompt

#: A runaway split (a numbered list with 500 items, say) must not fan out to 500
#: subagents. Bounding here is cheaper and more reliable than trusting the
#: instruction author or a model to self-limit.
MAX_SUBTASKS = 8


class Subtask(BaseModel):
    """One unit of dispatchable work.

    `id` is stable and human-readable — it becomes part of the `Send` payload and
    the key results are joined under, so a trace can attribute a result to the
    instruction fragment that produced it without re-deriving anything.
    """

    id: str
    instruction: str


@runtime_checkable
class IOrchestrator(Protocol):
    """The contract consumers depend on."""

    def plan(self, instruction: str) -> list[Subtask]: ...


class BaseOrchestrator(ABC):
    """Shared bounding and fallback behaviour, declared once.

    Subclasses supply `split(instruction)` — how an instruction decomposes — and
    inherit the bounding, the id assignment and the empty-instruction fallback.
    """

    PREAMBLE: ClassVar[str] = (
        "You are an orchestrator. Your only job is to split one instruction into "
        "independent subtasks that can run in parallel. You never do the work "
        "yourself."
    )

    OUTPUT_CONTRACT: ClassVar[str] = (
        "Reply with one subtask per line, each a complete, self-contained "
        "instruction. No numbering, no preamble, no explanation."
    )

    def __init__(self, *, max_subtasks: int = MAX_SUBTASKS, model: Any = None) -> None:
        self.max_subtasks = max_subtasks
        self.model = model

    @abstractmethod
    def split(self, instruction: str) -> list[str]:
        """Turns one instruction into raw subtask strings. The extension point."""

    def system_prompt(self) -> SystemPrompt:
        return SystemPrompt(preamble=self.PREAMBLE, output_contract=self.OUTPUT_CONTRACT)

    def plan(self, instruction: str, *, generation: int = 0) -> list[Subtask]:
        """Splits, bounds, and ids. Subclasses should not need to override this.

        `generation` is folded into every id so that **replanning never reuses
        an id from an earlier attempt**. Found by running a real revise loop:
        every call starts numbering at `task-1`, so a second orchestrator pass
        after a rejection produces `task-1`/`task-2` again — silently aliasing
        onto whatever the *rejected* attempt's results were keyed under in the
        shared `worker_results` dict, blending stale and fresh work under one
        key. The caller (the orchestrator node) passes its own attempt count;
        this class has no notion of "which attempt" on its own.
        """
        pieces = [p.strip() for p in self.split(instruction) if p.strip()]
        # Never zero subtasks: an instruction that does not split is still one
        # unit of work, not a dead end.
        if not pieces:
            pieces = [instruction.strip()] if instruction.strip() else []
        if not pieces:
            return []

        truncated = pieces[: self.max_subtasks]
        prefix = f"task-{generation}-" if generation else "task-"
        return [Subtask(id=f"{prefix}{i + 1}", instruction=text) for i, text in enumerate(truncated)]


class Orchestrator(BaseOrchestrator):
    """The default: deterministic decomposition, no model required.

    Splits on explicit separators an instruction author would naturally use —
    numbered lists, semicolons, or literal "and" — rather than asking a model to
    decide, which is both cheaper and reproducible. This mirrors the checklist's
    own guidance: "keep control model-driven only where a rule cannot express the
    decision," and decomposing a punctuated list is exactly a rule's job.

    A model-driven subclass is a legitimate extension (override `split` to call
    `self.model`), and gets the bounding and fallback for free.
    """

    #: Ordered so a numbered list is tried before falling back to conjunctions —
    #: "1. X and Y" should split into two numbered items, not further on "and".
    _NUMBERED = re.compile(r"(?:^|\n)\s*\d+[.)]\s*")
    _SEMICOLON = re.compile(r"\s*;\s*")
    _AND = re.compile(r"\s+and\s+", re.IGNORECASE)

    def split(self, instruction: str) -> list[str]:
        if self._NUMBERED.search(instruction):
            return [p for p in self._NUMBERED.split(instruction) if p.strip()]
        if ";" in instruction:
            return self._SEMICOLON.split(instruction)
        if self._AND.search(instruction):
            return self._AND.split(instruction)
        return [instruction]


__all__ = ["BaseOrchestrator", "Field", "IOrchestrator", "MAX_SUBTASKS", "Orchestrator", "Subtask"]
