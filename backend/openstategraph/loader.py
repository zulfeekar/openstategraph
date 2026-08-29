"""The one public entry point for running a workflow package you own.

**Why this exists.** OpenStateGraph is a compiler, so the artifact a developer
commits is a package folder — `workflow.json` plus `tools/`, `functions/`,
`middlewares/`, `skills/`, `knowledge/`. Compiling that document is two lines;
compiling it *with the package's own capabilities wired* is six, and the
difference between them is invisible at run time. Verified live: a package
loaded with a bare ``NodeRuntime(model=...)`` compiles, runs, and answers —
while ``unresolved_tools`` holds every tool the agent was drawn with and the
agent replies "we need to call chinook_list_tables" instead of querying
anything. That is the parametric-answer failure this codebase treats as the
worst kind, reached by following the documented snippet.

So the assembly `WorkflowServices` already owns for HTTP and MCP is exposed
here as **one function** with the package directory as its only required
argument. A consumer passes exactly what they have — a folder — and gets back
a small value object: the compiled graph (the full escape hatch), the
capabilities that could not be resolved, a Mermaid rendering, and one
convenience for asking a question.

**Import cost is part of the contract.** Nothing here imports LangGraph,
LangChain or FastAPI at module scope, so ``import openstategraph`` stays cheap
and side-effect free; the runtime arrives on the first ``load_workflow`` call.
A consumer running a graph in-process never touches the web layer at all.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from openstategraph.compile.run_context import validate_run_context
from openstategraph.errors import InvalidPackageName, PackageNotFound, ThreadNotResumable
from openstategraph.executed_statements import statements_executed
from openstategraph.results import RunResult
from openstategraph.run_doors import RunLoop, invoke_run
from openstategraph.schema import normalize_document
from openstategraph.step_budget import DEFAULT_STEP_BUDGET, resolve_step_budget

if TYPE_CHECKING:
    # TYPE_CHECKING, not a plain import: `import openstategraph` must stay
    # cheap — the runtime arrives on the first `load_workflow()` call, and a
    # subprocess test plus `scripts/clean_install_proof.sh` both assert that
    # langgraph and langchain_core are absent from `sys.modules` until then.
    # `from __future__ import annotations` above makes every annotation a
    # string, so these names are never evaluated at run time.
    from langchain_core.tools import BaseTool
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from langgraph.store.base import BaseStore

logger = logging.getLogger(__name__)

#: Supersteps, not iterations — see CLAUDE.md. Matches the editor's own
#: default so a workflow behaves the same run from a script as from the canvas.
#: Re-exported from `step_budget`, which is where the resolution lives now
#: that a document's own `settings.recursionLimit` is consulted first; the
#: name is kept because scripts import it from here.
DEFAULT_RECURSION_LIMIT = DEFAULT_STEP_BUDGET

#: The verdicts a `human.approval` gate can carry, and the whole set of them.
#: There is no `edit`: a person may approve, or reject with words, and never
#: hand back corrected text (`organisms-first-class` 27).
_DECISIONS = frozenset({"approve", "reject"})


def _interrupt_payload(final: dict[str, Any]) -> dict[str, Any] | None:
    """The pause a finished `invoke` came back carrying, or `None`.

    LangGraph puts pending `Interrupt` objects on the returned state under
    `__interrupt__`. Read tolerantly and trusted narrowly, the way this project
    reads every reply it did not write: a payload is taken as a mapping when it
    is one, and anything else is rendered as the message it evidently is
    rather than raised over.
    """
    pending = final.get("__interrupt__") or ()
    for interrupt in pending if isinstance(pending, (list, tuple)) else (pending,):
        value = getattr(interrupt, "value", interrupt)
        return dict(value) if isinstance(value, dict) else {"message": str(value)}
    return None



@dataclass(frozen=True)
class CompiledWorkflow:
    """One loaded package, ready to run.

    Deliberately small: `graph` is the escape hatch (a plain compiled
    LangGraph object — stream it, checkpoint it, mount it in your own service),
    and everything else here is the convenience that makes the common case one
    line. Nothing wraps LangGraph's own surface, because wrapping it would be
    the beginning of the execution engine this project refuses to write.
    """

    #: The compiled LangGraph `StateGraph`. Everything LangGraph can do, you
    #: can do — `.stream()`, `.astream_events()`, `.get_state()`, `.invoke()`.
    graph: Any
    #: Capabilities the package names but this process could not resolve —
    #: a bound tool with no implementation, a `function.*` with no callable, a
    #: subgraph whose workflow is missing. Empty is the healthy case; anything
    #: here means the graph will run and answer *less well than it looks*.
    warnings: list[str] = field(default_factory=list)
    #: The package's identity, derived from the directory name.
    slug: str = ""
    package_dir: Path = Path()
    #: The vendor-neutral document that was compiled, envelope already peeled.
    document: dict[str, Any] = field(default_factory=dict)
    #: Where `ask()` appends one JSON line per run, or None for no trace.
    #: Set through `load_workflow(..., trace_file=...)`; see `_append_trace`
    #: for exactly what is written and — more importantly — what is not.
    trace_file: Path | None = None

    #: The subset of `warnings` that is a claim this run came out **less
    #: capable**, and therefore the only part that may reach an exit code.
    #: Everything on `warnings` and not here is a *report* about the document —
    #: today, an agent whose authored rules deny the tools it holds, which is a
    #: stale sentence in a graph that runs correctly (ticket 89). Empty is not
    #: the same as `warnings` being empty, and `cli.run_report_lines` derives
    #: `error:` versus `warning:` from exactly this distinction.
    failure_warnings: list[str] = field(default_factory=list)
    #: What `load_workflow` opened on this object's behalf and must therefore
    #: release: the `WorkflowServices` (checkpointer + memory store) and, when
    #: the document asked for `settings.checkpointer: "sqlite"`, that
    #: workflow's own saver. Underscored and excluded from `repr`/equality
    #: because it is bookkeeping, not part of what a loaded workflow *is* —
    #: but it is a field rather than a closure so the dataclass stays frozen
    #: and comparable. A checkpointer the *caller* passed is never in here.
    _owned: tuple[Any, ...] = field(default=(), repr=False, compare=False)
    #: Graph node name -> the mounted child compiled under it, as the
    #: compiler recorded it. Read by `mermaid`, which draws it, and by
    #: `composition_step_budget`, which prices it. Underscored and out of
    #: `repr`/equality for the same reason `_owned` is: it is bookkeeping,
    #: not part of what a loaded workflow *is*.
    _mounts: Mapping[str, Any] = field(
        default_factory=dict, repr=False, compare=False
    )
    #: The loop every run through this object is driven on, and the fix for
    #: `launch-readiness/171`. **It is here because the model is here**: the
    #: provider client is built once by `load_workflow` and held for this
    #: object's whole life, and a client's pooled sockets belong to the loop
    #: that opened them. A loop that died with each run left the second `ask`
    #: reaching a closed one — `RuntimeError: Event loop is closed`, on every
    #: second call, silently. `run_doors.py` carries the rule and the table of
    #: which door owns what. Lazy: the thread starts on the first run, so a
    #: workflow that is loaded and never asked costs nothing.
    _loop: RunLoop = field(default_factory=RunLoop, repr=False, compare=False)

    def close(self) -> None:
        """Release the sqlite handles this load opened. Idempotent.

        Only needed by a process that loads workflows repeatedly — a script
        that loads one and exits has never had a problem, which is exactly why
        the leak survived: langgraph's sqlite saver and store have no
        `close()`, so one file descriptor per `load_workflow` accumulated
        invisibly in the long-lived transports.

        After this, `graph` and `ask()` are no longer usable. Use the context
        manager form when the scope is obvious:

            with load_workflow("workflows/billing") as billing:
                print(billing.ask("How much did we invoice in March?"))
        """
        from openstategraph.memory import close_resource

        # Before the handles, because stopping the loop is what makes it true
        # that nothing else is still running against them.
        self._loop.close()
        for resource in self._owned:
            closer = getattr(resource, "close", None)
            if callable(closer):
                closer()
            else:
                close_resource(resource)

    def __enter__(self) -> "CompiledWorkflow":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    def mermaid(self, *, xray: bool = True) -> str:
        """The compiled topology as Mermaid **text**, with no network call.

        `xray=True` **opens every mount**, to any depth: `nested-mounts` draws
        as three nested `subgraph` blocks with the innermost workflow's own
        agents inside them. `xray=False` draws what LangGraph itself holds —
        one box per mount — which is the honest picture of the topology handed
        to the runtime, and is what you want when a mount is the suspect.

        **LangGraph's own `xray` is not what does this, and cannot be.** It
        expands a LangGraph subgraph; a mount is a *closure* over the child's
        `invoke()`, and a function is opaque. So the expansion is ours, from
        what the compiler recorded while it built the child —
        `compile/composition.py` carries the argument, including why the child
        is not made into a real subgraph instead. An agent is likewise a
        closure and stays one box: it has no second document to show.

        (Until `workflow-gallery` 28 this docstring said the flag "changes
        nothing", which was true of LangGraph and read as a statement about
        the preview. Before 2026-08-16 it said the opposite and was simply
        wrong. Two corrections of one sentence is why the behaviour is now
        pinned in `backend/tests/test_mount_composition_preview.py` rather
        than described here.)

        Never `draw_mermaid_png()`: that posts the graph to a third-party API.
        """
        drawable = self.graph.get_graph(xray=xray)
        if xray and self._mounts:
            from openstategraph.compile.composition import expand_mounts

            drawable = expand_mounts(drawable, self._mounts)
        diagram: str = drawable.draw_mermaid()
        return diagram

    def composition_step_budget(self, recursion_limit: int | None = None) -> int:
        """The most supersteps this workflow **and everything it mounts** may
        spend — a ceiling known before the run, not a measurement after it.

        `ask()`'s `recursion_limit` bounds **one graph**. A mount is one
        isolated step of that graph and a separate `invoke` with a counter of
        its own, so a composition of seven graphs given 60 may spend up to
        seven sixties. That is the number this returns.

        It is not the unbounded thing the phrasing suggests, and
        `step_budget.composition_step_budget` carries the measurement:
        depth on its own costs nothing, the cost tracks the number of mount
        *instances in the expansion*, and that expansion is finite at build
        time because every child is compiled eagerly and a mount cycle is
        refused there. So there is a worst case and it can be quoted.

        Pass a number to price a run you have not started; pass nothing to
        price the run this document would take on its own, resolved exactly as
        `ask()` resolves it.

            with load_workflow("workflows/desk") as desk:
                print(desk.composition_step_budget())   # e.g. 420, not 60

        Reporting rather than preventing is the whole answer to
        `organisms-first-class` 63, and the two preventions it rejects — one
        shared decrementing allowance, and a depth-scaled ceiling — are priced
        at that function.
        """
        from openstategraph.step_budget import composition_step_budget

        return composition_step_budget(
            resolve_step_budget(recursion_limit, self.document), self._mounts
        )

    def ask(
        self,
        question: str,
        *,
        thread_id: str | None = None,
        user_email: str | None = None,
        session_id: str | None = None,
        recursion_limit: int | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> RunResult:
        """Run the graph once and return its answer.

        The return value **is** the answer string — `RunResult` subclasses
        `str`, so everything that worked when this returned a bare `str` still
        works — with the rest of the run attached: `.decisions`, `.outputs`,
        `.warnings`, `.attempts`. Those are what you need when the answer is
        wrong, and reaching them used to mean dropping to `.graph.invoke()`
        with hand-seeded state, which is the ceremony this function replaces.

        **Raises `RunProducedNothing` when the run produced no answer and
        something went wrong.** It never used to, and that was
        `launch-readiness/171`'s worse half: a run whose only answering node
        died came back as a `RunResult` that *is* an empty string, so the
        published example above printed a blank line and the reason sat on
        `.warnings` where nobody was looking. Both halves are required — a
        legally empty answer still returns, and so does a run paused at a gate
        — and the whole `RunResult` rides on the error's `.result`, so nothing
        a caller could have read is lost by the raise.

        The initial state is not arbitrary — `attempts`/`decisions`/`outputs`
        must be seeded or a grader loop reads `None` where it expects a
        counter. Getting that wrong is silent, so it is done here rather than
        printed in a snippet for everyone to copy.

        `thread_id` names a conversation for the checkpointer: omit it and
        every call is independent; pass the same string twice and the second
        call continues the first. Use `.graph` directly for streaming,
        multi-key results, or an interrupted human-approval resume.

        `user_email` is **who this run is for**, and it is what scopes
        per-person long-term memory. Omit it and user-scoped memory does not
        bind at all — `save_memory(scope="user")` says so rather than writing
        into a namespace shared with everyone else who did not identify
        (memory ticket 01). Over HTTP this value is the server's to determine
        and a client may not send it; here **you are** the server, so it is
        yours to supply. `session_id` scopes thread listing only.

        Both use the same names as `RunRequest`, so one vocabulary describes
        identity whichever way a run is started.

        `context` is the other half, and the opposite by construction: **who
        the run is for** is `configurable` and the server's to decide, while
        **what the workflow asked its caller for** is `settings.context`, the
        author's to declare and yours to fill. A plain dict, never a Python
        type — the compiler mints the dataclass and the mapping is coerced into
        it, so nothing here imports an artefact of a build. It is validated
        against this document's own declaration before the graph is invoked, so
        a key it does not declare, one it requires and you omitted, or a value
        of the wrong declared type is a `RunContextError` naming the key and
        the workflow rather than a `TypeError` from inside the graph naming a
        class you never wrote (`organisms-first-class` 70).

        `workflow_slug` needs no argument: this object knows its own slug and
        now passes it, which is what scopes workflow memory and stamps the
        provenance of an app-scope deposit. Before this it was dropped, so
        every workflow in a process shared `("workflow-memory", "unsaved")`.
        """
        thread = thread_id or f"load-workflow-{uuid.uuid4().hex}"
        # Before anything is built or spent, and before `invoke` can raise the
        # library's own message from inside the graph.
        run_context = validate_run_context(self.document, context, slug=self.slug)
        config = {
            "recursion_limit": resolve_step_budget(recursion_limit, self.document),
            "configurable": {
                "thread_id": thread,
                "user_email": user_email or "",
                "session_id": session_id or "",
                "workflow_slug": self.slug or "",
            },
        }

        from langchain_core.callbacks import get_usage_metadata_callback

        started = time.monotonic()
        # **What the run cost, counted by LangChain rather than by us**
        # (`workflow-gallery` 35). `get_usage_metadata_callback` aggregates
        # `AIMessage.usage_metadata` per model, in-process, with no tracer and
        # no account — so the answer to "what did that cost" stops being
        # "attach LangSmith" for a run happening on this machine.
        #
        # `CLAUDE.md` says token accounting stays deliberately **not** unified
        # — middleware for agents, callbacks elsewhere — "because unifying them
        # would invent an abstraction LangGraph does not have". This is on the
        # permitted side of that line and deliberately so: it is the library's
        # own callback, wrapped around the one `invoke()` this door already
        # makes. Nothing is declared on a base class, no node knows about it,
        # and no family carries a capability it does not use. The forbidden
        # move would be an accounting layer of ours that agents and tools both
        # inherit; this adds no layer at all.
        #
        # The context variable is `inheritable=True`, so it reaches every model
        # call the graph makes underneath — including inside an agent's ReAct
        # loop and inside a mounted child, which is where a run's tokens
        # actually go.
        with get_usage_metadata_callback() as usage:
            # `None` means *pass no argument at all*, which is what every run
            # against a workflow declaring no context has always done.
            extra = {"context": run_context} if run_context is not None else {}
            final = invoke_run(
                self.graph,
                {"question": question, "attempts": 0, "decisions": {}, "outputs": {}},
                config,
                loop=self._loop,
                **extra,
            )
            # Read inside the block: the manager clears the variable on exit.
            spent = dict(usage.usage_metadata)
        result = self._result(final, spent, thread)
        self._append_trace(question, result, time.monotonic() - started)
        return self._answered(result)

    def pause(self, thread_id: str) -> dict[str, Any] | None:
        """What a paused thread is waiting to be told — or `None` if it is not
        waiting at all.

        The payload is the node's own: `{"message", "candidate"}`, the sentence
        the gate asks and the text a person is being asked to stand behind. It
        is a **view**, like `threads show`: reading a pause resumes nothing.

        Raises for a thread this workflow cannot speak for at all — see
        `_thread_state`. A stored thread that simply finished is not an error:
        it returns `None`, because "is this waiting on me" is a fair question
        to ask of any thread.
        """
        state = self._thread_state(thread_id)
        for task in state.tasks or ():
            for interrupt in getattr(task, "interrupts", ()) or ():
                value = getattr(interrupt, "value", None)
                payload = dict(value) if isinstance(value, dict) else {"message": str(value)}
                chain = self._paused_mount(thread_id)
                if chain:
                    payload["mount"] = chain
                return payload
        return None

    def _paused_mount(self, thread_id: str) -> list[dict[str, str]]:
        """Which mounted workflow this pause is waiting inside, top-down.

        `organisms-first-class` 64. The gate's own sentence says *what* is
        being asked and has since `07ffbc3`; what it could not say is that the
        question comes from a package the top document merely mounts — and a
        reviewer answering `approval-in-the-loop` a day later has no other way
        to find out which document to read.

        Asked of the checkpointer rather than of the graph, because
        `get_state(subgraphs=True)` cannot answer for a mount at all (the
        measurement, and the docs sentence behind it, are in
        `compile/paused_mount.py`). A workflow with no mounts asks the saver
        nothing, so every document without one costs exactly what it did.
        """
        from openstategraph.compile.paused_mount import paused_mount_chain

        if not self._mounts:
            return []
        return paused_mount_chain(
            getattr(self.graph, "checkpointer", None), thread_id, self._mounts
        )

    def resume(
        self,
        thread_id: str,
        *,
        decision: str,
        feedback: str | None = None,
        user_email: str | None = None,
        session_id: str | None = None,
        recursion_limit: int | None = None,
    ) -> RunResult:
        """Answer a `human.approval` gate and let the rest of the run happen.

        `ask()`'s sibling, and the half that was missing: `ask()` starts a
        conversation, this one finishes the turn a person was asked to close.
        Both return a `RunResult`, because a resumed run is not a different
        kind of thing from the run it continues — it is the same run, picking
        back up, which is the argument `POST /api/runs/resume` already makes
        about reusing one event vocabulary.

        `decision` is `"approve"` or `"reject"`, and there is deliberately no
        default: a decision nobody gave is the one thing this seam must never
        invent. `feedback` rides along with a rejection and is what the drafter
        treats as the specification for its next attempt; `_human_approval`
        reads it only when the decision is a rejection, so passing it with an
        approval is a caller error rather than a value silently dropped.

        There is no `edit` outcome, deliberately — a person may approve, or
        reject with words, and never hand back corrected text
        (`organisms-first-class` 27).

        **This executes.** The rest of the graph runs against a durable
        checkpoint, tools and all, and the pause is consumed: a thread cannot
        be resumed twice. Callers with a person in front of them should say so
        first — `openstategraph resume` does.
        """
        if decision not in _DECISIONS:
            raise ValueError(
                f"decision must be one of {', '.join(sorted(_DECISIONS))} — "
                f"{decision!r} is not a verdict this gate can carry"
            )
        if feedback and decision == "approve":
            raise ValueError(
                "feedback belongs to a rejection — an approval carries no note, "
                "and one passed here would be dropped rather than read"
            )
        if self.pause(thread_id) is None:
            raise ThreadNotResumable(
                f"thread {thread_id!r} is not paused — there is nothing waiting "
                "for a decision. `threads list` reports which threads are"
            )

        from langgraph.types import Command

        from langchain_core.callbacks import get_usage_metadata_callback

        started = time.monotonic()
        resume_value: dict[str, Any] = {"decision": decision}
        if feedback:
            resume_value["feedback"] = feedback
        config = self._config(thread_id, user_email, session_id, recursion_limit)
        with get_usage_metadata_callback() as usage:
            final = invoke_run(
                self.graph, Command(resume=resume_value), config, loop=self._loop
            )
            spent = dict(usage.usage_metadata)
        result = self._result(final, spent, thread_id)
        self._append_trace(f"resume:{decision}", result, time.monotonic() - started)
        return self._answered(result)

    def _config(
        self,
        thread_id: str,
        user_email: str | None = None,
        session_id: str | None = None,
        recursion_limit: int | None = None,
    ) -> dict[str, Any]:
        """The one config both doors build. Identity is the whole point of it:
        a resume that named the thread and forgot the slug would continue the
        right run in the wrong memory namespace."""
        return {
            "recursion_limit": resolve_step_budget(recursion_limit, self.document),
            "configurable": {
                "thread_id": thread_id,
                "user_email": user_email or "",
                "session_id": session_id or "",
                "workflow_slug": self.slug or "",
            },
        }

    def _thread_state(self, thread_id: str) -> Any:
        """The checkpointer's snapshot of one thread, or a refusal naming why.

        Two refusals, and both are about *this* workflow's right to speak for
        the thread rather than about how the run went:

        - **Nothing stored.** A checkpointer with no record of the id is a
          typo, a different state directory, or a run that never happened.
        - **Another package's thread.** The saver is shared across a project,
          so a thread is perfectly *findable* from the wrong package — and
          resuming it there would run this document against a checkpoint some
          other document wrote. `workflow_slug` has ridden in every
          checkpoint's metadata since threads were listable, so the mismatch
          is answerable rather than merely suspected.
        """
        state = self.graph.get_state(self._config(thread_id))
        if state.created_at is None:
            raise ThreadNotResumable(
                f"no stored run for thread {thread_id!r} — `threads list` shows "
                "which threads this checkpointer holds"
            )
        stored = str((state.metadata or {}).get("workflow_slug") or "")
        if stored and self.slug and stored != self.slug:
            raise ThreadNotResumable(
                f"thread {thread_id!r} belongs to {stored!r}, not to {self.slug!r} "
                "— resume it against the package that started it"
            )
        return state

    def _result(
        self, final: dict[str, Any], spent: dict[str, Any], thread_id: str | None = None
    ) -> RunResult:
        """One finished `invoke` as a `RunResult` — the assembly `ask` and
        `resume` share, so a run cannot report its health differently
        depending on which door started it."""
        from openstategraph.compile.workflow_compiler import run_health_from_state

        outputs = final.get("outputs") or {}
        # The third door onto `run_health`, and the one that had been reading
        # a third of it (`workflow-gallery` 49). Derived from the assembly
        # rather than re-listed here: this door fell behind three times, once
        # per source added to `run_health`, and each time by re-listing.
        health = run_health_from_state(final)
        return RunResult(
            str(final.get("answer") or ""),
            decisions=final.get("decisions") or {},
            outputs=outputs,
            # A warning about how the workflow was *built* explains one about
            # how it ran, so compile findings go first; a claim the run failed
            # goes before a report about how the answer was reached.
            warnings=[*self.warnings, *health.failures, *health.silent],
            # Only the failure half — a silent node, a forced pass and an
            # unrouted verdict must never reach an exit code. A compile
            # finding does: a mount that could not be loaded leaves no marker
            # in `outputs` and is still a broken run (`production-ready` 53).
            failures=[*self.failure_warnings, *health.failures],
            attempts=int(final.get("attempts") or 0),
            # What this run executed (`one-chinook-honest` 30). The same read
            # both HTTP doors make, off the same `tool_use`: a run must not be
            # able to say what it did over one door and not another.
            statements=statements_executed(final.get("tool_use")),
            # Empty when no model reported — which is *unknown*, not free.
            # See `RunResult.usage`; nothing here fabricates a zero.
            usage=spent,
            # **A pause is not an answer, and this is where the two stop
            # looking alike** (`workflow-gallery` 24). LangGraph puts the
            # pending `Interrupt` on the returned state under `__interrupt__`;
            # without reading it, a run stopped at a gate came back with an
            # empty answer, no warnings and every appearance of success.
            pause=self._with_mount(_interrupt_payload(final), thread_id),
        )

    def _answered(self, result: RunResult) -> RunResult:
        """`result`, unless the run produced nothing and something went wrong.

        **The one shape that must never be returned** (`launch-readiness/171`).
        Before this, a run whose only answering node died came back as a
        `RunResult` that *is* an empty string, with the reason on `.warnings` —
        so the README's own headline example printed a blank line and said
        nothing at all. The cause that made it happen every second call is
        fixed in `run_doors.py`; this is here so that whatever the *next* cause
        turns out to be, the symptom cannot come back.

        The predicate is `results.produced_nothing`, which is the rule
        `cli.run_exit_code` has gated on since `workflow-gallery` 53 rather
        than a second one invented here — an exit code and a raise disagreeing
        about what a failed run is would be the same defect one surface along.
        A legally empty answer still returns, and so does a paused run.

        Raised **after** `_append_trace`, deliberately: a failed run is the one
        most worth having in the trace file.
        """
        from openstategraph.errors import RunProducedNothing
        from openstategraph.results import produced_nothing

        if produced_nothing(result):
            raise RunProducedNothing.of(result)
        return result

    def _with_mount(
        self, payload: dict[str, Any] | None, thread_id: str | None
    ) -> dict[str, Any] | None:
        """The same mount chain `pause()` reports, on the pause a *run* returns.

        Derived here rather than restated, so the two doors onto one pause
        cannot disagree — `run` prints `RunResult.pause` and `resume` prints
        `pause()`, and a reviewer reading one and then the other must not be
        told two different things about where the gate is
        (`organisms-first-class` 64).
        """
        if not payload or thread_id is None:
            return payload
        chain = self._paused_mount(thread_id)
        if chain:
            payload["mount"] = chain
        return payload

    def _append_trace(self, question: str, result: RunResult, seconds: float) -> None:
        """One JSON line per run, appended to `trace_file`. Never fatal.

        **A file sink, not a tracing framework.** LangSmith and OpenTelemetry
        exist; this is the thing you attach to a support ticket, and inventing
        a span model to compete with them would be inventing an abstraction we
        do not have.

        **The answer text is deliberately not written — only its length.** A
        trace file gets committed, emailed and pasted into issues, and an
        answer is the one field in a run that reliably contains a customer's
        data. `decisions` and `attempts` are what tell you *which way the graph
        went*, which is what a wrong answer is diagnosed from; the answer
        itself you already have in front of you.

        A path that cannot be written **warns and returns**. A trace is
        diagnostics: losing it must never lose the run that produced it.
        """
        if self.trace_file is None:
            return
        line = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "slug": self.slug,
            "question": question,
            "decisions": result.decisions,
            "attempts": result.attempts,
            "warnings": result.warnings,
            "seconds": round(seconds, 3),
            "answer_chars": len(result),
            # Tokens, per model — the one number a support ticket about a
            # slow or expensive run always wants and never had. Safe to write
            # where the answer is not: a count carries no customer data.
            "usage": result.usage,
        }
        try:
            self.trace_file.parent.mkdir(parents=True, exist_ok=True)
            with self.trace_file.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(line) + "\n")
        except OSError as exc:
            logger.warning("Could not write the run trace to %s: %s", self.trace_file, exc)

    def as_tool(self, *, name: str | None = None, description: str | None = None) -> BaseTool:
        """This whole workflow, as one LangChain tool your existing agent can call.

        For the team already on `create_agent` who does not want to restructure:

            from langchain.agents import create_agent

            billing = load_workflow("workflows/billing").as_tool(
                name="billing_analyst",
                description="Answers questions about invoices and revenue.",
            )
            agent = create_agent(model, tools=[billing, ...])

        **Adapted at the seam, never subclassed** — the same rule and the same
        `StructuredTool.from_function` shape `abc/tool.py` uses, so an upstream
        change to LangChain's tool internals cannot reach into us.

        **Isolation, stated plainly, because it is the part people get wrong.**
        The workflow runs as its own graph. It sees the question string and
        nothing else — not the calling agent's message history, not its state,
        not its tools — and it returns its answer text as the tool's result.
        That is exactly the subagent rule this codebase already states
        (CLAUDE.md, "State flows down; subagents do not receive it"): a
        subagent is invoked as a tool, gets a task, and reports a result. If
        the caller needs the workflow to know something, it has to be in the
        question.

        Each call runs on its own thread id, so two calls never continue each
        other's conversation. Use `.ask(thread_id=...)` directly if you want
        one that does.

        There is deliberately **no middleware equivalent**. Middleware would
        have to decide *when* to consult the workflow, which is a routing
        policy — and a router is something this framework already expresses as
        a document (`route.classifier`). Shipping a second, worse one inside
        the library would be the duplicated-knowledge defect CLAUDE.md names.
        """
        from pydantic import BaseModel, Field

        from langchain_core.tools import StructuredTool

        class _Question(BaseModel):
            model_config = {"extra": "forbid"}
            question: str = Field(description="The question to ask this workflow.")

        def _call(question: str) -> str:
            return str(self.ask(question))

        tool_name = name or re.sub(r"[^a-zA-Z0-9_]+", "_", self.slug or "workflow").strip("_")
        return StructuredTool.from_function(
            func=_call,
            name=tool_name or "workflow",
            description=description or self._default_tool_description(),
            args_schema=_Question,
        )

    def _default_tool_description(self) -> str:
        """A description from the document, so the tool is usable un-configured.

        Named `description=` is still the right answer — the calling model
        picks tools by this text — but a missing one must not produce a tool
        the model cannot tell apart from any other.
        """
        title = str(self.document.get("name") or self.slug or "workflow")
        return f"Ask the {title!r} OpenStateGraph workflow a question and get its answer."


def _warnings_with_node_failures(
    warnings: Sequence[str], outputs: Mapping[str, Any]
) -> list[str]:
    """Compile findings, then the steps that broke — the **failure** half.

    Superseded as the library door's report by `run_health_from_state`, which
    carries all four sources rather than this one (`workflow-gallery` 49).
    Kept because this is exactly `RunResult.failures` for a caller that holds
    outputs and no state, and because deleting a name three tests and the
    ticket record all cite would lose the chain back.
    """
    from openstategraph.compile.workflow_compiler import node_failure_warnings

    return [*warnings, *node_failure_warnings(outputs)]


def load_workflow(
    package_dir: str | Path,
    *,
    model: Any = None,
    # Named rather than `Any`: these have one published base class each, and
    # the failure mode of the wrong object is a stack trace inside LangGraph
    # that mentions no code of ours.
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    store: BaseStore | None = None,
    tools: dict[str, Any] | None = None,
    functions: dict[str, Any] | None = None,
    middleware: dict[str, Any] | None = None,
    knowledge_dir: str | Path | None = None,
    trace_file: str | Path | None = None,
) -> CompiledWorkflow:
    """Compile the workflow package at `package_dir`, capabilities and all.

    `package_dir` is the folder holding `workflow.json`. Both things the
    runtime needs are derived from it — the workflows **root** is its parent
    and the **slug** is its own name — so a consumer passes the one path they
    actually have rather than restating it twice.

    `model` accepts either a LangChain model string (`"anthropic:claude-..."`,
    `"ollama:gpt-oss:120b-cloud"`), resolved through the *same* path the HTTP
    API uses so behaviour is identical, or an already-built LangChain model
    object, which is passed through untouched. `None` means: the document's own
    `settings.model` if it names one, otherwise the environment default
    (`ANTHROPIC_API_KEY` → Claude, `OPENAI_API_KEY` → GPT, else Ollama
    **cloud**). A node that names its own model still overrides all of this.

    `checkpointer` is optional, and durable by default. Threads land in
    `<workflows root>/.openstategraph/checkpoints.sqlite` — the workflows root
    being this package's parent — so a `human.approval` pause and an
    `ask(thread_id=...)` conversation both outlive the process. A package's own
    `settings.checkpointer: "sqlite"` still takes its own per-workflow file;
    `OPENSTATEGRAPH_CHECKPOINT_PATH` moves the default or, set to `memory`,
    opts out of durability entirely. Pass your own — a Postgres saver, say —
    to own durability, which outranks all of the above.

    `store` is the long-term memory `Store` — the collaborator the prebuilt
    `save_memory`/`search_memory` tools read and write, namespaced per user.
    `None` keeps the environment-driven default (in-process, or sqlite when
    `OPENSTATEGRAPH_MEMORY_PATH` is set). Pass a LangGraph `BaseStore` —
    Postgres, Redis, your own — to own memory durability the same way
    `checkpointer` lets you own thread durability. The two are siblings and
    are meant to be supplied together: owning half of persistence is how a
    deployment ends up with durable conversations and evaporating memories.

    `tools` and `functions` are explicit capability mappings —
    `{"tool.my-thing": instance}` and `{"function.my_fn": callable}` — keyed
    exactly as a document names them. `middleware` is the same idea for the
    slot table (`{"summarization": middleware_object}`), keyed by slot name
    as `middlewares/<slot>.py` is.

    **Precedence: built-in < installed plugin < the package's own files <
    these arguments.** An explicit mapping is the most specific source there
    is, so it outranks every discovered one. The filesystem describes what a
    package *shipped*; an argument describes what *this process* is to run,
    and only the caller knows which is right — a vendored package, a package
    on a read-only mount, a test that needs one tool stubbed and the rest
    real. The reverse order would make substitution impossible: a package
    could veto the host application. A collision with a discovered capability
    is therefore **not** reported on `.warnings`; it is a deliberate
    substitution, and warning about it would train adopters to ignore the one
    list that means "this run lost a capability".

    `knowledge_dir` overrides where the package's second brain is read from.
    The default stays the **convention** — `<package>/knowledge` — because
    discovery-by-convention is why this function takes one argument. The
    override is for the cases convention cannot express: knowledge shared
    between two packages, knowledge that lives outside the repository, or a
    test pointing at a fixture directory. It names the directory that *holds
    the `<topic>.md` files*, not the package above it.

    `trace_file` appends one JSON line per `ask()` — question, slug,
    decisions, attempts, warnings, duration and the answer's **length**, never
    the answer text (see `CompiledWorkflow._append_trace` for why). A path
    that cannot be written warns; it never fails a run.

    **Unresolved capabilities never raise.** They land on `.warnings` and log
    one WARNING line naming them, because the alternative failure mode is a
    workflow that answers confidently without the tools it was drawn with.
    """
    directory = Path(package_dir).expanduser().resolve()
    manifest = directory / "workflow.json"
    if not manifest.is_file():
        raise PackageNotFound(f"no workflow.json in {directory} — is that a workflow package?")

    # Lazy, all of it: this is where a consumer opts into the runtime.
    from openstategraph.api.model_resolution import resolve_model, workflow_default_model
    from openstategraph.api.registries import runtime_failure_warnings, runtime_warnings
    from openstategraph.api.services import WorkflowServices
    from openstategraph.api.workflow_store import slugify
    from openstategraph.compile.node_runtime import RunState
    from openstategraph.compile.workflow_compiler import WorkflowCompiler

    slug = directory.name
    if slug != slugify(slug):
        # The slug is the package's frozen identity and is what scopes tool,
        # function, skill and knowledge discovery. A directory the store
        # cannot address would silently discover nothing — the exact silent
        # degradation this function exists to prevent — so say it instead.
        raise InvalidPackageName(
            f"workflow package directory {slug!r} is not a valid slug; "
            f"rename it to {slugify(slug)!r} (lowercase letters, digits and hyphens)"
        )

    document = normalize_document(json.loads(manifest.read_text()))

    # One assembly point, shared with HTTP and MCP: the caller's collaborators
    # go in here rather than into a second wiring path beside it.
    services = WorkflowServices(
        directory.parent,
        # The public parameter is `store=` and stays that way — it is in
        # `public_api.txt`, so renaming it would break an adopter's call. The
        # *internal* keyword says which store it is (ticket 12).
        memory_store=store,
        checkpointer=checkpointer,
        tools=tools,
        functions=functions,
        middleware=middleware,
    )
    resolved_model = model
    if model is None or isinstance(model, str):
        from openstategraph.chat_model import build_chat_model

        # The credential gate, the endpoint and the extras hint all live in
        # `chat_model`. They used to live here, which meant the HTTP, MCP and
        # per-node paths called `init_chat_model` directly and got the vendor
        # SDK's error instead of ours.
        resolved_model = build_chat_model(
            resolve_model(model or workflow_default_model(document))
        )

    compiler = WorkflowCompiler()
    plan = compiler.plan(document)
    knowledge_override = Path(knowledge_dir).expanduser().resolve() if knowledge_dir else None
    # A capability that failed to load — a half-installed plugin distribution
    # (ticket 05), a tool class left abstract (ticket 07) — is a capability
    # this run does not have, so it belongs on `.warnings` beside every other
    # one, not only in a log line the consumer's service will never show them.
    # It arrives through `runtime_warnings(runtime)` below: `runtime_for` hangs
    # the findings on the runtime itself, so every transport reports them and
    # this one no longer needs its own sink (passing one as well would report
    # each finding twice).
    runtime = services.runtime_for(
        slug,
        document,
        resolved_model,
        knowledge_dir=knowledge_override,
    )

    # The services were built here, so their two sqlite handles are this
    # workflow's to close (see `CompiledWorkflow.close`).
    owned: list[Any] = [services]
    if checkpointer is None:
        # The same seam the HTTP and MCP transports use, and the same default:
        # `services.checkpointer` is durable (a sqlite file under the workflows
        # root) unless the environment opts out. Before ticket 05 this was a
        # fresh `InMemorySaver` per call, which meant a `human.approval` pause
        # could not be resumed by a second process — or even by a second
        # `load_workflow` in the same one.
        checkpointer = services.checkpointer_for(document.get("settings"), slug)
        # A per-workflow `settings.checkpointer: "sqlite"` file is opened and
        # owned by the services object itself, so nothing extra to track here.

    graph = compiler.build(
        document,
        RunState,
        runtime.factory(document),
        checkpointer=checkpointer,
        store=services.memory_store,
    )

    warnings = list(plan.warnings) + runtime_warnings(runtime)
    # The half of that list a failed run may be blamed on. `plan.warnings` is
    # whole-document and has no report-only kind; the split is the runtime's.
    failure_warnings = list(plan.warnings) + runtime_failure_warnings(runtime)
    if warnings:
        # Degrade loud, never silent — the same rule the run endpoints follow.
        logger.warning(
            "Workflow %r loaded with %d unresolved capability warning(s): %s",
            slug,
            len(warnings),
            " | ".join(warnings),
        )

    return CompiledWorkflow(
        graph=graph,
        warnings=warnings,
        failure_warnings=failure_warnings,
        slug=slug,
        package_dir=directory,
        document=document,
        trace_file=Path(trace_file).expanduser() if trace_file else None,
        _owned=tuple(owned),
        _mounts=dict(runtime.mounted_graphs),
    )


__all__ = ["CompiledWorkflow", "DEFAULT_RECURSION_LIMIT", "RunResult", "load_workflow"]
