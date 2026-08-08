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


def archetype_slug(text: str) -> str:
    """A worker archetype's dispatch key, from its human-readable name.

    Lowercase; alphanumerics and `_` survive; every other run of characters
    collapses to a single `-`. `_` is deliberately preserved — the router's
    port-id slug once collapsed it and silently dropped two branches' edges
    (see the map's "slug bug" entry); this slug does not repeat that.
    """
    out: list[str] = []
    for ch in text.strip().lower():
        if ch.isalnum() or ch == "_":
            out.append(ch)
        elif out and out[-1] != "-":
            out.append("-")
    return "".join(out).strip("-")


def archetype_key(node: dict) -> str:
    """The dispatch key for one worker node — its title, slugified.

    Ticket 37's resolution verbatim: the label matches the worker node's
    archetype *name* (its node title, slugified), not its id, so the planning
    prompt and the dispatch map share one string. An untitled worker falls
    back to its id — unique by construction, and irrelevant in the
    single-worker case where no labelling happens at all.
    """
    title = str(node.get("title") or "").strip()
    return archetype_slug(title) if title else str(node.get("id") or "")


class Archetype(BaseModel):
    """One wired worker kind the supervisor can dispatch to.

    `key` is the dispatch key (`archetype_key` of the worker node); `name` and
    `description` are what the planning prompt shows the model.
    """

    key: str
    name: str
    description: str = ""


class Subtask(BaseModel):
    """One unit of dispatchable work.

    `id` is stable and human-readable — it becomes part of the `Send` payload and
    the key results are joined under, so a trace can attribute a result to the
    instruction fragment that produced it without re-deriving anything.

    `archetype` is the dispatch key of the worker kind this subtask was
    labelled for. Empty means "no trusted label" — the fan-out router reads
    that as "use the default worker", so a misroute degrades to today's
    single-archetype behaviour instead of a silent wrong answer.
    """

    id: str
    instruction: str
    archetype: str = ""


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

    #: The labelling call's machinery — locked, like every output contract.
    #: The literal phrase "one archetype key per line" is load-bearing: tests
    #: (and any scripted model) recognise a labelling call by it.
    LABEL_PREAMBLE: ClassVar[str] = (
        "You are a supervisor assigning subtasks to specialist workers. For "
        "each subtask, pick the one worker archetype best suited to it."
    )

    LABEL_CONTRACT: ClassVar[str] = (
        "Reply with exactly one archetype key per line, one line per subtask, "
        "in the same order as the subtasks. Use only the keys listed above. "
        "No numbering, no explanation."
    )

    def system_prompt(self) -> SystemPrompt:
        return SystemPrompt(preamble=self.PREAMBLE, output_contract=self.OUTPUT_CONTRACT)

    def label(self, subtasks: list[Subtask], archetypes: list[Archetype]) -> list[str]:
        """One archetype key per subtask — hybrid routing (ticket 37).

        Model present: one call labels every subtask against the wired
        archetype names, and anything the call produces is **validated**
        against those keys — an invented label is not trusted and collapses
        to `""` (the default worker), because dispatching a subtask to a
        tool-less worker on the model's say-so is a silent wrong answer.

        No model: a deterministic name-mention fallback (the archetype's own
        name or key appearing in the subtask text), so the orchestrator still
        works — degraded but honest — with no model configured, the same
        stance the deterministic `split()` already takes.
        """
        if not archetypes:
            return ["" for _ in subtasks]
        if len(archetypes) == 1:
            return [archetypes[0].key for _ in subtasks]

        valid = {a.key for a in archetypes}
        # Names normalise to keys, so "Weather Worker" and `weather-worker`
        # are the same answer — one string, two spellings.
        by_name = {archetype_slug(a.name): a.key for a in archetypes}

        if self.model is None:
            labels = []
            for task in subtasks:
                # Match on the fragment itself, never the appended parent
                # context — the context names the whole request and would
                # make every fragment "mention" every archetype in it.
                text = task.instruction.split("(part of the request:")[0].lower()
                match = next(
                    (
                        a.key
                        for a in archetypes
                        if a.name.lower() in text or a.key.replace("-", " ") in text
                    ),
                    "",
                )
                labels.append(match)
            return labels

        roster = "\n".join(
            f"- {a.key}: {a.name}" + (f" — {a.description}" if a.description else "")
            for a in archetypes
        )
        listing = "\n".join(f"{i + 1}. {t.instruction}" for i, t in enumerate(subtasks))
        prompt = SystemPrompt(
            preamble=self.LABEL_PREAMBLE,
            output_contract=self.LABEL_CONTRACT,
        ).with_context(f"Worker archetypes:\n{roster}", f"Subtasks:\n{listing}")
        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            reply = self.model.invoke(
                [SystemMessage(content=prompt.render()), HumanMessage(content="Label the subtasks.")]
            )
            raw = reply.content if isinstance(reply.content, str) else str(reply.content)
        except Exception:
            # A labelling failure must not kill the plan — everything falls
            # to the default worker, which is a working (single-archetype) run.
            return ["" for _ in subtasks]

        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        labels = []
        for line in lines[: len(subtasks)]:
            candidate = archetype_slug(line.strip(" \t\"'`.,:;"))
            if candidate in valid:
                labels.append(candidate)
            else:
                labels.append(by_name.get(candidate, ""))
        # A short reply pads with the default; a long one was truncated above.
        labels.extend("" for _ in range(len(subtasks) - len(labels)))
        return labels

    def plan(
        self,
        instruction: str,
        *,
        generation: int = 0,
        archetypes: list[Archetype] | None = None,
    ) -> list[Subtask]:
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

        # Two hygiene rules, both found live (ticket 61's residual). First:
        # a conjunction split loses the shared predicate — "compare the
        # weather in Oslo and Madrid" leaves the fragment "Madrid.", and a
        # worker handed only that drifts back to whatever it saw last. A
        # fragment (short, and not the whole instruction) carries its parent
        # as explicit context. Second: near-duplicate pieces collapse to one
        # — dispatching the same work twice doubles cost and lets two answers
        # disagree.
        if len(pieces) > 1:
            pieces = [
                piece if len(piece.split()) >= 3
                else f"{piece} (part of the request: {instruction.strip()})"
                for piece in pieces
            ]
        seen: set[str] = set()
        deduped: list[str] = []
        for piece in pieces:
            key = " ".join(piece.lower().split()).rstrip(".!?")
            if key not in seen:
                seen.add(key)
                deduped.append(piece)
        pieces = deduped

        truncated = pieces[: self.max_subtasks]
        prefix = f"task-{generation}-" if generation else "task-"
        subtasks = [
            Subtask(id=f"{prefix}{i + 1}", instruction=text) for i, text in enumerate(truncated)
        ]
        if archetypes:
            labels = self.label(subtasks, archetypes)
            subtasks = [
                task.model_copy(update={"archetype": label})
                for task, label in zip(subtasks, labels)
            ]
        return subtasks


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


__all__ = [
    "Archetype",
    "BaseOrchestrator",
    "Field",
    "IOrchestrator",
    "MAX_SUBTASKS",
    "Orchestrator",
    "Subtask",
    "archetype_key",
    "archetype_slug",
]
