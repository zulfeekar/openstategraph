"""The task desk — what owns a child run that outlives the parent's turn.

`async-first/08`, and the decision is recorded in full on
`.scratch/organisms-first-class/tickets/20-do-async-subagents-belong-on-this-canvas.md`.

## The question this module exists to answer

`run_doors.py` settled the general form already: **a loop needs an owner, and a
node call is not one** (`async-first/12`). A blocking run gets one loop, owned by
the *door*, because the door is the thing whose lifetime is the run.

A child that outlives the parent's turn cannot be owned by any of those. Not the
node that launched it — gone when the node returns. Not the door — gone when the
turn ends. Not the run's loop — closed when the door closes. Its owner has to
outlive all three, and there is exactly one lifetime left in the process, with
exactly one precedent for taking it: `mcp_sessions.py` owns one daemon thread
running one event loop for the life of the process, because MCP transports must
outlive a call.

This module is that shape, for the one other thing that genuinely needs it. A
child is a **task on a desk**; the desk owns the loop, the desk outlives the
turn, and the launching tool gets a task id back.

**Deliberately not the MCP loop**, and not an ambient loop for graph code
either. `mcp_sessions` says in as many words that nothing awaits user code on
its loop, and that is a property worth keeping true — a child agent's model
calls and tool calls are user code, and putting them on the transport loop would
make one badly-behaved tool a stall for every MCP session in the process.

## What happens when the run that started it ends

Stated plainly, because it is the property that differs from the library's:

- the child keeps running. A turn ending is not a cancel;
- its answer is collected on a **later turn of the same conversation**, because
  the task ids ride `RunState.async_tasks`, which the workflow's checkpointer
  persists (`abc/async_task_middleware.py`);
- **the child dies with the process.** An in-process desk has process-lifetime
  durability and nothing more. `status()` on a task this desk never held is
  `TaskStatus.UNKNOWN` — never a guess, never `running`, because *"I have no
  record of that"* and *"it is still going"* rendering identically is the defect
  class this repository keeps closing.

## The seam

`AsyncTaskDesk` is a `Protocol` of seven members, and it is the whole seam. An
`AgentProtocolTaskDesk` — `langgraph_sdk` against a real Agent Protocol server,
which is what installed `deepagents 0.7.5`'s `AsyncSubAgentMiddleware` requires
and cannot do without `langgraph_api` present — implements the same seven and
drops in with nothing redrawn: the document does not change, the middleware does
not change, the state channel does not change, the stream frames do not change.

There is **no `Abstract`/`Base` rung** between the protocol and the concrete
desk, deliberately. The two implementations share no behaviour at all — one owns
an event loop, the other owns an HTTP client — so a common ancestor would exist
to hold nothing. Inheritance must earn itself.

## Steering, honestly

The library's `update_async_task` "interrupts and restarts a different run on
another thread". This desk does not claim that. `follow_up` **queues** a message
and the child receives it as a second turn on its own conversation once its
current turn ends. The task stays `running` while a follow-up is pending. A tool
that says *steer* and means *queue* is two situations rendering identically,
which is the one defect shape `CLAUDE.md` names twice.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable, Mapping, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

__all__ = [
    "ASYNC_TASKS_KEY",
    "ASYNC_TASKS_SLOT",
    "AsyncTaskDesk",
    "InProcessTaskDesk",
    "TaskLauncher",
    "TaskRecord",
    "TaskStatus",
    "desk_for",
    "reset_desks",
    "set_desk_for",
]


#: The state key, spelled once for both sides. `compile/state.py`'s `RunState`,
#: `compile/node_runtime.py`'s threading and `abc/async_task_middleware.py`'s
#: tools all read it from here — a literal in four files is the drift this
#: constant exists to prevent (`progress.NARRATES_ITSELF`'s argument, one seam
#: over).
ASYNC_TASKS_KEY = "async_tasks"

#: The middleware slot name. Declared in `AbstractAgentNode.SLOT_ORDER` and
#: filled by the compiler **only** when a document declared an async subagent.
#: Lives here rather than beside the middleware because `abc/agent.py` needs it
#: at class-definition time and must not import a module that pulls in
#: `langchain` to get one string.
ASYNC_TASKS_SLOT = "async-tasks"


class TaskStatus:
    """The statuses a task may report.

    A plain namespace of `str` constants rather than an `Enum`, matching the
    installed library's own reasoning at `deepagents.middleware.async_subagents`:
    the SDK types `Run.status` as `str`, so an `Enum` here would mean a `cast` at
    every boundary the Agent Protocol desk will one day cross. These are the
    library's four spellings plus one of ours.
    """

    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    CANCELLED = "cancelled"
    #: Ours, and the honest fifth: this desk has no record of the task. On an
    #: in-process desk that means the process restarted since it was started.
    UNKNOWN = "unknown"

    #: Statuses that will never change again, so a live fetch can be skipped.
    TERMINAL: frozenset[str] = frozenset({SUCCESS, ERROR, CANCELLED, UNKNOWN})


def _now() -> str:
    """ISO-8601 UTC to the second — the library's own `AsyncTask` format."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class TaskRecord:
    """One tracked child, as it rides the state channel.

    Field-for-field the installed library's `AsyncTask` TypedDict, so a document
    written against this desk needs no migration the day the Agent Protocol desk
    replaces it. `thread_id` and `task_id` are the same string there and here.
    """

    task_id: str
    agent_name: str
    status: str
    created_at: str
    last_checked_at: str
    last_updated_at: str
    #: The task's own conversation on whatever runs it. Equal to `task_id` for
    #: this desk, kept separate because a real server's need not be.
    thread_id: str = ""
    #: The current execution on that conversation. A follow-up turn is a new
    #: run on the same thread, so this moves and `thread_id` does not.
    run_id: str = ""

    def as_dict(self) -> dict[str, Any]:
        """The plain-JSON shape the state channel and the SSE frames carry."""
        return {
            "task_id": self.task_id,
            "agent_name": self.agent_name,
            "thread_id": self.thread_id or self.task_id,
            "run_id": self.run_id or self.task_id,
            "status": self.status,
            "created_at": self.created_at,
            "last_checked_at": self.last_checked_at,
            "last_updated_at": self.last_updated_at,
        }

    @classmethod
    def from_dict(cls, row: Mapping[str, Any]) -> "TaskRecord":
        """Read a row back off the state channel, tolerantly.

        The channel survives a checkpoint round trip and, one day, a document a
        different version of this code wrote. A row missing a timestamp is a row
        with no timestamp, never an exception on the path that collects an
        answer.
        """
        task_id = str(row.get("task_id") or "")
        return cls(
            task_id=task_id,
            agent_name=str(row.get("agent_name") or ""),
            status=str(row.get("status") or TaskStatus.UNKNOWN),
            created_at=str(row.get("created_at") or ""),
            last_checked_at=str(row.get("last_checked_at") or ""),
            last_updated_at=str(row.get("last_updated_at") or ""),
            thread_id=str(row.get("thread_id") or task_id),
            run_id=str(row.get("run_id") or task_id),
        )


#: What a desk is handed to actually run a child: the whole conversation so far
#: — one string per turn, the launch description first — plus the run
#: **identity** captured when the task was started, returning the child's
#: answer. Everything about *how* a child is built (which model, which tools,
#: which prompt) lives on the other side of this callable, which is what keeps
#: this module free of `deepagents`, `langchain` and the compiler.
#:
#: **Why identity and not state.** They are different channels, and
#: `compile/subagents.py` already records the distinction the same way round: a
#: subagent never sees the parent's messages or graph state, *and* the run's
#: context crosses into its tools unchanged. Without the identity a child's
#: memory-scoped tools would resolve `workflow_slug` and `thread_id` to nothing
#: — and `memory.workflow_scope_slug` says in as many words that a nameless run
#: **shares a key**. Two conversations' children writing one namespace is not
#: isolation, it is the opposite of it.
#:
#: Captured at `start` and replayed for every follow-up turn, so a task's
#: identity is the one it was launched with rather than whichever run last
#: touched the desk.
TaskLauncher = Callable[[list[str], dict[str, Any]], Awaitable[str]]


@runtime_checkable
class AsyncTaskDesk(Protocol):
    """The seam: seven members, and a second implementation redraws nothing.

    Seven is under the ten-member ceiling with room, and that is not an
    accident — the desk has one reason to change (*what holds a child run*) and
    the five tools above it are the ones with a vocabulary. `InProcessTaskDesk`
    adds two of its own (`launchers`, `shutdown`) and stops at nine.
    """

    def start(
        self,
        agent_name: str,
        description: str,
        *,
        task_id: str | None = None,
        identity: Mapping[str, str] | None = None,
    ) -> TaskRecord:
        """Launch a child and return its record immediately. Never blocks on it.

        `task_id` lets the caller name the task. `abc/async_task_middleware.py`
        passes the **tool call id**, which is what makes the `spawn` frame's
        `taskId` the same string the model will later hand to
        `check_async_task` — the stream and the state agree by construction
        rather than by a correlation somebody has to maintain.
        """

    def status(self, task_id: str) -> str:
        """The task's current status, or `TaskStatus.UNKNOWN` if it is not held."""

    def result(self, task_id: str) -> str | None:
        """The child's answer once it has succeeded, else `None`."""

    def error(self, task_id: str) -> str | None:
        """Why the child failed, if it did."""

    def follow_up(self, task_id: str, message: str) -> bool:
        """Queue a message as the child's next turn. `False` if unknown/finished."""

    def cancel(self, task_id: str) -> bool:
        """Stop the child. `False` if it is not held or already finished."""

    def tasks(self) -> list[TaskRecord]:
        """Every record this desk holds — **including other conversations'**.

        Not a per-conversation view, because a desk is not keyed by one (see
        `_DESKS`). A caller serving a single conversation must intersect this
        with the ids that conversation tracks in `ASYNC_TASKS_KEY`, or report
        nothing at all; publishing it whole is how a customer came to be told
        about a stranger's background workers.
        """


@dataclass
class _Task:
    """A desk's private bookkeeping for one child. Never leaves this module."""

    record: TaskRecord
    turns: list[str]
    answer: str | None = None
    failure: str | None = None
    pending: list[str] = field(default_factory=list)
    #: The run identity captured when this task was started — see
    #: `TaskLauncher`. Replayed on every follow-up turn.
    identity: dict[str, str] = field(default_factory=dict)
    #: The handle `run_coroutine_threadsafe` hands back, and the **only** one
    #: worth holding. An `asyncio.Task` is only available once the driver has
    #: actually started on the desk's loop, so cancelling through one lost every
    #: child that had been submitted and not yet scheduled — which is most of
    #: them, most of the time, because `start` returns immediately by design.
    #: Cancelling this future propagates into the task when there is one.
    future: concurrent.futures.Future[Any] | None = None


class _DeskLoop:
    """One daemon-thread event loop, started the first time it is needed.

    Lazily, and for the reason `mcp_sessions._McpLoop` gives: importing this
    package must not spawn a thread in a process that never launches a child —
    a CLI printing `--help`, a test collecting.
    """

    def __init__(self, name: str) -> None:
        self._name = name
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

    def loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is not None and not self._loop.is_closed():
                return self._loop
            loop = asyncio.new_event_loop()
            thread = threading.Thread(
                target=self._run, args=(loop,), name=self._name, daemon=True
            )
            thread.start()
            self._loop, self._thread = loop, thread
            return loop

    @staticmethod
    def _run(loop: asyncio.AbstractEventLoop) -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    def submit(self, coro: Any) -> concurrent.futures.Future[Any]:
        return asyncio.run_coroutine_threadsafe(coro, self.loop())

    def shutdown(self) -> None:
        with self._lock:
            loop, self._loop, self._thread = self._loop, None, None
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(loop.stop)


class InProcessTaskDesk:
    """The co-deployed desk: children run here, on a loop nobody's turn owns.

    Owner decision, derived from *"we are a compiler, not a runtime"* and the
    promise that the emitted graph *"runs anywhere Python runs"* — a second
    deployable turns that promise into "…plus this service".
    """

    def __init__(
        self,
        launchers: Mapping[str, TaskLauncher],
        *,
        loop_name: str = "openstategraph-tasks",
    ) -> None:
        #: Agent name -> how to run one of its children. **Public and
        #: rebindable**: a desk outlives the compiled graph that created it, so
        #: a recompile (a saved edit, a fresh process-local plan) has to be able
        #: to refresh *how* a child is built without discarding the children
        #: already running. `desk_for` does exactly that.
        self.launchers: dict[str, TaskLauncher] = dict(launchers)
        self._loop = _DeskLoop(loop_name)
        self._lock = threading.Lock()
        self._tasks: dict[str, _Task] = {}

    # -- the seam's seven -------------------------------------------------- #

    def start(
        self,
        agent_name: str,
        description: str,
        *,
        task_id: str | None = None,
        identity: Mapping[str, str] | None = None,
    ) -> TaskRecord:
        """Launch a child. Raises `KeyError` for an agent nobody declared.

        Refused rather than dropped: a launch that silently does nothing is a
        task id the model will poll forever, which is worse than an error
        sentence the tool can hand back on the same turn.
        """
        launcher = self.launchers[agent_name]
        task_id = (task_id or "").strip() or uuid.uuid4().hex
        now = _now()
        record = TaskRecord(
            task_id=task_id,
            agent_name=agent_name,
            status=TaskStatus.RUNNING,
            created_at=now,
            last_checked_at=now,
            last_updated_at=now,
            thread_id=task_id,
            run_id=uuid.uuid4().hex,
        )
        task = _Task(
            record=record, turns=[description], identity=dict(identity or {})
        )
        with self._lock:
            if task_id in self._tasks:
                # A caller-supplied id that is already held. Rather than clobber
                # a running child — which would lose it with no trace and leave
                # the model polling an id that now means something else — the
                # new task gets a fresh id and the record the caller receives
                # says so. Reachable in practice: a provider that reuses a tool
                # call id across turns.
                task_id = uuid.uuid4().hex
                record = replace(record, task_id=task_id, thread_id=task_id)
                task.record = record
            self._tasks[task_id] = task
        future = self._loop.submit(self._drive(task_id, launcher))
        # Nothing awaits this future for its *value*. The desk's own bookkeeping
        # is the record of what happened; the future is held so a crash inside
        # `_drive` cannot be swallowed silently, and so a child can be cancelled
        # before it has even been scheduled.
        future.add_done_callback(self._log_driver_exit)
        with self._lock:
            task.future = future
        return record

    def status(self, task_id: str) -> str:
        task = self._get(task_id)
        return task.record.status if task else TaskStatus.UNKNOWN

    def result(self, task_id: str) -> str | None:
        task = self._get(task_id)
        if task is None or task.record.status != TaskStatus.SUCCESS:
            return None
        return task.answer

    def error(self, task_id: str) -> str | None:
        task = self._get(task_id)
        return task.failure if task else None

    def follow_up(self, task_id: str, message: str) -> bool:
        """Queue a turn. Never interrupts — see this module's header."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.record.status == TaskStatus.CANCELLED:
                return False
            task.pending.append(message)
            restart = task.record.status in TaskStatus.TERMINAL
            self._touch(task, TaskStatus.RUNNING)
        if restart:
            future = self._loop.submit(
                self._drive(task_id, self.launchers[task.record.agent_name])
            )
            future.add_done_callback(self._log_driver_exit)
            with self._lock:
                task.future = future
        return True

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.record.status in TaskStatus.TERMINAL:
                return False
            future, task.pending = task.future, []
            self._touch(task, TaskStatus.CANCELLED)
        if future is not None:
            future.cancel()
        return True

    def tasks(self) -> list[TaskRecord]:
        with self._lock:
            return [task.record for task in self._tasks.values()]

    # -- lifetime ---------------------------------------------------------- #

    def shutdown(self) -> None:
        """Stop the desk's loop. Every child still running dies with it.

        Children are cancelled first rather than left to be garbage-collected
        mid-await: a task destroyed while pending is a warning nobody can act
        on, and — more to the point — it leaves the record saying `running` for
        a child that is definitively over.
        """
        with self._lock:
            live = [
                task
                for task in self._tasks.values()
                if task.record.status not in TaskStatus.TERMINAL
            ]
            for task in live:
                self._touch(task, TaskStatus.CANCELLED)
        for task in live:
            if task.future is not None:
                task.future.cancel()
        self._drain()
        self._loop.shutdown()

    def _drain(self, timeout: float = 1.0) -> None:
        """Let the loop deliver pending cancellations before it is stopped.

        `Task.cancel()` only *schedules* the `CancelledError`; stopping the loop
        in the same breath destroys the task mid-await instead. One yield on the
        desk's own loop is enough, and a timeout rather than a wait because a
        child wedged in blocking code must not make shutdown hang.
        """
        try:
            self._loop.submit(asyncio.sleep(0)).result(timeout=timeout)
        except Exception:  # noqa: BLE001 - shutdown never raises into a caller
            logger.debug("task desk drain did not complete before shutdown", exc_info=True)

    # -- private ----------------------------------------------------------- #

    def _get(self, task_id: str) -> _Task | None:
        with self._lock:
            return self._tasks.get(task_id.strip())

    def _touch(self, task: _Task, status: str) -> None:
        """Move a record's status and timestamps. Caller holds the lock."""
        now = _now()
        task.record = replace(
            task.record,
            status=status,
            last_checked_at=now,
            last_updated_at=now if task.record.status != status else task.record.last_updated_at,
        )

    async def _drive(self, task_id: str, launcher: TaskLauncher) -> None:
        """Run the child's turns until nothing is queued.

        One coroutine per task, on the desk's loop. It drains `pending` between
        turns, which is exactly what makes `follow_up` a second turn rather than
        an interruption.
        """
        while True:
            with self._lock:
                task = self._tasks.get(task_id)
                if task is None or task.record.status == TaskStatus.CANCELLED:
                    return
                # Drained here and nowhere else. A follow-up queued while the
                # child was between turns — the restart case — is picked up on
                # this pass, so `turns` is always the whole conversation before
                # a turn begins rather than after it.
                task.turns.extend(task.pending)
                task.pending = []
            try:
                answer = await launcher(list(task.turns), dict(task.identity))
            except asyncio.CancelledError:
                with self._lock:
                    if task.record.status != TaskStatus.CANCELLED:
                        self._touch(task, TaskStatus.CANCELLED)
                raise
            except Exception as exc:  # noqa: BLE001 - a child is third-party code
                logger.warning("async subagent task %s failed: %s", task_id, exc)
                with self._lock:
                    task.failure = f"{type(exc).__name__}: {exc}"
                    task.answer = None
                    self._touch(task, TaskStatus.ERROR)
                return
            with self._lock:
                if task.record.status == TaskStatus.CANCELLED:
                    return
                task.answer, task.failure = answer, None
                if not task.pending:
                    self._touch(task, TaskStatus.SUCCESS)
                    return
                self._touch(task, TaskStatus.RUNNING)

    @staticmethod
    def _log_driver_exit(future: concurrent.futures.Future[Any]) -> None:
        try:
            future.result()
        except (asyncio.CancelledError, concurrent.futures.CancelledError):
            return
        except Exception:  # noqa: BLE001 - never raised into a caller's thread
            logger.exception("async subagent task driver exited unexpectedly")


#: Every desk this process holds, keyed by whoever asked for one. **Module
#: level, and that is the whole ticket**: a desk scoped to anything narrower
#: than the process is a desk that dies with the turn, which is the thing being
#: fixed. The key is `<workflow slug>:<node id>` — stable across a recompile, so
#: a saved edit does not orphan a running child, and narrow enough that one
#: agent **node** can never reach another node's tasks.
#:
#: **It is not a conversation boundary, and it never was**
#: (`the-boundary-nobody-checked/04`). There is no thread in the key, on
#: purpose: a desk that died with the turn is the defect this registry exists
#: to fix, and a follow-up turn has to find the desk already holding its
#: running child. So two callers on one node share this desk, and every read
#: that serves *one* conversation filters by the ids that conversation tracks
#: in `ASYNC_TASKS_KEY` — which is what all five of the middleware's paths now
#: do. Until that ticket the sentence above claimed the stronger property and
#: `_announce` published `tasks()` to both audiences on the strength of it.
_DESKS: dict[str, AsyncTaskDesk] = {}
_DESKS_LOCK = threading.Lock()


def desk_for(key: str, launchers: Mapping[str, TaskLauncher]) -> AsyncTaskDesk:
    """The desk for `key`, created once per process and kept.

    A second call with the same key returns the desk that already holds the
    running children and **rebinds its launchers** — the compiled agent behind
    them may be newer than the tasks in front of them, and the newer one is the
    right thing to run the next child with.

    A desk installed by `set_desk_for` (a scripted one, or the Agent Protocol
    desk) is returned untouched: rebinding is an `InProcessTaskDesk` concern and
    nothing else's.
    """
    with _DESKS_LOCK:
        desk = _DESKS.get(key)
        if desk is None:
            desk = InProcessTaskDesk(launchers, loop_name=f"osg-tasks-{key}"[:63])
            _DESKS[key] = desk
        elif isinstance(desk, InProcessTaskDesk):
            desk.launchers = dict(launchers)
        return desk


def set_desk_for(key: str, desk: AsyncTaskDesk | None) -> AsyncTaskDesk | None:
    """Install a desk under `key`, returning the one it replaced.

    The swap point for the Agent Protocol desk, and the seam a test uses to put
    a scripted desk in front of the middleware with no loop and no model.
    """
    with _DESKS_LOCK:
        previous = _DESKS.pop(key, None)
        if desk is not None:
            _DESKS[key] = desk
    return previous


def reset_desks() -> None:
    """Shut every desk down and forget them. For tests, and for nothing else."""
    with _DESKS_LOCK:
        desks = list(_DESKS.values())
        _DESKS.clear()
    for desk in desks:
        shutdown = getattr(desk, "shutdown", None)
        if callable(shutdown):
            shutdown()
