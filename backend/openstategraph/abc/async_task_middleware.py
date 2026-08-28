"""The five tools an agent gets when — and only when — it declares an async worker.

`async-first/08`. The decision this implements is recorded in full on
`.scratch/organisms-first-class/tickets/20-do-async-subagents-belong-on-this-canvas.md`;
what a child *runs on* is `openstategraph/async_tasks.py`. This module is the
vocabulary in between: `start_async_task`, `check_async_task`,
`update_async_task`, `cancel_async_task`, `list_async_tasks`, and the state
channel their ids ride.

## The shape is the library's; the mechanism is ours, and here is why

`AsyncSubAgentMiddleware` **does exist** in installed `deepagents 0.7.5` — 921
lines of it, exported from `deepagents.__init__`. It was not usable here, and
the reason is one import. Every one of its five tools goes through
`langgraph_sdk.get_client` / `get_sync_client`, and `url=None` — the
"co-deployed, ASGI transport" case the ticket originally quoted — does **not**
mean *in this process*. Reading the installed `langgraph_sdk/_async/client.py`,
it means `from langgraph_api.server import app`: inside a running LangGraph
Platform API server. `langgraph_api` is not installed here, and installing it is
the second deployable *"we are a compiler, not a runtime"* rules out.

So the library's middleware is adopted as a **shape, not as a dependency**: the
same five tool names, the same `async_tasks` channel, the same `AsyncTask`
record fields, the same prompt discipline about not polling immediately. The day
an Agent Protocol desk is built, `AsyncSubAgentMiddleware` becomes reachable
again and nothing above this line has to move.

## Opt-in, never universal

CLAUDE.md: *"narrow interfaces … so a node opts into being a tool without
carrying unused methods"*, and *"inherit the capability to compose; do not
inherit the composition"*. An agent that declares no `async` subagent row
carries none of these five tools and no `async_tasks` channel. The compiler
fills the `async-tasks` slot only when a document asked for it, exactly as it
fills `injection-screening` only when a workflow asked for injection screening.

## The channel, and why it is not an invention

The library puts task metadata outside message history because *"deep agents
compact their message history when the context window fills up; if task IDs were
only in tool messages they would be lost during compaction."* That is
CLAUDE.md's named-reducer rule found from the other direction, so the channel is
kept and reduced by `Reducer.MERGE` — an **existing** member of the named enum,
not a new one, because `merge_decisions` is `{**left, **right}`, which is
precisely the library's own `_tasks_reducer`.

It rides `RunState.async_tasks` too, keyed by node id, threaded by
`compile/node_runtime.py` exactly the way `agent_files` is (commit `f02bf34`).
That is what makes a task id survive to the turn that collects the answer: the
agent's own state is thrown away when its node returns, and `RunState` is what
the workflow's checkpointer persists.

## What the stream is told

The owner's explicit requirement is that the stream say what is happening and
the current status of each async subagent — on the rails that exist
(`spawn` frames, narration `progress`), never a new channel. Two rails, and
they answer two different questions:

- **`spawn`** answers *a task began*. `api/streaming.py`'s `SpawnWatcher` reads
  the `start_async_task` tool call off the agent's own model frame, the same way
  it reads `task`, and emits `kind: "async"` carrying the task id.
- **`progress`** answers *and here is where each one stands now*. This
  middleware reports the live roster before every model call — deterministically,
  out of the desk, with no model involved — so a reader watching a long turn
  sees `researcher · running` become `researcher · finished` without the agent
  having to be asked.

**A spawned task is not a canvas node**, and `140`'s `ThinkingStack` renders by
`activeNode`. So attribution is by ownership: both frames are attributed to the
**agent node that launched the task** — `spawn.parent` and the `progress`
frame's `activeNode`, which resolves that way for free because the tool runs
inside that node's namespace. The task's own identity travels as `taskId`,
which is what `canvas-feels-right/07` will draw with.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Literal, NotRequired, Sequence, cast

from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langchain.tools import ToolRuntime
from langchain_core.messages import ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.types import Command
from pydantic import BaseModel, Field

from openstategraph.async_tasks import (
    ASYNC_TASKS_KEY,
    ASYNC_TASKS_SLOT,
    AsyncTaskDesk,
    TaskRecord,
    TaskStatus,
)
from openstategraph.compile.reducers import Reducer, reducer_for
from openstategraph.progress import report_progress
from openstategraph.run_identity import run_identity

logger = logging.getLogger(__name__)

__all__ = [
    "ASYNC_TASKS_KEY",
    "ASYNC_TASKS_SLOT",
    "AsyncTaskMiddleware",
    "AsyncTaskState",
    "async_task_status_line",
]

# `ASYNC_TASKS_KEY` and `ASYNC_TASKS_SLOT` are re-exported from
# `openstategraph.async_tasks`, which owns them: `abc/agent.py` needs the slot
# name at class-definition time and must not import this module — and therefore
# `langchain` — to get one string.


class AsyncTaskState(AgentState):
    """The agent-loop state extension: task metadata outside the messages.

    `Reducer.MERGE` rather than a bare field, because `check` and `list` can
    both write this key and CLAUDE.md's rule is that a key more than one writer
    can reach needs a **named** reducer.
    """

    async_tasks: Annotated[NotRequired[dict[str, Any]], reducer_for(Reducer.MERGE)]


class _StartSchema(BaseModel):
    description: str = Field(
        description="A detailed, self-contained description of the task. The worker "
        "sees this and nothing else about your conversation."
    )
    subagent_type: str = Field(
        description="Which async worker to use. Must be one of the types listed above."
    )


class _TaskIdSchema(BaseModel):
    task_id: str = Field(
        description="The exact task_id string returned by start_async_task. Pass it verbatim."
    )


class _UpdateSchema(_TaskIdSchema):
    message: str = Field(description="Follow-up instructions or context for the worker.")


class _ListSchema(BaseModel):
    status_filter: (
        Literal["running", "success", "error", "cancelled", "unknown", "all"] | None
    ) = Field(
        default=None,
        description="Narrow the list to one status. Defaults to all of them.",
    )


#: The launch tool's description. The usage notes are the library's own, kept
#: verbatim in substance because they patch the failure modes the ticket was
#: sceptical about — *supervisor polls immediately after launch*, *supervisor
#: reports a stale status*. The scepticism was right and the answer to it is
#: prompt discipline, so the discipline is not paraphrased away.
_START_DESCRIPTION = """Start a background worker. It runs on its own and this tool returns a task id immediately, without waiting for it.

Available workers:
{workers}

Usage notes:
1. This launches a background task and returns straight away. Report the task id and carry on — do NOT check its status in the same breath.
2. Use `check_async_task` when the answer is actually wanted.
3. Use `update_async_task` to send a worker further instructions. They are delivered as its next turn once its current one ends, not mid-thought.
4. Several workers can run at once — launch them and let them run.
5. A worker never sees this conversation. Everything it needs goes in `description`.
6. A task outlives this turn: you can start one now and collect it in a later message."""


def async_task_status_line(records: Sequence[TaskRecord]) -> str:
    """One deterministic sentence naming every task and where it stands.

    Deterministic on purpose, and it is the same argument `launch-readiness/143`
    settled for narration: a model asked to summarise its own progress once
    leaked its scratchpad into a customer answer. This sentence is assembled
    from the desk's own records and no model sees it before a reader does.
    """
    if not records:
        return ""
    parts = [f"{record.agent_name} {record.status}" for record in records]
    return "Background workers: " + ", ".join(parts)


class AsyncTaskMiddleware(AgentMiddleware):
    """The `async-tasks` slot: five tools, one channel, one desk.

    Not a subclass of anything in `deepagents` and not a subclass of
    `NarrationMiddleware` either — a slot is a *contribution*, and this shares
    no behaviour with the others in the table.
    """

    state_schema = AsyncTaskState

    def __init__(
        self,
        *,
        subagents: Sequence[dict[str, Any]],
        desk: AsyncTaskDesk | None = None,
        desk_factory: Callable[[], AsyncTaskDesk] | None = None,
        system_prompt: str | None = None,
    ) -> None:
        """Exactly one of `desk` and `desk_factory`.

        **Why a factory at all.** The desk is keyed by workflow *and* node so
        that one agent can never read another's tasks — and the workflow slug is
        a fact about the **run**, read from `run_identity()`, not about the
        compile. A desk resolved at construction would key every document
        compiled in this process under the same name. So the compiler passes a
        factory that resolves at call time; a test passes a scripted desk.
        """
        super().__init__()
        if not subagents:
            raise ValueError(
                "AsyncTaskMiddleware needs at least one async subagent — the slot is "
                "opt-in, so an agent that declares none must not carry it at all."
            )
        if (desk is None) == (desk_factory is None):
            raise ValueError("AsyncTaskMiddleware takes exactly one of desk, desk_factory")
        resolved: AsyncTaskDesk | None = desk
        self._desk_factory: Callable[[], AsyncTaskDesk] = (
            desk_factory if desk_factory is not None else (lambda: cast(AsyncTaskDesk, resolved))
        )
        self._workers = {str(row["name"]): row for row in subagents}
        roster = "\n".join(
            f"- {name}: {row.get('description', '')}" for name, row in self._workers.items()
        )
        self.system_prompt = system_prompt
        self.tools = [
            self._start_tool(_START_DESCRIPTION.format(workers=roster)),
            self._check_tool(),
            self._update_tool(),
            self._cancel_tool(),
            self._list_tool(),
        ]

    def _desk(self) -> AsyncTaskDesk:
        """The desk this run's tasks live on, resolved every time it is asked.

        Every time, not memoised: a desk resolved once would outlive the run it
        was resolved for, and the whole registry exists to key desks by a fact
        the run supplies.
        """
        return self._desk_factory()

    # -- the roster, said out loud before every model call ------------------ #

    def wrap_model_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        self._announce()
        return handler(request)

    async def awrap_model_call(
        self, request: Any, handler: Callable[[Any], Awaitable[Any]]
    ) -> Any:
        self._announce()
        return await handler(request)

    def _announce(self) -> None:
        """Report the live roster on the `progress` rail. Never fails a run."""
        line = async_task_status_line(self._desk().tasks())
        if line:
            report_progress(line)

    # -- the five ---------------------------------------------------------- #

    def _start_tool(self, description: str) -> StructuredTool:
        def start_async_task(description: str, subagent_type: str, runtime: ToolRuntime) -> Any:
            if subagent_type not in self._workers:
                allowed = ", ".join(f"`{name}`" for name in self._workers)
                return (
                    f"Unknown async worker `{subagent_type}`. Available: {allowed}. "
                    "Nothing was started."
                )
            try:
                # The tool call id becomes the task id: see `AsyncTaskDesk.start`.
                # It is what lets `SpawnWatcher` announce the launch off the
                # model frame — immediately, before the tool has even returned —
                # carrying the very string the model will poll with.
                record = self._desk().start(
                    subagent_type,
                    description,
                    task_id=str(getattr(runtime, "tool_call_id", "") or ""),
                    # Captured here, inside the run, because the desk's loop is
                    # outside every run context and `run_identity()` answers
                    # `{}` there. Identity is a third channel — not messages,
                    # not graph state — and `compile/subagents.py` records the
                    # same distinction for the blocking subagent one door over.
                    identity=run_identity(),
                )
            except Exception as exc:  # noqa: BLE001 - a desk is a seam, not a promise
                logger.warning("could not launch async worker %s: %s", subagent_type, exc)
                return f"Could not launch `{subagent_type}`: {exc}. Nothing was started."
            return self._command(
                f"Started `{subagent_type}` in the background. task_id: {record.task_id}",
                record,
                runtime,
            )

        return StructuredTool.from_function(
            name="start_async_task",
            func=start_async_task,
            description=description,
            infer_schema=False,
            args_schema=_StartSchema,
        )

    def _check_tool(self) -> StructuredTool:
        def check_async_task(task_id: str, runtime: ToolRuntime) -> Any:
            tracked = self._tracked(task_id, runtime)
            if isinstance(tracked, str):
                return tracked
            status = self._desk().status(tracked.task_id)
            result: dict[str, Any] = {"status": status, "task_id": tracked.task_id}
            if status == TaskStatus.SUCCESS:
                result["result"] = self._desk().result(tracked.task_id) or (
                    "(finished with no output)"
                )
            elif status == TaskStatus.ERROR:
                result["error"] = self._desk().error(tracked.task_id) or "The worker failed."
            elif status == TaskStatus.UNKNOWN:
                # The honest fifth status. *No record of it* and *still going*
                # rendering identically is the defect class this repository
                # keeps closing, so the sentence says which one this is.
                result["error"] = (
                    "This task is no longer held. Background workers run in the server "
                    "process, so a restart ends them. Start it again if the answer is "
                    "still wanted."
                )
            return self._command(json.dumps(result), self._touched(tracked, status), runtime)

        return StructuredTool.from_function(
            name="check_async_task",
            func=check_async_task,
            description=(
                "Check one background task. Returns its current status and, once it has "
                "finished, its answer. A status you were told earlier is always stale."
            ),
            infer_schema=False,
            args_schema=_TaskIdSchema,
        )

    def _update_tool(self) -> StructuredTool:
        def update_async_task(task_id: str, message: str, runtime: ToolRuntime) -> Any:
            tracked = self._tracked(task_id, runtime)
            if isinstance(tracked, str):
                return tracked
            if not self._desk().follow_up(tracked.task_id, message):
                return (
                    f"Could not pass that on: task {tracked.task_id} is not running and "
                    "cannot be given more work. Start a new one instead."
                )
            return self._command(
                f"Queued for `{tracked.agent_name}`. It will read this as its next turn, "
                "once the turn it is on now has finished.",
                self._touched(tracked, TaskStatus.RUNNING),
                runtime,
            )

        return StructuredTool.from_function(
            name="update_async_task",
            func=update_async_task,
            description=(
                "Send a running background worker further instructions. They are "
                "delivered as its next turn once its current turn ends — this does not "
                "interrupt it mid-thought."
            ),
            infer_schema=False,
            args_schema=_UpdateSchema,
        )

    def _cancel_tool(self) -> StructuredTool:
        def cancel_async_task(task_id: str, runtime: ToolRuntime) -> Any:
            tracked = self._tracked(task_id, runtime)
            if isinstance(tracked, str):
                return tracked
            if not self._desk().cancel(tracked.task_id):
                return (
                    f"Task {tracked.task_id} was already finished or is no longer held; "
                    "nothing was cancelled."
                )
            return self._command(
                f"Cancelled `{tracked.agent_name}` (task {tracked.task_id}).",
                self._touched(tracked, TaskStatus.CANCELLED),
                runtime,
            )

        return StructuredTool.from_function(
            name="cancel_async_task",
            func=cancel_async_task,
            description="Stop a background task that is no longer needed.",
            infer_schema=False,
            args_schema=_TaskIdSchema,
        )

    def _list_tool(self) -> StructuredTool:
        def list_async_tasks(runtime: ToolRuntime, status_filter: str | None = None) -> Any:
            tracked = self._all_tracked(runtime)
            if not tracked:
                return "No background tasks have been started."
            rows: dict[str, Any] = {}
            lines: list[str] = []
            for record in tracked:
                status = self._desk().status(record.task_id)
                if status_filter and status_filter != "all" and status != status_filter:
                    continue
                refreshed = self._touched(record, status)
                rows[record.task_id] = refreshed.as_dict()
                lines.append(
                    f"- task_id: {record.task_id}  worker: {record.agent_name}  "
                    f"status: {status}"
                )
            if not lines:
                return f"No background tasks with status {status_filter!r}."
            message = f"{len(lines)} background task(s):\n" + "\n".join(lines)
            return Command(
                update={
                    "messages": [
                        ToolMessage(message, tool_call_id=getattr(runtime, "tool_call_id", None))
                    ],
                    ASYNC_TASKS_KEY: rows,
                }
            )

        return StructuredTool.from_function(
            name="list_async_tasks",
            func=list_async_tasks,
            description=(
                "List every background task and where it stands right now. Statuses you "
                "were shown earlier in this conversation are stale — read them here."
            ),
            infer_schema=False,
            args_schema=_ListSchema,
        )

    # -- shared ------------------------------------------------------------ #

    def _command(self, message: str, record: TaskRecord, runtime: Any) -> Command[Any]:
        return Command(
            update={
                "messages": [
                    ToolMessage(message, tool_call_id=getattr(runtime, "tool_call_id", None))
                ],
                ASYNC_TASKS_KEY: {record.task_id: record.as_dict()},
            }
        )

    @staticmethod
    def _touched(record: TaskRecord, status: str) -> TaskRecord:
        from dataclasses import replace

        from openstategraph.async_tasks import _now  # noqa: PLC2701 - one spelling of "now"

        moment = _now()
        return replace(
            record,
            status=status,
            last_checked_at=moment,
            last_updated_at=moment if record.status != status else record.last_updated_at,
        )

    def _tracked(self, task_id: str, runtime: Any) -> TaskRecord | str:
        """The record this agent's own state holds for `task_id`.

        Read from **state**, never from the desk, and that is the narrowness the
        tolerant-reader rule demands: a model that invents a task id, or names
        one another node started, gets *no such task* rather than a stranger's
        answer.
        """
        rows = (getattr(runtime, "state", None) or {}).get(ASYNC_TASKS_KEY) or {}
        row = rows.get(task_id.strip()) if isinstance(rows, dict) else None
        if not isinstance(row, dict):
            return (
                f"No background task called {task_id!r} was started from this "
                "conversation. Use list_async_tasks to see the ones that were."
            )
        return TaskRecord.from_dict(row)

    @staticmethod
    def _all_tracked(runtime: Any) -> list[TaskRecord]:
        rows = (getattr(runtime, "state", None) or {}).get(ASYNC_TASKS_KEY) or {}
        if not isinstance(rows, dict):
            return []
        return [TaskRecord.from_dict(row) for row in rows.values() if isinstance(row, dict)]
