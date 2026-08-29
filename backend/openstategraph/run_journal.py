"""One turn, written down once, by whichever door started it.

## The defect this ends

`memory-and-replay/43` landed the run store and wired it to **one** door.
`CompiledWorkflow.ask`/`.resume` published a `RunRecord` — and therefore so did
the CLI and a package's own `tests/`, which both reach the library door. The
three doors a *product* is served over published nothing:

    POST /api/runs          -> invoke_run(...)   and no row
    POST /api/runs/stream   -> astream(...)      and no row
    MCP  run_workflow       -> invoke_run(...)   and no row

So the store was populated by the door a **developer** uses and empty for the
door a **deployment** uses, which is the wrong way round for both consumers
`43` was built for: `guardrails/07` wants to bound spend in a deployment, and
`launch-readiness/99` wants patterns out of real traffic.

## Where the seam goes, and why it is not `invoke_run`

`invoke_run` is the one call all four doors already share, and it is the wrong
place. It is an **event-loop owner**: it takes a graph and a payload, drives a
coroutine to completion, and by design knows nothing about answers, audiences,
identity or clocks. Teaching it a `RunRecord` would put the store inside the
loop module and would still miss the streaming door, which never calls it —
`/api/runs/stream` drives `astream` itself. A seam that cannot cover the door
the shipped UIs actually use is not the seam.

So the seam is here, one layer up, at the thing all four doors genuinely have
in common: **a turn**. A door opens one, runs whatever it runs however it runs
it, and records the finished state. That is the `api/diagram.workflow_mermaid`
shape — one assembly, four callers — rather than four assemblies.

## What a door passes, and what it must not

A door passes only what **only it** knows: who is asking, what was asked, and
its own compile-time warnings. Everything derivable from the finished state is
derived **here**, off the same single assemblies the doors already share —
`run_health_from_state` for the health half of `warnings` and for `failed`,
`statements_executed` for what ran. That is deliberate and it is the lesson of
`every-workflow-green` 14/16 and `workflow-gallery` 49: every time a door
re-listed `run_health`'s sources locally, it fell behind them.

## Exactly one row per turn

Two mechanisms, and they answer two different double-writes.

**Within a door**, `RunTurn.record` is idempotent. The streaming door has two
terminal paths that can both be reached (`done`/`interrupt`, and the stop
handler), and the guarantee belongs in the object rather than in each door's
control flow.

**Across doors**, an open turn is held in a `ContextVar` and a turn opened
inside one is a **no-op**. This is the case `44` asked to be designed for
rather than discovered: `POST /api/runs` must not produce two rows if it ever
starts going through `ask()`, and it would, because `ask` records too. The
outer door owns the row; the inner writes nothing. Nesting is context-local,
so two concurrent runs on one server are two independent turns — the streaming
door is under exactly that load today.

A **mount** is not this case and never was: a mounted child is invoked as a
closure over the compiled child graph (`compile/composition.py`), not through
`ask`, so it opens no turn and has never written a row of its own.

## A stopped run is a row, and it is its own kind

A run the user stopped — or abandoned by closing the tab — is the most
interesting row `guardrails/07` will ever read: the provider call in flight was
issued and is billed, and Stop is precisely what a person presses when a
runaway run is costing money. Dropping it would leave that spend invisible on
the one door where it happens.

It is **not** `failed`. `RunRecord.failed` means a node wrote the failure
sentinel; a stopped run did not fail, and marking it so would corrupt every
failure rate read out of this table and would teach `99` that a truncated
answer was a bad one.

It is **not** `kind="run"` either, because it is not a finished turn: its
answer is whatever had accumulated when the reader left, and a pattern miner
that treats it as an answer is learning from half a sentence. So it is
`kind="stopped"` — which costs no existing sink anything, because that is the
whole reason `RunRecord.kind` is a tolerant string rather than a `Literal`.
"""

from __future__ import annotations

import contextvars
import logging
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Iterator, Mapping, Sequence

from openstategraph.run_sinks import RunRecord, RunSinkRegistry, now, publish

if TYPE_CHECKING:  # pragma: no cover - import cycle at runtime only
    from openstategraph.errors import StepBudgetExhausted

logger = logging.getLogger(__name__)

__all__ = [
    "RunTurn",
    "RUN_KIND",
    "STOPPED_KIND",
    "EXHAUSTED_KIND",
    "budget_exhausted",
    "run_turn",
]

#: A finished turn. The default, and what every consumer of `43` reads.
RUN_KIND = "run"

#: A turn the reader walked away from — Stop, or a closed tab. See the module
#: docstring for why it is a kind rather than a `failed` run or nothing at all.
STOPPED_KIND = "stopped"

#: A turn that spent the whole step budget and reached no answer
#: (`launch-readiness/176`). The third kind, by the same argument as the
#: second and with more force behind it: a stopped run is billed for the one
#: provider call in flight, and this one is billed for the whole budget.
#:
#: It is **not** `failed`. `RunRecord.failed` means a node wrote the failure
#: sentinel, and none did — the graph was still running perfectly well when
#: the ceiling stopped it, which is a different fact and belongs in a
#: different column, or every failure rate read out of this table starts
#: counting runaway loops as broken nodes.
#:
#: It is **not** `kind="run"` either, for `stopped`'s reason: its answer is
#: empty, and `launch-readiness/99` mining this table for patterns would be
#: learning from a blank.
EXHAUSTED_KIND = "exhausted"

#: The turn this context is inside, if any. See "Exactly one row per turn".
_open_turn: contextvars.ContextVar["RunTurn | None"] = contextvars.ContextVar(
    "openstategraph_open_run_turn", default=None
)


class RunTurn:
    """One turn in flight: its clock, its token meter, and its one row.

    Constructed by `run_turn` and never directly — the context manager is what
    binds the `ContextVar` and what enters LangChain's usage callback, and a
    turn built outside it would silently count nothing.
    """

    __slots__ = (
        "_failures",
        "_identity",
        "_question",
        "_recorded",
        "_registry",
        "_silent",
        "_started",
        "_usage",
        "_warnings",
    )

    def __init__(
        self,
        *,
        workflow_slug: str = "",
        thread_id: str = "",
        session_id: str = "",
        user_email: str = "",
        question: str = "",
        warnings: Sequence[str] = (),
        failures: Sequence[str] = (),
        registry: RunSinkRegistry | None = None,
        silent: bool = False,
    ) -> None:
        self._identity = {
            "workflow_slug": workflow_slug or "",
            "thread_id": thread_id or "",
            "session_id": session_id or "",
            "user_email": user_email or "",
        }
        self._question = question
        self._warnings = list(warnings)
        self._failures = list(failures)
        self._registry = registry
        #: A turn opened inside another one. It keeps the whole interface and
        #: writes nothing — see "Exactly one row per turn".
        self._silent = silent
        self._started = time.monotonic()
        self._usage: Any = None
        self._recorded = False

    @property
    def seconds(self) -> float:
        """How long this turn has been open. Read by `record`, and by a door
        that wants to say so itself."""
        return time.monotonic() - self._started

    def spent(self) -> dict[str, dict[str, Any]]:
        """What this turn's models reported, keyed by model.

        Readable only while the turn is open — LangChain's callback clears the
        context variable on exit — which is why `record` is called inside the
        `with` block at every door.
        """
        held = getattr(self._usage, "usage_metadata", None)
        return dict(held) if held else {}

    def record(
        self,
        state: Mapping[str, Any] | None = None,
        *,
        answer: str | None = None,
        question: str | None = None,
        warnings: Sequence[str] | None = None,
        failures: Sequence[str] | None = None,
        kind: str = RUN_KIND,
    ) -> RunRecord | None:
        """Write this turn down. **At most once, and never fatal.**

        `state` is the finished graph state — LangGraph's own returned mapping
        at a blocking door, the streaming door's folded accumulators at the
        one that has no return value. Everything a run's own state can answer
        is answered from it here, so a door cannot fall behind a health source
        by forgetting to re-list it.

        `warnings` and `failures` are the door's own compile-time halves, and
        they are accepted **here** as well as at `run_turn` because some of
        them are only true once the run is over: `runtime_warnings(runtime)`
        collects what the runtime could not resolve *while it ran*, so a door
        that handed them over before the run would record a shorter list than
        the one it returns to its caller.

        Returns the row, or `None` when this turn is nested inside another or
        has already written one. Losing a row must never lose the run that
        produced it, so a sink that refuses is `publish`'s problem and a bug
        here is logged rather than raised.
        """
        if self._silent or self._recorded:
            return None
        self._recorded = True
        try:
            if warnings is not None:
                self._warnings = list(warnings)
            if failures is not None:
                self._failures = list(failures)
            record = self._assemble(state or {}, answer, question, kind)
        except Exception as exc:  # noqa: BLE001 - a row is never worth a run
            logger.warning("A run record could not be assembled: %s", exc)
            return None
        publish(record, registry=self._registry)
        return record

    def _assemble(
        self,
        state: Mapping[str, Any],
        answer: str | None,
        question: str | None,
        kind: str,
    ) -> RunRecord:
        """The one assembly. See "What a door passes, and what it must not"."""
        from openstategraph.compile.workflow_compiler import run_health_from_state
        from openstategraph.executed_statements import statements_executed

        health = run_health_from_state(state)
        return RunRecord(
            kind=kind,
            at=now(),
            **self._identity,
            question=self._question if question is None else question,
            answer=str(state.get("answer") or "") if answer is None else answer,
            seconds=round(self.seconds, 3),
            attempts=int(state.get("attempts") or 0),
            decisions={
                str(k): str(v) for k, v in (state.get("decisions") or {}).items()
            },
            # A warning about how the workflow was *built* explains one about
            # how it ran, so the door's compile findings go first — the order
            # `RunResult.warnings` has always used, kept here so the trace file
            # and the returned result read the same way round.
            warnings=[*self._warnings, *health.failures, *health.silent],
            # Only the failure half. A silent node, a forced pass and an
            # unrouted verdict are reports about how the answer was reached,
            # never a claim the run failed.
            failed=bool(self._failures or health.failures),
            usage=self.spent(),
            # Copied from the channel that already scrubbed them, never
            # re-derived: `executed_statements` holds the rule that a
            # credential-bearing argument is not recorded at all, and a second
            # reader of `tool_use` would be a second chance to publish an
            # argument map by accident.
            statements=statements_executed(state.get("tool_use")),
        )


@contextmanager
def run_turn(
    *,
    workflow_slug: str = "",
    thread_id: str = "",
    session_id: str = "",
    user_email: str = "",
    question: str = "",
    warnings: Sequence[str] = (),
    failures: Sequence[str] = (),
    registry: RunSinkRegistry | None = None,
) -> Iterator[RunTurn]:
    """Open a turn around one run, whichever door is starting it.

    Wrap the run — not just the record — because the turn owns two things that
    have to span it: the clock, and LangChain's per-model usage callback. The
    callback's context variable is `inheritable=True`, so it reaches every
    model call the graph makes underneath, including inside an agent's ReAct
    loop and inside a mounted child, which is where a run's tokens actually go.

    A turn opened inside another is a no-op that keeps the whole interface, so
    a nested door writes nothing and the outer one owns the row.
    """
    if _open_turn.get() is not None:
        yield RunTurn(silent=True)
        return

    from langchain_core.callbacks import get_usage_metadata_callback

    turn = RunTurn(
        workflow_slug=workflow_slug,
        thread_id=thread_id,
        session_id=session_id,
        user_email=user_email,
        question=question,
        warnings=warnings,
        failures=failures,
        registry=registry,
    )
    token = _open_turn.set(turn)
    try:
        with get_usage_metadata_callback() as usage:
            turn._usage = usage
            yield turn
    finally:
        turn._usage = None
        # **Best effort, and deliberately so.** An async generator does not get
        # a context of its own (PEP 568 was never implemented), so a streaming
        # door's turn is opened and closed from whichever context ASGI happens
        # to drive the generator in — and a token reset across contexts raises
        # `ValueError`. The guard it protects is context-local by nature: a
        # context that never saw the `set` has nothing to reset, which is the
        # correct state already.
        try:
            _open_turn.reset(token)
        except ValueError:  # pragma: no cover - depends on the ASGI driver
            _open_turn.set(None)


def budget_exhausted(
    exc: BaseException,
    *,
    budget: int | None = None,
    workflow: str = "",
    state: Mapping[str, Any] | None = None,
    turn: "RunTurn | None" = None,
) -> "StepBudgetExhausted":
    """Write an overrun down on whatever turn is open, and word it in ours.

    `launch-readiness/176`, and it is deliberately **one function doing two
    things**, because the two were the same defect: a top-level overrun was
    reported in LangGraph's words *and* left no row, so the run that cost the
    most and returned nothing was both unreadable and invisible.

    Called from the two places that drive a graph — `run_doors.invoke_run`,
    which every blocking door goes through, and `api/streaming._run_frames`,
    the one door that drives `astream` itself. That is the same *one assembly,
    two callers* shape `api/diagram.workflow_mermaid` has, and it is why
    nothing else in the package may name `GraphRecursionError`
    (`tests/test_a_budget_overrun_speaks_our_words.py` walks the modules).

    **Why the row is written here rather than by each door.** `44` put the
    seam at `run_turn` and not at `invoke_run` because a driver has no business
    assembling a `RunRecord` — that argument still holds, and this is the shape
    that respects it: the assembly stays in this module, and the driver calls
    one function. The turn is found on the `ContextVar` rather than passed,
    because the driver genuinely does not have it and the variable exists for
    exactly this — a nested turn is silent, so a run reached through `ask()`
    inside `POST /api/runs` still writes one row, the outer door's. A caller
    that *does* hold the turn passes it: the streaming door's fold is handed
    one as an argument, and looking up a variable when a reference is in scope
    is a chance to find the wrong one.

    It also covers the **mount** boundary's own `StepBudgetExhausted`, which
    has been worded since `organisms-first-class` 60 and has never left a row
    either. An error that is already ours keeps its sentence — the mount case
    is a different event with a different thing to say — and only gains the
    row.

    Returns the error rather than raising it, so the caller writes
    `raise budget_exhausted(...) from exc` and the vendor's traceback is kept
    as the cause.
    """
    from openstategraph.errors import StepBudgetExhausted
    from openstategraph.step_budget import step_budget_exhausted_message

    open_turn = turn if turn is not None else _open_turn.get()
    if open_turn is not None:
        open_turn.record(state or {}, kind=EXHAUSTED_KIND)
    if isinstance(exc, StepBudgetExhausted):
        return exc
    return StepBudgetExhausted(step_budget_exhausted_message(budget, workflow=workflow))
