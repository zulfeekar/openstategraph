"""SSE framing and the stream fold (ticket 72 split)."""

from __future__ import annotations

from openstategraph.messages import content_text, reasoning_text, usage_of

import asyncio
import json
import logging
from contextlib import ExitStack, suppress
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger(__name__)

from openstategraph.api.diagram import workflow_mermaid  # noqa: E402
from openstategraph.api.burst_recorder import BurstRecorder  # noqa: E402
from openstategraph.api.frame_clock import (  # noqa: E402
    FRAME_CLOCK_FIELDS,
    frame_stamp,
    open_frame_clock,
)
from openstategraph.api.audience import (  # noqa: E402
    AnswerChannel,
    Audience,
    DeveloperChannel,
    clean_output as _clean_output,
    redaction_report,
    split_suggestion,
    with_capability_notice,
)
from openstategraph.developer_channel import ProseGuard  # noqa: E402
from openstategraph.executed_statements import statements_executed  # noqa: E402
from openstategraph.progress import progress_report  # noqa: E402
from openstategraph.api.registries import runtime_warnings  # noqa: E402
from openstategraph.compile.node_doors import interruptible_nodes  # noqa: E402
from openstategraph.run_journal import (  # noqa: E402
    RunTurn,
    STOPPED_KIND,
    budget_exhausted,
    run_turn,
)
from openstategraph.run_identity import run_identity  # noqa: E402

# Named here and in three other modules only — `run_doors` (the blocking
# driver), `compile/node_runtime` (the mount boundary) and `run_journal` (the
# translation). A fifth surface deciding for itself what LangGraph's
# exhaustion meant is the defect `launch-readiness/176` closed, and
# `tests/test_a_budget_overrun_speaks_our_words.py` walks the package for one.
from langgraph.errors import GraphRecursionError  # noqa: E402

from openstategraph.errors import StepBudgetExhausted  # noqa: E402


def customer_task_id(task_id: Any, audience: Any) -> Any:
    """A task id, unless it is machinery and the reader is a customer.

    `__turn_reset__` marks the start of a turn. To a developer that is real
    information — it is how one turn is told from the next in a thread. To a
    customer it arrived in the trace as `in1 (__turn_reset__)`, reading like
    the name of something their question had spawned
    (reviews-2026-08-14 ticket 04).

    Dropped here rather than hidden by the page, because that is this
    boundary's rule: a developer value is absent from a customer's frame
    because no code path put one there.
    """
    from openstategraph.api.audience import Audience

    if audience is Audience.CUSTOMER and isinstance(task_id, str) and task_id.startswith("__"):
        return None
    return task_id


def _redact_for(audience: Any) -> Any:
    """A single-value redactor for one audience, for use inside the fold.

    The terminal frame redacts a whole `outputs` map at once; a live `update`
    frame carries one node's output and is just as much a surface, so the same
    rule has to be applied a value at a time (ticket 04).
    """
    from openstategraph.api.audience import Audience as _Audience
    from openstategraph.compile.workflow_compiler import redact_failure_markers

    if audience == _Audience.DEVELOPER:
        return lambda value: value
    return lambda value: redact_failure_markers({"": value}).get("", value)


def _coerce_update(raw: Any) -> dict[str, Any]:
    """A node's contribution to one `updates`-mode chunk, defensively.

    Found live, mid-run, not in any fixture: once `subgraphs=True` is on,
    LangGraph auto-detects a nested graph invoked *synchronously inside* a
    plain node (the worker's `create_agent` call, the deep grader's
    `create_deep_agent` call) and surfaces its own internal steps in the
    same stream. Some of those steps contribute `None` rather than `{}` for
    "nothing to report this tick" — every `.get()` on a raw chunk value
    must go through this first, or the ones that changed it call directly
    crash on `'NoneType' object has no attribute 'get'`.
    """
    return raw if isinstance(raw, dict) else {}


#: How much of a spawned child's instruction rides along on the `spawn` event.
#: Long enough to recognise the task, short enough that a step row stays one line.
SPAWN_SNIPPET_CHARS = 120


def _snippet(text: Any) -> str:
    """One line of a spawned child's instruction, truncated for a step row."""
    flat = " ".join(str(text or "").split())
    if len(flat) <= SPAWN_SNIPPET_CHARS:
        return flat
    return flat[: SPAWN_SNIPPET_CHARS - 1].rstrip() + "…"


def _tool_calls_of(message: Any) -> list[dict[str, Any]]:
    """A message's tool calls, whether it arrived as an object or a dict.

    The `updates` stream carries whatever the node returned: a LangChain
    `AIMessage` from an agent's `model` step, but a plain dict from a node
    that built its own state update. Both shapes appear in one run.
    """
    calls = getattr(message, "tool_calls", None)
    if calls is None and isinstance(message, dict):
        calls = message.get("tool_calls")
    return [c for c in (calls or []) if isinstance(c, dict)]


def is_transcript_record(message: Any) -> bool:
    """Whether this is a node **writing the conversation record**, not the model.

    `_input` logs the user's turn and `_output` logs the answer where every path
    converges, which is what gives a thread memory (ticket 73). Both are right
    and stay. But `stream_mode=["updates", "messages", "custom"]` emits every
    message on that channel — written or streamed — and nothing told them apart,
    so the record re-entered the token stream and `AskPanel`, which concatenates
    every token, held the answer twice before the answer block showed it a third
    time (`every-workflow-green` 02).

    **Measured on the wire**, not inferred, by tapping one real run of
    `workflow-2026` in the editor:

        AIMessageChunk  AIMessageChunk  model                     744 chars
        AIMessage       ai              node_output_formatted_1   744 chars
        HumanMessage    human           node_input_text_1          21 chars
        ToolMessage     tool            tools                     478 chars

    744 + 744 + 21 = 1509, against 1466 measured in the DOM. The model's own
    text arrives **only** as chunks; the two settled non-tool messages are
    exactly the two records.

    So: a settled `ai` or `human` message is the record. A **tool** message is
    not — a tool produces its output whole rather than token by token, and the
    developer's per-call result cards are fed from it.

    Duck-typed on `.type` like `_is_tool_message`, for the reason recorded
    there: this channel yields chunk classes and settled messages, and one test
    covers the family without importing one of each. Verified against
    langchain-core 1.5.3, where `AIMessageChunk.type` is the class name and
    `AIMessage.type` is `"ai"`.

    **The cost, stated rather than discovered.** A provider that does not stream
    returns its reply as one settled `AIMessage`, which this drops from the
    *live* stream. Nothing is lost — the answer still arrives on the `updates`
    fold and the terminal frame — and a provider that does not stream had no
    live text to offer anyway.
    """
    kind = str(getattr(message, "type", ""))
    return kind in {"ai", "human"}


def _is_tool_message(message: Any) -> bool:
    """Whether a streamed message is a tool's *result* rather than model text.

    Duck-typed on LangChain's own `type` discriminator rather than
    `isinstance(message, ToolMessage)`: the `messages` stream yields chunk
    classes (`ToolMessageChunk`) as well as settled messages, and both answer
    `"tool"` here, so one test covers the family without importing it.
    """
    return str(getattr(message, "type", "")) == "tool"


#: Tool name -> the `spawn` kind calling it announces.
#:
#: `task` is the deep agent's blocking delegation — the parent waits.
#: `start_async_task` is the background one (`async-first/08`) — the parent gets
#: a task id and carries on, and the child outlives the turn. A reader has to be
#: able to tell those apart, because *"a worker is running"* and *"a worker is
#: running and this run has already finished"* are different situations, and
#: this file's own theme is that two situations must never render identically.
_SPAWNING_TOOLS: dict[str, str] = {
    "task": "subagent",
    "start_async_task": "async",
}


class SpawnWatcher:
    """Turns raw `updates` frames into *spawn* events — the moment a run
    creates a child worker or subagent.

    Four signals over three shapes, because the runtime spawns in structurally
    different ways and a user cannot be expected to know which one they are looking at:

    1. **Fan-out plan.** An orchestrator writes `subtasks[node_id] = [...]`
       and the conditional edge `Send`s one task each. The plan frame is the
       spawn moment — it names every child *before* any of them runs, with
       the instruction that was handed to it.
    2. **Deep-agent `task` tool call.** A deep agent spawns a subagent by
       calling its `task` tool; the call's arguments carry the subagent type
       and the task description. Detected on the agent's own model frame,
       which is where the tool call surfaces.
    2b. **`start_async_task`**, the same signal on the same frame, announced as
       `kind: "async"` because the lifecycle is different: the parent does not
       wait, and the child is still running when this run ends
       (`async-first/08`).
    3. **A namespace appearing for the first time.** A mounted workflow or
       team runs as a true nested subgraph and gets its own checkpoint
       namespace; the first frame bearing an unseen namespace head is that
       subgraph starting.

    Stateful only in the "have I seen this id before" sense, so one instance
    lives exactly as long as one run.
    """

    def __init__(self, node_ids_by_name: dict[str, str] | None = None) -> None:
        #: Graph-node name -> canvas node id. A namespace head that is not in
        #: here belongs to a node's *own* compiled loop (`node_agent_llm_1`
        #: and friends), not to a mounted workflow — announcing it as a spawn
        #: showed internal machinery as if it were a new actor.
        self._known = dict(node_ids_by_name or {})
        #: `self._known.values()` is a view, so membership on it is a linear
        #: scan — and `inspect` asked for it once per stream frame. The
        #: mapping is fixed for the life of a run (one watcher per run), so
        #: the set is built here.
        self._known_ids = set(self._known.values())
        self._namespaces: set[str] = set()
        self._tasks: set[str] = set()
        self._tool_calls: set[str] = set()
        self._last_top_node: str = ""

    def inspect(
        self,
        node_id: str,
        namespace: tuple[str, ...] | list[str],
        update: dict[str, Any],
        internal: bool,
    ) -> list[dict[str, Any]]:
        """Every spawn this frame reveals, in the order they should be shown."""
        spawns: list[dict[str, Any]] = []
        ns = list(namespace)

        head = ns[0] if ns else ""
        mounted = head.split(":")[0] if head else ""
        # Keyed by the *mounted node*, not the namespace head. Found live: a
        # `Send`-dispatched worker that calls `create_agent` gets a fresh
        # checkpoint id per dispatched instance, so keying on the head
        # announced the same worker node once per task on top of the `fanout`
        # rows that already named each child. One announcement per mounted
        # node per run is the honest count.
        is_canvas_node = not self._known or mounted in self._known or mounted in self._known_ids
        if mounted and is_canvas_node and mounted not in self._namespaces:
            self._namespaces.add(mounted)
            mounted = self._known.get(mounted, mounted)
            spawns.append(
                {
                    "kind": "subgraph",
                    "parent": self._last_top_node or mounted,
                    "label": mounted,
                    "instruction": "",
                    "taskId": None,
                    "namespace": ns,
                }
            )

        for owner, plan in (update.get("subtasks") or {}).items():
            for task in plan if isinstance(plan, list) else []:
                if not isinstance(task, dict):
                    continue
                task_id = str(task.get("id") or "")
                if not task_id or task_id in self._tasks:
                    continue
                self._tasks.add(task_id)
                spawns.append(
                    {
                        "kind": "fanout",
                        "parent": str(owner),
                        "label": str(task.get("archetype") or "") or task_id,
                        "instruction": _snippet(task.get("instruction")),
                        "taskId": task_id,
                        "namespace": ns,
                    }
                )

        for message in update.get("messages") or []:
            for call in _tool_calls_of(message):
                kind = _SPAWNING_TOOLS.get(str(call.get("name") or ""))
                if kind is None:
                    continue
                call_id = str(call.get("id") or "")
                if call_id and call_id in self._tool_calls:
                    continue
                if call_id:
                    self._tool_calls.add(call_id)
                args = call.get("args")
                args = args if isinstance(args, dict) else {}
                spawns.append(
                    {
                        "kind": kind,
                        "parent": node_id,
                        "label": str(args.get("subagent_type") or "") or kind,
                        "instruction": _snippet(
                            args.get("description") or args.get("instruction")
                        ),
                        # For `async`, this is **the task id**, not merely the
                        # call id: `abc/async_task_middleware.py` names the task
                        # after the tool call that started it, so the string a
                        # reader sees here is the one the model will poll with
                        # and the one `async_tasks` is keyed by. That is what
                        # lets a surface follow one background worker from
                        # launch to answer without correlating anything.
                        "taskId": call_id or None,
                        "namespace": ns,
                    }
                )

        if not internal and not ns:
            self._last_top_node = node_id
        return spawns


class ActiveNodeResolver:
    """Which **canvas** node is honestly executing, frame by frame.

    Ticket 01: both clients used to guess this from what a frame said about
    itself, and both guessed the same way — "the last frame that was not
    internal". While a mounted team ran, or an agent spent thirty seconds in
    its own `model`/`tools` loop, every frame was internal, so the highlight
    stayed on the *previous* top-level node (in practice: the router). The
    UI said the router was working while a team was.

    The namespace is the missing evidence, and it is already on the frame.
    A checkpoint namespace segment is `<graph-node-name>:<checkpoint-id>`,
    and `node_ids_by_name` maps a graph-node name back to the canvas node it
    was compiled from — so a namespaced frame names its owner precisely:

    - **innermost mapped segment wins** — a mount inside a mount, or an
      agent's loop inside a mount, resolves to the deepest thing that is
      actually a node on this canvas;
    - a top-level frame that *is* a canvas node is itself active;
    - anything else (a middleware step with no namespace, an inner node of a
      mounted workflow whose own ids are not on this canvas) **keeps the
      last resolved owner** rather than falling back to a stale sibling.

    Resolved once here rather than twice in the clients, because it is one
    fact about the run and two implementations of it is two chances to drift
    (`AskPanel`'s canvas highlight and `chat.html`'s `highlightFlow` had
    already drifted from each other).

    **Applied to `token` frames as well as `update` frames** (ticket 02).
    Resolving correctly is only half the answer: `updates` fires when a node
    *completes*, so a highlight fed by update frames alone shows who last
    finished and never who is now working. Tokens are the only frames that
    arrive mid-node, so they are what makes the glow move at the START of a
    step. One resolver instance sees both streams, so the two cannot disagree
    about where the run is.

    One instance per run, like `SpawnWatcher` — the stickiness is the state.
    """

    def __init__(self, node_ids_by_name: dict[str, str] | None = None) -> None:
        self._known = dict(node_ids_by_name or {})
        #: Membership on `.values()` is a linear scan and this is asked once
        #: per namespace segment per frame; the mapping is fixed per run.
        self._known_ids = set(self._known.values())
        self._active = ""

    def resolve(self, node_id: str, namespace: tuple[str, ...] | list[str]) -> str:
        """The canvas node id to highlight for this frame ("" before any)."""
        for segment in reversed(list(namespace)):
            head = str(segment).split(":")[0]
            if not head:
                continue
            if not self._known:
                self._active = head
                return self._active
            if head in self._known:
                self._active = self._known[head]
                return self._active
            if head in self._known_ids:
                self._active = head
                return self._active
        if not self._known or node_id in self._known_ids:
            self._active = node_id
        return self._active


class RunPathResolver:
    """Where a frame is happening, on **every** canvas at once (tickets 33/34).

    `activeNode` answers the question for one document — the one that was
    submitted — and that is all a top-level canvas needs. It is not enough for
    an editor, because an editor lets you *open the mount while it works*, and
    that child document contains neither the mount's id nor, in general, the
    id the frame reports for itself:

    - inside an agent's compiled loop, `node` is literally `model` or `tools`;
    - inside a mounted document, `node` is `safe_name(id)`, so the child's
      `agent-sql` arrives as `agent_sql`, which no canvas contains.

    The evidence was always on the frame, unresolved: a checkpoint namespace
    reads `wf_music:<id> / agent_sql:<id>`, one segment per level of nesting,
    each named after the graph node that owns it. Given a name->id map that
    spans the mounted documents too (`NodeRuntime.node_ids_by_name`), that is a
    **path**: the chain of canvas nodes from the outermost document inward.

    The client walks it **outermost-first** and takes the first id the document
    it has open contains. That ordering is the substance, not a detail: the
    innermost end collides — `concierge` and `chinook-assistant` both have
    `in1`, `router1` and `out1` — so an inward-first walk would light the
    parent's own input node while the *child's* input step ran, which is the
    same lie this exists to remove. Outermost-first, the parent stops at the
    mount and the child, which has no mount, walks on to the real step.

    Each level also names **the document it happened in** (`pathSlugs`), and
    that is not decoration. Ids are unique only within a document, and the
    shipped pair proves it: `concierge` mounts `chinook-assistant`, and both
    have an `in1`, a `router1` and an `out1`. A client matching on id alone
    would light the child's `router1` when the *parent's* router ran — a
    second, quieter version of the lie this exists to remove. Matching on the
    slug it has open is exact; the id-only walk above stays as the fallback
    for a client that does not know which document it is showing.

    Stateless: a path is a pure function of one frame plus two maps fixed for
    the life of the run. (`ActiveNodeResolver` is stateful because its answer
    is *sticky* across frames that resolve to nothing; `path` reports only what
    this frame can support and leaves the smoothing to the client.)
    """

    def __init__(
        self,
        node_ids_by_name: dict[str, str] | None = None,
        mount_slugs: dict[str, str] | None = None,
        root_slug: str = "",
    ) -> None:
        self._known = dict(node_ids_by_name or {})
        #: Mount canvas node id -> the slug it descends into.
        self._mounts = dict(mount_slugs or {})
        #: The document the run was launched against — the owner of level 0.
        self._root = root_slug

    def resolve(
        self, raw_name: str, namespace: tuple[str, ...] | list[str]
    ) -> tuple[list[str], list[str]]:
        """`(path, slugs)` — canvas ids and their documents, outermost first."""
        path: list[str] = []
        slugs: list[str] = []

        def append(name: str) -> None:
            canvas_id = self._known.get(name)
            # Consecutive duplicates dropped rather than all duplicates: a
            # frame whose own node *is* the namespace segment it sits in
            # (an agent's loop reporting under its own name) would otherwise
            # name the same card twice in a row, while a genuine A -> B -> A
            # nesting stays expressible.
            if not canvas_id or (path and path[-1] == canvas_id):
                return
            # The document this level lives in: the run's own for the first
            # entry, and thereafter whatever the mount above it descended
            # into. Looked up by the **whole chain so far**, because a mount
            # node id is unique only within its own document — two sibling
            # subtrees can both mount at a node called `inner`. Empty when a
            # mount's slug is unknown, which a client must read as "no claim"
            # rather than as a match.
            owner = self._root if not path else self._mounts.get("/".join(path), "")
            path.append(canvas_id)
            slugs.append(owner)

        for segment in namespace:
            head = str(segment).split(":")[0]
            if head:
                append(head)
        # The frame's own step last, so the path always ends at the deepest
        # thing that is a card somewhere. Unresolvable names — `model`,
        # `tools`, a middleware step — simply do not extend it, which is
        # correct: they are not cards on anyone's canvas.
        append(str(raw_name))
        return path, slugs


async def _client_left(receive: Any) -> None:
    """Resolves the moment the ASGI server reports the client is gone."""
    while True:
        message = await receive()
        if message.get("type") == "http.disconnect":
            return


def _abandon(task: Any) -> None:
    """Drops a task we are no longer waiting on, without a warning storm.

    A cancelled `__anext__` whose worker thread is still inside a synchronous
    node does not finish immediately (a blocking call cannot be interrupted),
    so the task outlives us. Retrieving its outcome here is what stops asyncio
    logging "exception was never retrieved" for work nobody wanted.

    Unchanged by `async-first/02`, deliberately. The fold is an async
    generator now, but the reason this cancels *without awaiting* is the same
    one it always had, and it is measured (`async-first/09`): the pending step
    may be a blocking model call, and awaiting it would turn today's instant
    stop into a stop the client sits through. Only an `async def` node body is
    genuinely cancelled here, and that is Phase D.
    """
    task.cancel()
    task.add_done_callback(lambda done: done.cancelled() or done.exception())


async def stop_when_client_leaves(frames: Any, receive: Any) -> Any:
    """Drives a sync SSE generator and stops pulling when the client hangs up.

    **This is what makes Stop mean anything on this transport.** Starlette
    does not listen for disconnects on a modern ASGI server: for
    `spec_version >= 2.4` it only notices when a `send()` raises `OSError`,
    and uvicorn's socket writes do not fail promptly. Measured, not assumed —
    a browser that aborted its fetch mid-crew left the run streaming to its
    natural end, with every remaining superstep billed to nobody, while the
    UI already said "Stopped by you". That is precisely the fake cancel this
    must not be.

    So the disconnect is raced against each frame here. On disconnect we stop
    pulling immediately and return; the frame already in flight is abandoned
    and its generator finalised (which is the `GeneratorExit` `_stream_run`
    logs). The boundary is unchanged and still honest — a blocking model call
    inside the current superstep cannot be interrupted by anyone — but the
    supersteps *after* it no longer run.

    This is the one path with **no terminal frame** (see `_stream_run`): the
    consumer we would send it to is the one that left. The client's own
    fallback is authoritative there — an aborted signal reads as "you stopped
    it", a body that ended with no terminal frame as "the connection dropped".

    **`iterate_in_threadpool` is gone** (`async-first/02`). `_stream_run` is
    an async generator driving `graph.astream()`, so there is no longer a sync
    generator to bridge and no worker thread held for the life of the run.
    What survives untouched is the abandon: cancelled, never awaited — see
    `_abandon`.

    It stays a separate function from `stop_when_client_leaves_async` for that
    one reason, and the two docstrings are where the difference is written
    down: this path abandons work that cannot be interrupted, `/api/events`
    closes a source that can only be waiting. Merging them would have to pick
    one of those behaviours for both.
    """
    stream = frames.__aiter__()
    gone = asyncio.ensure_future(_client_left(receive))
    try:
        while True:
            step = asyncio.ensure_future(stream.__anext__())
            await asyncio.wait({step, gone}, return_when=asyncio.FIRST_COMPLETED)
            # **The disconnect is asked about first, not "did the step lose the
            # race".** Both can be ready in the same pass — an async fold that
            # has a frame buffered resolves its `__anext__` without ever
            # suspending, so a client that left is only *also* ready, never
            # ahead. Reading the race as "the step did not win" then let the
            # whole run drain to a consumer that had gone, which is precisely
            # the fake cancel this function exists to prevent. Found by
            # `test_a_disconnect_stops_the_run_instead_of_letting_it_finish`
            # when the fold went async (`async-first/02`); under the old
            # threadpool bridge every step cost a thread hop, so the ordering
            # was correct by accident.
            if gone.done():
                _abandon(step)
                return
            try:
                frame = step.result()
            except StopAsyncIteration:
                return
            yield frame
    finally:
        _abandon(gone)


async def stop_when_client_leaves_async(frames: Any, receive: Any) -> Any:
    """`stop_when_client_leaves`, for a source that is already asynchronous.

    Same finding, same fix, different input: Starlette does not notice a
    disconnect on a modern ASGI server, so the disconnect has to be raced
    against each frame. The other function drives a *sync* generator through a
    threadpool because `graph.stream()` is blocking; `/api/events` is a pure
    asyncio source (a queue and a timer), and pushing it through a threadpool
    would occupy a worker thread for the entire life of every open surface.

    On disconnect the source generator is closed rather than abandoned: it owns
    a broadcaster subscription, and a subscription that outlived its socket
    would be fed for the life of the process. There is no work in flight to
    abandon here — the only thing it can be doing is waiting.
    """
    import asyncio

    gone = asyncio.ensure_future(_client_left(receive))
    stream = frames.__aiter__()
    try:
        while True:
            step = asyncio.ensure_future(stream.__anext__())
            done, _ = await asyncio.wait({step, gone}, return_when=asyncio.FIRST_COMPLETED)
            if step not in done:
                # Cancelled **and awaited**, unlike the sync path's `_abandon`.
                # There the pending step is a blocking model call that cannot be
                # interrupted, so waiting for it would defeat the stop. Here it
                # is a wait on a queue, it unwinds at once — and it must, because
                # `aclose()` on a generator whose `__anext__` is still in flight
                # raises "already running", which the `suppress` below would
                # swallow, silently skipping the very cleanup this exists for.
                step.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await step
                return
            try:
                yield step.result()
            except StopAsyncIteration:
                return
    finally:
        _abandon(gone)
        closer = getattr(stream, "aclose", None)
        if callable(closer):
            with suppress(Exception):
                await closer()


def _token_frame(common: dict[str, Any], block: str, text: str, usage: Any) -> str:
    """One `token` frame, built in the one place a `token` frame is built.

    A chunk can now produce **two** frames — a model's deliberation and its
    answer arrive in one content list and are split apart (ticket 23) — so the
    fifteen fields below are assembled here rather than twice at the call
    site, which is where the two would drift.

    `common` carries everything decided per chunk; `block`, `text` and `usage`
    are what differ between the frames a single chunk yields.
    """
    message = common["message"]
    withheld = bool(common["withheld"])
    return _sse(
        "token",
        {
            "node": common["node"],
            "namespace": common["namespace"],
            "content": text,
            # WHICH KIND of text this is (ticket 23), so a reasoning model can
            # be rendered as one: thinking shown as thinking, the answer as
            # the answer. `text` | `reasoning`.
            #
            # Distinct from `kind` below, which answers *who produced it*. A
            # tool result is `kind: "tool"`, `block: "text"`; collapsing the
            # two would make a thinking tool inexpressible and would leave a
            # client unable to tell a tool's output from its reasoning.
            #
            # `"text"` is the right default against a backend that predates
            # the field: it is the overwhelming majority of frames and the
            # only kind that was ever emitted.
            "block": block,
            # What this message cost, on the frame that SETTLES it — the
            # docs' `message-finish`. `null` on every other frame, so a client
            # reads one field unconditionally and "usage is present" is itself
            # the signal that the message finished.
            "usage": usage.as_frame() if usage else None,
            # Present and true only when the text was the machinery rather
            # than the reply. Absent on every frame a developer receives, so
            # "did I get the whole stream" stays answerable.
            **({"withheld": True} if withheld else {}),
            # Ticket 02, and the whole point of it: `activeNode` means exactly
            # what it means on an `update` frame — the canvas node to show as
            # running — but a `token` frame is the only one that arrives while
            # a node is STILL WORKING. `updates` fires on completion, so a
            # highlight fed by update frames alone can only ever show who last
            # finished. Measured on a real run: 135 consecutive token frames
            # streamed out of the mounted analyst over ~20s while the last
            # update frame still said `router1`.
            #
            # NOT coalesced here. The field is attached to every frame because
            # its meaning must not vary by frame ("present = changed" would be
            # a second, implicit field), and because an SSE consumer may join
            # late or drop frames. Coalescing is the clients' job and is cheap
            # there — both compare against the node they last highlighted and
            # do nothing when it is unchanged, so a 135-token model turn is
            # one state write.
            "activeNode": common["activeNode"],
            "interruptible": common["interruptible"],
            # Carried here too, and for the reason `activeNode` is: a `token`
            # frame is the only one that arrives while a node is STILL
            # WORKING, so a canvas fed by `update` frames alone can only ever
            # light who last finished. A child canvas opened mid-run sees
            # nothing at all without this — its steps are exactly the long
            # ones.
            "path": common["path"],
            "pathSlugs": common["pathSlugs"],
            # WHAT produced this text, so a client can stop treating a tool's
            # result as the model's prose.
            #
            # LangGraph's `messages` mode carries every message a node emits,
            # not only model tokens — a `ToolMessage` rides the same stream
            # (documented, and observed: `list_all_tables` streamed its
            # eleven-row Markdown table through here). Untagged, the client
            # concatenated tool output and model reasoning into one blob and
            # rendered the result as Markdown, which collapsed the table onto
            # a single line — a tool result made unreadable precisely because
            # it was long.
            "kind": common["kind"],
            # A tool result's identity for the client's fold. `name` alone
            # cannot separate two consecutive calls to the same tool
            # (`get_table_schema` on Invoice, then on InvoiceLine); the
            # `tool_call_id` can.
            #
            # Withheld with the content, because ticket 25 names the tool NAME
            # as its own leak: QA read `music_store` on the customer surface,
            # and `chinook_execute_sql` says as much about the machinery as
            # the table it returned.
            "tool": {"name": "", "callId": ""}
            if withheld
            else {
                "name": str(getattr(message, "name", "") or ""),
                "callId": str(getattr(message, "tool_call_id", "") or ""),
            },
        },
    )


def _stream_parts(stream: Any) -> Any:
    """`(namespace, mode, payload)` for each chunk, whichever shape it arrives in.

    We ask LangGraph for **`version="v2"`** (see `_run_frames`), whose every
    chunk is a `StreamPart` — `{"type", "ns", "data"}` — regardless of how many
    modes were requested or whether `subgraphs=True` is set. v1, the default,
    yields a bare payload for one mode, a `(mode, payload)` pair for several,
    and a `(ns, mode, payload)` triple once subgraphs are on. We unpacked the
    triple, which was correct for exactly the combination we happened to pass
    and would have become wrong on the day a third mode was added — stable by
    accident rather than by contract.

    The v1 tuple is still accepted here, and that is deliberate rather than
    leftover. Nine test files script this fold with hand-written chunks, and a
    decode change that can only be demonstrated by rewriting its own callers
    has not been isolated; `test_stream_version_v2.py` pins the two shapes to
    identical frames and pins the `version="v2"` we actually send.

    A chunk this version cannot produce is **skipped, not raised on**. The fold
    is the one place a run can die without a terminal frame reaching the
    client, so an unreadable chunk costs one frame rather than the stream.

    The decode itself is `_stream_part`, one chunk at a time, because since
    `async-first/02` the fold drives `graph.astream()` and iterates the chunks
    with `async for`. Two loops over one decode would be two spellings of the
    chunk vocabulary, and the second one is the one that goes stale.
    """
    for chunk in stream:
        decoded = _stream_part(chunk)
        if decoded is not None:
            yield decoded


def _stream_part(chunk: Any) -> tuple[Any, str, Any] | None:
    """One chunk as `(namespace, mode, payload)`, or `None` if it is unreadable.

    The whole chunk vocabulary, in one place — see `_stream_parts` for which
    shapes arrive and why the v1 tuple is still accepted. `None` rather than a
    raise: the fold is the one place a run can die without a terminal frame
    reaching the client, so an unreadable chunk costs one frame, never the
    stream.
    """
    if isinstance(chunk, dict):
        mode = chunk.get("type")
        if isinstance(mode, str):
            return tuple(chunk.get("ns") or ()), mode, chunk.get("data")
        logger.warning("skipping an unreadable stream chunk: %r", sorted(chunk))
        return None
    if isinstance(chunk, tuple) and len(chunk) == 3:
        namespace, mode, payload = chunk
        return namespace, mode, payload
    logger.warning("skipping an unreadable stream chunk of type %s", type(chunk).__name__)
    return None


def _frame_bytes(event: str, data: dict[str, Any]) -> str:
    """The serialiser: an `event:` line, a `data:` line, a blank line.

    `json.dumps` rather than string interpolation, because a node's output can
    contain newlines and quotes, and SSE's `data:` line is newline-delimited —
    an unescaped newline would silently split one event into two.

    Split from `_sse` so that *building* a frame and *formatting* one are
    separable (`memory-and-replay` 46). Building mints the clock stamp, which
    advances a counter; a caller that only wants to re-render a payload it
    already has — the wire-format golden does exactly that — must not mint a
    second one. Nothing in the running server calls this directly.
    """
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _sse(event: str, data: dict[str, Any]) -> str:
    """One Server-Sent Event frame, dated (`memory-and-replay` 46).

    The one place a frame is built, and therefore the one place the clock is
    minted: `seq` and `elapsedMs` are appended here rather than at ~ten call
    sites, so a frame kind added tomorrow is stamped without anybody
    remembering to. `frame_stamp` is empty outside a stream, which is how the
    catalogue feed keeps the payload it always had.

    Appended last, so the ordering of every field the wire already carried is
    untouched — see `test_the_sse_wire_format_is_unchanged`.
    """
    return _frame_bytes(event, {**data, **frame_stamp()})


#: The event names that report progress. A client must keep waiting after
#: every one of them — none of these can be the last frame of a healthy run.
#:
#: `progress` sits beside `token` because it is the other frame that arrives
#: while a node is *still working* (ticket 22). `update` fires on completion,
#: so between two of them a tool that spends forty seconds paging an API
#: produced nothing at all and the run read as stopped.
PROGRESS_EVENTS: tuple[str, ...] = ("update", "token", "progress", "spawn")

#: The event names that *end* a stream. Exactly one of these is the last
#: frame of every stream that lives long enough to send one — see
#: `_stream_run`, which is what guarantees it.
TERMINAL_EVENTS: tuple[str, ...] = ("done", "interrupt", "error")

#: The whole run vocabulary, in the order a client meets it. Named here
#: rather than retyped in the guide: `docs/api.md` is what a stranger builds
#: a client from, and `backend/tests/test_api_guide.py` reads this tuple to
#: prove the page still describes every frame this code can emit. OpenAPI
#: cannot express any of it (see `api/openapi_document.py`), so the prose is
#: the contract and a drift there is a broken client, not a typo.
RUN_EVENTS: tuple[str, ...] = PROGRESS_EVENTS + TERMINAL_EVENTS

#: What each frame carries **of its own** — the vocabulary one level below the
#: names. `FRAME_FIELDS` below is this plus the clock every frame gets from
#: `_sse`; that is the one a consumer reads, and this is the one an emitter
#: edits.
#:
#: **Why this exists** (framework-packaging ticket 10). `RUN_EVENTS` was
#: published, pinned in both languages and read by a drift test; the ~30 field
#: names inside those frames were a hand-mirror in `RuntimeClient.ts`, prose in
#: `docs/api.md` and dict literals down this file, with nothing holding the
#: three together. The pin stopped at what a frame is *called*. `withheld` is
#: what that cost: emitted here, documented in the guide, Python-tested, and
#: read by no client at all — while `api/audience.py` says the field exists
#: precisely so a client can tell "emptied deliberately" from "nothing
#: happened".
#:
#: Declared once, here, beside the emitters — so `sse_responses` can write it
#: into the OpenAPI description, `docs/openapi.json` publishes it, and
#: `contractDrift.test.ts` reads it from there rather than from a second list.
#: A field a frame stops carrying, or gains, is now a diff in a committed
#: artifact instead of a silent widening.
#:
#: Optional fields are included: `withheld` rides only a frame that was
#: emptied, and `developer` only a developer run, but a client has to know
#: they exist to handle them. Absence is a value here, not a gap.
_PAYLOAD_FIELDS: dict[str, tuple[str, ...]] = {
    "update": (
        "node", "namespace", "taskId", "internal",
        "activeNode", "path", "pathSlugs", "output",
        # Whether a stop *right now* cancels the node this frame names, or
        # merely walks away from it (`async-first/07`). On the three frames
        # that carry `activeNode` and on no others — see that ticket for why
        # a run surface that cannot say which of the two happened makes the
        # whole feature unfalsifiable from the outside.
        "interruptible",
        # Optional, and a pair: a grader's own frame carries them when a
        # deterministic check rejected the candidate before any model was
        # invoked, and neither key at all otherwise (`production-ready` 92).
        "check", "reason",
    ),
    "token": (
        "node", "namespace", "content", "block", "usage",
        "activeNode", "path", "pathSlugs", "kind", "tool", "withheld",
        "interruptible",
    ),
    "progress": (
        "node", "namespace", "message", "current", "total",
        "activeNode", "path", "pathSlugs", "interruptible",
        # `launch-readiness/163`. Always present, `null` for a customer and
        # for any line with no evidence behind it — a frame that omitted the
        # key would make "this audience does not get it" and "this line had
        # nothing to add" the same wire shape, which is the distinction the
        # field exists to draw.
        "detail",
    ),
    "spawn": ("kind", "parent", "label", "instruction", "taskId", "namespace"),
    "interrupt": ("threadId", "node", "message", "candidate", "verdict", "reason", "check"),
    "done": (
        "threadId", "answer", "decisions", "outputs",
        "nested", "attempts", "mermaid", "developer", "publishedRejected",
    ),
    "error": ("threadId", "detail"),
}

#: What each frame **actually carries** — the payload table above plus the two
#: fields `_sse` mints for every one of them (`memory-and-replay` 46).
#:
#: Composed rather than typed into each row, and that is the structural half of
#: the ticket's "a frame kind cannot be added without one": a new row in the
#: table above inherits `seq` and `elapsedMs` because this expression gives
#: them to it, not because a contributor remembered. `sse_responses` writes
#: this into the OpenAPI description, `docs/openapi.json` publishes it, and
#: `contractDrift.test.ts` reads it back — so the clock is a published field on
#: every frame, in both languages, from one declaration.
FRAME_FIELDS: dict[str, tuple[str, ...]] = {
    name: fields + FRAME_CLOCK_FIELDS for name, fields in _PAYLOAD_FIELDS.items()
}


def _frame_interruptible(frame: str, previous: bool) -> bool:
    """Whether a stop would cancel the node this frame names, else `previous`.

    Only `update`, `token` and `progress` carry the field, and a frame without
    it leaves the answer where it was — a `spawn` between two of an agent's
    tokens must not read as "the agent stopped being cancellable".

    Parsed rather than threaded out of `_run_frames` as a second return value:
    the fold yields strings by design (`_sse` is the one place a frame is
    built), and a parallel channel carrying a copy of a field the frame
    already has is the duplication this repository keeps paying for.
    """
    if '"interruptible"' not in frame:
        return previous
    try:
        payload = json.loads(frame.split("data: ", 1)[1])
    except (IndexError, ValueError):  # pragma: no cover - `_sse` cannot emit this
        return previous
    value = payload.get("interruptible")
    return previous if value is None else bool(value)


def _record_chunk(recorder: BurstRecorder, frame: str) -> None:
    """Fold a `token` frame into this run's cadence (`memory-and-replay` 47).

    Read off the finished frame rather than threaded out of the fold, and that
    is the same choice `_frame_interruptible` above makes for the same reason:
    `_sse` is the one place a frame is built, and a parallel channel carrying a
    copy of fields the frame already has is the duplication this repository
    keeps paying for.

    It also buys the audience boundary for nothing. What is recorded is
    literally what the client received, so a withheld chunk — already emptied
    by `_token_frame` before the frame existed — has no text here to leak. The
    boundary is upstream of the recorder rather than repeated inside it.

    The prefix test comes first so the ~1000 non-token frames of a real run
    cost a string comparison and not a JSON parse.
    """
    if not frame.startswith("event: token\n"):
        return
    try:
        payload = json.loads(frame.split("data: ", 1)[1])
    except (IndexError, ValueError):  # pragma: no cover - `_sse` cannot emit this
        return
    recorder.chunk(payload)


def _is_terminal(frame: str) -> bool:
    """True if this SSE frame is one of the three that end a stream."""
    return any(frame.startswith(f"event: {name}\n") for name in TERMINAL_EVENTS)


#: The accumulators the terminal frame is built from that are **also** state
#: channels — so a resume can seed them from what the thread already holds
#: (`workflow-gallery` 25). State key -> the local name it seeds.
#:
#: `nested_decisions` is deliberately absent: it has no state channel to read.
#: `_subgraph` records `nested_outputs` into state because `/api/runs` has no
#: frames to rebuild it from (`every-workflow-green` 16) and never did the same
#: for decisions, so there is nothing here to seed it with. Recorded as a known
#: gap rather than implied by a list that looks complete.
RESUME_SEEDED_KEYS: tuple[str, ...] = (
    "decisions",
    "outputs",
    "nested_outputs",
    "answer",
    "attempts",
    "forced",
    "unrouted",
    "retries",
    "unmet_tools",
    "tool_use",
    "redactions",
    "budget_stops",
)


def _resumes_a_paused_run(graph_input: Any) -> bool:
    """Whether this call picks a thread back up rather than starting one.

    A resume arrives as LangGraph's `Command(resume=...)`; a fresh run arrives
    as the initial state dict. Asked by duck-typing rather than `isinstance`
    because this fold is also driven by scripted stubs that pass neither.

    Gated on the resume, and this is the load-bearing choice. Seeding *every*
    call from the checkpoint would fold a previous **turn** of the same
    conversation into a fresh run's terminal frame — a thread is the
    conversation, not the approval handle, and second turns into one thread are
    ordinary. A resume is the only call that is the same run.
    """
    if isinstance(graph_input, dict):
        return False
    return getattr(graph_input, "resume", None) is not None


def _built_warnings(plan: Any, runtime: Any) -> list[str]:
    """How the workflow was *built* — this door's own half of a run record.

    Read at record time rather than when the turn opens, because
    `runtime_warnings` collects what the runtime could not resolve while it
    ran. `getattr` because the fold is also driven by scripted stubs.
    """
    return list(getattr(plan, "warnings", None) or ()) + runtime_warnings(runtime)


def _question_asked(graph_input: Any) -> str:
    """What this segment was asked, for the run record.

    A fresh run carries the question in its initial state. A resume carries a
    `Command(resume={"decision": ...})` instead, and the honest answer there is
    what the person decided — the spelling `CompiledWorkflow.resume` has always
    written into its own row, kept identical so one store does not hold two
    vocabularies for one event.
    """
    if isinstance(graph_input, Mapping):
        return str(graph_input.get("question") or "")
    resume = getattr(graph_input, "resume", None)
    if isinstance(resume, Mapping):
        return f"resume:{resume.get('decision') or ''}"
    return ""


async def _stream_run(
    graph: Any,
    graph_input: Any,
    config: dict[str, Any],
    plan: Any,
    node_ids_by_name: dict[str, str],
    runtime: Any,
    thread_id: str,
    audience: Audience = Audience.CUSTOMER,
    document: Any = None,
    store: Any = None,
    run_context: Mapping[str, Any] | None = None,
) -> Any:
    """The stream, with its ending guaranteed (UX-02).

    `_run_frames` below does the actual work; this wrapper exists for one
    reason, and it is a protocol rule rather than a convenience:

    > **Every stream ends with a frame that says how it ended.** A client must
    > never have to tell "still working", "finished" and "died" apart by
    > waiting and guessing.

    …and **every terminal frame names the thread it ran in** (ticket 11).
    `interrupt` always did, because resuming an approval obviously needs it;
    `done` and `error` did not, and the omission read as "a thread is an
    approval handle". It is not — a thread is the *conversation*, the channel
    `messages` accumulates in. The server invents a `thread_id` for a request
    that omits one, so a client with no way to read it back could never send a
    second turn into the same conversation, and every follow-up arrived with
    no antecedent. Disclosing it on all three is what makes continuity
    something a client can *choose*, rather than something it has to have
    guessed in advance.

    | Exit path | Terminal frame |
    | --- | --- |
    | the run completes | `done` |
    | a `human.approval` node pauses it | `interrupt` |
    | anything raises — in `graph.stream`, in the fold, in `get_state`, in `draw_mermaid` | `error` |
    | the fold returns without saying how it ended (a bug) | `error`, and logged |
    | **the client disconnects / the server is killed** | **none is possible — see below** |

    The last row is the honest exception, not an oversight. After
    `GeneratorExit` a generator may not yield (Python raises `RuntimeError:
    generator ignored GeneratorExit`), and there is no longer a socket to
    write to; a killed process runs no Python at all. **So on that path the
    client's own fallback is authoritative**, and both clients implement it:
    an aborted signal means "you stopped it", and a body that ends with no
    terminal frame means "the connection dropped" — never a silent success
    and never an open spinner. The disconnect is logged here because that log
    line is the only record such a run leaves.

    Before this wrapper, `error` covered only exceptions raised *inside* the
    fold: a `get_state` or `draw_mermaid` failure unwound the generator with
    the client having seen updates and no ending at all.
    """
    # **The turn this run is written down in** (`memory-and-replay` 44).
    #
    # Opened here rather than in `_run_frames` because this is the frame with a
    # real `finally`: the turn holds the clock, LangChain's per-model token
    # meter and the nesting guard, and every one of those has to be released
    # once whichever way the stream ends — including the stop path, where the
    # generator below may not yield another byte. `_run_frames` is where the
    # *row* is assembled, because that is the frame that holds the state.
    #
    # An `ExitStack` rather than a `with` block: this generator's body is the
    # protocol guarantee in the docstring above, and re-indenting it under a
    # context manager would bury the one thing it exists to make obvious.
    turn_stack = ExitStack()
    # **The clock this stream's frames are dated by** (`memory-and-replay` 46).
    #
    # Opened here, beside the turn and for the same reason: this is the one
    # wrapper every run stream goes through — `/api/runs/stream` and
    # `/api/runs/resume` both — so a clock opened here belongs to exactly one
    # run and is released whichever way the stream ends. `_sse` reads it; no
    # call site passes it, which is what makes a new frame kind dated by
    # default rather than by attention.
    turn_stack.enter_context(open_frame_clock())
    identity = run_identity(config)
    turn = turn_stack.enter_context(
        run_turn(
            workflow_slug=identity.get("workflow_slug", ""),
            thread_id=thread_id,
            session_id=identity.get("session_id", ""),
            user_email=identity.get("user_email", ""),
            question=_question_asked(graph_input),
        )
    )
    # **How this run's output arrived** (`memory-and-replay` 47). Per stream,
    # like the clock above and for the same reason. Fed below from the frames
    # this wrapper is already walking, and read by `_run_frames` when it writes
    # the row — which is safe by generator semantics: the fold cannot reach its
    # terminal frame until every frame before it has been consumed here.
    #
    # The audience travels with the bursts because a developer run's cadence
    # carries developer content, and a reader has to be able to refuse it.
    recorder = BurstRecorder(audience=getattr(audience, "value", str(audience)))
    frames = _run_frames(
        graph,
        graph_input,
        config,
        plan,
        node_ids_by_name,
        runtime,
        thread_id,
        audience,
        document,
        store,
        run_context,
        turn=turn,
        recorder=recorder,
    )
    ended = False
    # What a stop would do to the step in flight, kept as the frames go past
    # so the log line below can say which of the two happened. Read off the
    # frames rather than recomputed here, so the sentence in the log and the
    # sentence in the browser cannot disagree — they are the same field.
    cancellable = False
    try:
        async for frame in frames:
            ended = ended or _is_terminal(frame)
            cancellable = _frame_interruptible(frame, cancellable)
            _record_chunk(recorder, frame)
            yield frame
    except (GeneratorExit, asyncio.CancelledError):
        # Stop, pressed, or the client hung up. Nothing may be yielded from
        # here — see the docstring. Logged rather than silent because "did the
        # run actually stop?" is otherwise unanswerable from outside, and a
        # Stop button whose effect cannot be observed is a fake cancel.
        #
        # **Two spellings of one event since `async-first/02`.** This is an
        # async generator now, so a consumer that stops pulling arrives as
        # `GeneratorExit` (an explicit `aclose()`) *or* as `CancelledError`
        # (the pending `__anext__` task cancelled, which is what
        # `stop_when_client_leaves` does and therefore the live path). Both
        # mean the same thing here and both must be re-raised, never converted
        # into a frame.
        #
        # **What this costs, now that Phase D has landed** — measured live on
        # 2026-08-27 through this very path (`async-first/07`), never asserted
        # by a test. `graph.astream` is a generator driven BY the fold, so
        # nothing further is *scheduled* either way. What changed is the step
        # already in flight:
        #
        #   morning-brief, supervisor + three concurrent workers,
        #   disconnected 12 s in, gpt-oss:120b-cloud, three runs each:
        #
        #     pre-Phase-D (`72eaaa9`, `def` worker bodies)
        #        24.16 s / 12.65 s / 16.51 s of node work billed after the
        #        stop; 3/3 workers ran to completion and were discarded.
        #     this tree (`async def` worker bodies)
        #        0.68 s / 0.41 s / 1.08 s; 3/3 workers cancelled.
        #
        # The ~15 s and ~75 s this comment used to quote were the same
        # quantity on a larger crew and a later stop point, and they were
        # never latency a user waited through — the client-visible stop has
        # been 0.00 s in every run of every arm, before and after
        # (`async-first/09`). They were a model call that kept being paid for.
        #
        # **The boundary that survives, because it is a different one.** A
        # cancelled body unwinds at its *next await*, so the provider call
        # already issued is still finished and still billed: 0.41–4.85 s
        # across the nine runs above. And a node whose body is still `def` —
        # a function, an output formatter, anything reached through
        # `node_doors`' sync door — is exactly as uninterruptible as
        # everything was before. So "stop means stop" is a claim about a
        # *node*, never about the graph, which is why the frames carry
        # `interruptible` per node and this line says which of the two it was
        # rather than describing one and hoping.
        #
        # There is still no cancellation seam inside a superstep on this
        # version, and **all three candidates were probed on the installed
        # langgraph 1.2.10 rather than read off a page** (ticket 09):
        #
        # - `RunControl.request_drain()` — its check is the first statement of
        #   `PregelLoop.tick()`, so it stops at exactly this boundary. With a
        #   node sleeping 20s and a drain at t=3s, control returned at 20.01s.
        #   LangChain's own fault-tolerance page says the same in words:
        #   drain "does not cancel running asyncio tasks or kill threads".
        # - `GraphRunStream.abort()` — it is `graph_iter.close()` plus a mux
        #   close: from the pumping thread it is *exactly* the `GeneratorExit`
        #   we are already handling here, and from any other thread it is a
        #   **silent no-op** — `close()` on a generator that is mid-`next()`
        #   raises `ValueError: generator already executing`, and `abort()`
        #   swallows it under a bare `except Exception: pass`. Probed: abort
        #   at t=3s returned instantly and raised nothing, the node still ran
        #   to completion at 20.01s, and the caller was left with an empty
        #   final state because the mux had been closed under it. It is
        #   strictly worse than this handler, which at least logs. It also
        #   requires the v3 protocol (`GraphRunStream` carries
        #   `@beta("The v3 streaming protocol on Pregel is experimental")`).
        # - Node `timeout` — the only construct in 1.2.10 that interrupts a
        #   node mid-flight, and `_internal/_timeout.py` rejects it at compile
        #   time for sync nodes: "Node timeouts are only supported for async
        #   nodes." Which is the same seam by another road: the node.
        #
        # None of that is what stops a run today. Cancelling the task driving
        # `astream` is, and it reaches an `async def` body directly — see
        # `.scratch/async-first/`.
        logger.info(
            "run stream stopped by the client (thread_id=%s) — no further "
            "supersteps, and the step in flight was %s",
            thread_id,
            (
                "cancelled"
                if cancellable
                else "abandoned (it finishes in the background; its result is discarded)"
            ),
        )
        raise
    except Exception as exc:  # noqa: BLE001 — reported to the client, not swallowed
        # One place turns an exception into a frame, so there is one spelling
        # of a failed run no matter where in the pipeline it failed.
        if not ended:
            # `threadId` on the failure path too (ticket 11): the turn that
            # died is still checkpointed, and a client that wants to try again
            # in the *same* conversation needs to name the thread it was in.
            # Same two rules the terminal frame obeys, because this *is* the
            # terminal frame when a run dies: our own errors are already the
            # copy (no Python class name), a refused credential is named as
            # refused, and a customer gets none of it — `detail` reached them
            # reading "set OLLAMA_API_KEY in .env" (ticket 04).
            from openstategraph.compile.workflow_compiler import (
                describe_failure,
                describe_failure_for_customer,
                failing_task_name,
            )
            from openstategraph.api.audience import Audience as _Audience

            detail = (
                describe_failure(exc)
                if audience == _Audience.DEVELOPER
                else describe_failure_for_customer(exc)
            )
            # Name the node, for a developer, the way `/api/runs` already does.
            #
            # A node's `error_handler` is bypassed whenever the caller streams
            # with `subgraphs=True` or `stream_mode="messages"`, which is what
            # this door asks for — LangGraph's behaviour, reproduced in twenty
            # lines with no model and no compiler (`every-workflow-green` 14).
            # So this door cannot recover the run the way the other two do, and
            # the least it can do is say *which step* died instead of handing
            # over a provider string and a reference id.
            #
            # A customer is deliberately excluded: a canvas node id is not
            # theirs to act on, and `describe_failure_for_customer` exists to
            # keep exactly this kind of detail away from them.
            if audience == _Audience.DEVELOPER:
                raw_name = failing_task_name(exc)
                if raw_name:
                    node = node_ids_by_name.get(raw_name, raw_name)
                    detail = f'Node "{node}" failed and produced no result. {detail}'
            yield _sse("error", {"threadId": thread_id, "detail": detail})
        return
    finally:
        # Not left to refcounting: under a stop the checkpointer/DB handles
        # the LangGraph stream holds should be released at a defined moment
        # rather than at the collector's convenience. `aclose()` is idempotent,
        # so the normal path pays nothing for it.
        #
        # `CancelledError` is suppressed alongside `Exception` because this
        # runs while a *cancelled* task unwinds, where the first `await`
        # re-raises it: without the suppression the close would be skipped
        # exactly on the path it exists for. It is not a swallowed
        # cancellation — the frame is already unwinding and the caller has
        # already stopped waiting.
        with suppress(Exception, asyncio.CancelledError):
            await frames.aclose()
        # After the frames, so a row recorded while they unwound is still
        # inside the turn that meters it.
        turn_stack.close()

    if not ended:
        # Unreachable by design — the fold's every path ends in `done`,
        # `interrupt` or a raise. Kept because "unreachable by design" is a
        # claim about today's code, and the cost of it becoming false is a
        # client that waits forever.
        logger.error(
            "run stream for thread_id=%s ended without a terminal frame", thread_id
        )
        yield _sse(
            "error",
            {
                "threadId": thread_id,
                "detail": "The run ended without reporting a result.",
            },
        )


async def _run_frames(
    graph: Any,
    graph_input: Any,
    config: dict[str, Any],
    plan: Any,
    node_ids_by_name: dict[str, str],
    runtime: Any,
    thread_id: str,
    audience: Audience = Audience.CUSTOMER,
    document: Any = None,
    store: Any = None,
    run_context: Mapping[str, Any] | None = None,
    turn: "RunTurn | None" = None,
    recorder: "BurstRecorder | None" = None,
) -> Any:
    """Drives one `graph.astream()` call and yields SSE frames.

    An **async generator** since `async-first/02`, driving `astream` directly
    rather than a sync `stream` pushed through `iterate_in_threadpool`. That
    buys no cancellation on its own and the phase's ticket is explicit about
    it: a sync node under `astream` still runs in a worker thread and still
    cannot be interrupted. This is the seam the per-node migration needs, not
    the win itself.

    `audience` decides only what the **terminal** `done` frame carries beyond
    the answer — see `api/audience.py`. It deliberately does not branch the
    fold: the suggestion fence is split out of the answer on every run,
    whatever the audience, so there is no code path that could put developer
    guidance in a customer's `answer` and none to keep audited.

    `document` and `store` are what the terminal frame's diagram needs and
    nothing else: the outermost document supplies the titles a customer reads,
    and the store loads a mounted child's own document so a node three levels
    down carries the name *its* author gave it. Both default to `None`, which
    draws exactly what LangGraph holds — the honest picture for a caller that
    has neither.

    Shared by `/api/runs/stream` (a fresh run) and `/api/runs/resume` (a
    run a `human.approval` node paused) — from the frontend's point of
    view a resume is not a different kind of thing, it is the same stream
    picking back up with a `Command(resume=...)` for `graph_input` instead
    of the initial state dict, so both endpoints reuse this one generator
    and the client's SSE parsing never needs to know which one it got.

    After the stream ends, `graph.get_state(config).next` tells apart "the
    run actually finished" (empty — nothing left scheduled) from "a
    `human.approval` node paused it" (non-empty — LangGraph does not raise
    or emit an `updates` chunk for the interrupted node itself, since it
    never completed; the loop above just stops, indistinguishable from a
    normal finish without this check).

    Raises rather than reporting: turning an exception into an `error` frame
    is `_stream_run`'s job, and doing it in both places is two spellings of
    one failure.
    """
    from openstategraph.compile.node_runtime import RESET, keep_latest_nonempty
    from openstategraph.run_identity import run_identity

    # The turn this run is being written down in — opened and closed by
    # `_stream_run`, which is the frame with a real `finally`, and recorded
    # here, which is the frame that holds the state (`memory-and-replay` 44).
    # A caller driving this generator directly gets a turn that writes nothing,
    # so a scripted fold in a test records no run.
    turn = turn if turn is not None else RunTurn(silent=True)

    answer = ""
    spawns = SpawnWatcher(node_ids_by_name)
    active = ActiveNodeResolver(node_ids_by_name)
    # Which of this graph's nodes a stop actually cancels, in canvas ids,
    # resolved once per run rather than per frame (`async-first/07`). Asked of
    # the compiled graph rather than of the document, because the answer is a
    # property of the door the compiler installed and of nothing a card
    # declares. A graph that cannot be asked answers `set()`, so every node
    # keeps the claim a stopped run has always made.
    cancels = {
        node_ids_by_name.get(name, name) for name in interruptible_nodes(graph)
    }

    def stop_cancels(active_node: str) -> bool:
        """Whether a stop right now cancels the node the run is *inside*.

        Keyed on `activeNode` and never on the frame's reporting node, which
        is the fix rather than the detail. A long agent step reports as
        `model`, `tools` or `NarrationMiddleware.before_model` — names that
        are not canvas nodes and match nothing — so keying on `node` answered
        `False` for every frame of exactly the steps this feature is about.
        Found live on 2026-08-27: a stop mid-fan-out logged *abandoned* while
        all three workers were in fact cancelled.
        """
        return active_node in cancels
    # Deliberately a **second, wider** map, never a replacement for the one
    # above. `ActiveNodeResolver` and the `internal` flag both mean "is this a
    # node of the document that was submitted", so widening their map with the
    # mounted children's ids would make the parent canvas glow on a card it
    # does not contain — the exact behaviour ticket 01 fixed. `path` asks a
    # different question ("which card, on whichever canvas") and needs the
    # wider answer. `getattr` because the fold is also driven by scripted
    # stubs, which declare no runtime names and degrade to the parent's.
    names = getattr(runtime, "names", None)
    run_path = RunPathResolver(
        {**(dict(names.node_ids_by_name) if names else {}), **node_ids_by_name},
        dict(names.mount_slugs) if names else {},
        run_identity(config).get("workflow_slug", ""),
    )
    # `dict.values()` is a *view*, so `x in view` is a linear scan. Asking it
    # once per update frame made "is this an internal step" O(canvas nodes)
    # per frame; the mapping never changes during a run, so the set is built
    # once here instead.
    canvas_node_ids = set(node_ids_by_name.values())
    decisions: dict[str, str] = {}
    # Force-passed graders (`every-workflow-green` 09), accumulated like the
    # two above so the terminal frame can report them.
    forced: dict[str, str] = {}
    #: Graders that stopped revising because the **step budget** was nearly
    #: spent (`organisms-first-class` 56). Folded like `forced`, and its own
    #: accumulator for the reason it is its own state key: the two ceilings
    #: are different facts with different fixes. The value is a superstep
    #: count, so it is carried whole rather than stringified.
    budget_stops: dict[str, Any] = {}
    #: Graders whose `revise` verdict named no wired edge (`workflow-gallery`
    #: 31). Folded exactly like `forced` — this door has no finished state to
    #: read, so the terminal frame is assembled from what went past.
    unrouted: dict[str, str] = {}
    #: agent node id -> tool names the runtime refused. Folded like `forced`,
    #: and read at the end to offer a capability the model did not ask for in
    #: words (`every-workflow-green` 33).
    unmet_tools: dict[str, Any] = {}
    #: node id -> `{"bound": [...], "ran": [...]}`. Folded like `unmet_tools`,
    #: and read by `capability_door`: a run that had tools and used none is
    #: offered the build door even when the model announced nothing
    #: (`every-workflow-green` 35).
    tool_use: dict[str, Any] = {}
    #: node id -> the attempt number that finally returned. Folded like
    #: `tool_use`, and the reason this door stopped listing `run_health`'s
    #: sources by hand: it was the only one of six this door never collected,
    #: so a recovered retry was reported by the other two doors and not by the
    #: one both shipped UIs read (`production-ready` 97).
    retries: dict[str, Any] = {}
    outputs: dict[str, str] = {}
    #: The same two, for everything below the outermost document — keyed by
    #: mount path (`wf-music/agent-sql`), which is the vocabulary the frames'
    #: `path`, the address bar and `MountAddress` already use. Additive, so a
    #: client that reads only the flat pair sees what it always saw, minus the
    #: collisions (ticket 40).
    nested_decisions: dict[str, str] = {}
    nested_outputs: dict[str, str] = {}
    #: Guardrail node id -> what its policy did. Accumulated exactly as
    #: `decisions` is, and flat rather than split by mount depth: a redaction
    #: inside a mounted child is still a redaction from this run's answer, and
    #: the developer reading it wants the total, not a tree.
    redactions: dict[str, Any] = {}
    attempts = 0

    # **The terminal frame reports the run, not this segment** — ticket 25.
    #
    # Everything above is filled from the `update` frames of *this* call, and a
    # resume is a new call: a run that paused for an approval reported
    # `attempts: 0` with the drafting node's output missing from `outputs`,
    # while `/api/runs` — which builds its `RunResponse` from `invoke`'s final
    # state — reported both. Two doors, one run, different answers.
    #
    # The streaming *frames* stay per-segment on purpose: a client watching a
    # resumed run must not be re-sent the first half's tokens. It is only the
    # accumulators the `done` frame is assembled from that are seeded, from the
    # checkpointed state — the same state `openstategraph threads show` reads.
    # Seeded *before* the fold, so this call's own frames still win where they
    # overlap.
    #: **State key -> the accumulator this door folds it into**, and the reason
    #: it is one mapping rather than two lists: the resume seed reads it, and
    #: so does the terminal frame's health report. `run_health_from_state`
    #: takes its sources off `run_health`'s own signature, so handing it this
    #: mapping is what stops this door falling behind a seventh source the way
    #: it fell behind `retries` (`production-ready` 97) — the sixth, after
    #: `every-workflow-green` 14 and 16 and `workflow-gallery` 49 fixed the
    #: same drift for the other two doors. Keys this door folds that are not
    #: health sources (`decisions`, `unmet_tools`, `redactions`) are simply not
    #: read by that function; the mapping is the door's, not the report's.
    folded: dict[str, Any] = {
        "decisions": decisions,
        "outputs": outputs,
        "nested_outputs": nested_outputs,
        "forced": forced,
        "unrouted": unrouted,
        "retries": retries,
        "unmet_tools": unmet_tools,
        "tool_use": tool_use,
        "redactions": redactions,
        "budget_stops": budget_stops,
    }
    if _resumes_a_paused_run(graph_input):
        prior = getattr(await graph.aget_state(config), "values", None) or {}
        if hasattr(prior, "get"):
            for state_key, target in folded.items():
                held = prior.get(state_key)
                if not isinstance(held, dict):
                    continue
                # Each map is seeded in the shape the fold gives it, never a
                # third shape: the two output maps are cleaned (a value that is
                # clean on one path and not the other is the leak that seam
                # exists to remove), the label maps are stringified as the fold
                # stringifies them, and the record maps are carried whole.
                if state_key.endswith("outputs"):
                    coerce = lambda v: str(_clean_output(str(v)))  # noqa: E731
                elif state_key in ("decisions", "forced", "unrouted"):
                    coerce = str
                else:
                    coerce = lambda v: v  # noqa: E731
                target.update(
                    {str(k): coerce(v) for k, v in held.items() if k != RESET}
                )
            answer = keep_latest_nonempty(answer, str(prior.get("answer") or ""))
            with suppress(TypeError, ValueError):
                attempts = max(attempts, int(prior.get("attempts") or 0))
    # One guard per streamed text — per node, per message kind — because each
    # is its own sequence of chunks and a shared tail would splice two
    # unrelated streams together. See `ProseGuard`: the settled answer is
    # cleaned at the end, but `token` frames reach a client while the model is
    # still typing, and that is the half a `done`-frame fix cannot reach.
    #: Keyed by node, message kind **and content block** (ticket 23): a
    #: model's reasoning and its answer are two independent sequences of
    #: chunks arriving interleaved, so one guard across both would carry a
    #: partial fence out of the thinking and splice it into the reply.
    guards: dict[tuple[str, str, str], ProseGuard] = {}
    # The streaming half of the audience boundary that `ProseGuard` could not
    # reach (ticket 25). `ProseGuard` polices a marker *inside* model prose;
    # this decides whether the text is prose at all — a tool's raw payload, a
    # classifier's branch name and a grader's verdict are none of them the
    # reply, and a customer watched all three appear in the answer area.
    #
    # Built from what the runtime declared rather than from a list here:
    # `NodeRuntime.machinery_nodes` is computed from node types and unioned up
    # from every mounted child. `getattr` because the fold is also driven by
    # scripted stubs, and a stub that declares nothing must degrade to the
    # `kind` test rather than crash.
    answer_channel = AnswerChannel(
        machinery=frozenset(getattr(runtime, "machinery_nodes", None) or ())
    )

    stream = None
    try:
        # `None` means *pass no argument at all*: a workflow that declares no
        # run context must stream exactly as it did before this existed, and
        # `None` and absent are not guaranteed to be the same thing to a
        # library we do not own (`organisms-first-class` 70).
        supplied = {"context": run_context} if run_context is not None else {}
        stream = graph.astream(
            graph_input,
            config,
            **supplied,
            # `custom` is what lets a step say "read 40 of 100" while it works
            # (ticket 22). Purely additive: a run whose tools write nothing
            # produces not one extra frame. Note it is a **shared** channel —
            # see `openstategraph.progress` for why an envelope is required
            # before anything on it reaches a person.
            stream_mode=["updates", "messages", "custom"],
            # Verbatim from the doc, and not to be disturbed: without it,
            # `stream_mode="messages"` on the parent graph will not emit token
            # chunks from the inner agent's LLM calls.
            subgraphs=True,
            # One chunk shape whatever we ask for — see `_stream_parts`.
            # Checked against the installed LangGraph 1.2.10 rather than taken
            # from the page, because the page does not say the thing that
            # decides whether this is a decode change or a contract change:
            # `pregel/_messages.py` attaches the content-block messages
            # handler only when an internal config key opts in, and states
            # that "direct `graph.stream(stream_mode="messages")` callers keep
            # the v1 AIMessageChunk shape". So the envelope moves and the
            # `messages` payload does not.
            version="v2",
        )
        async for chunk in stream:
            decoded = _stream_part(chunk)
            if decoded is None:
                continue
            namespace, mode, payload = decoded
            if mode == "updates":
                for raw_name, raw_update in payload.items():
                    update = _coerce_update(raw_update)
                    node_id = node_ids_by_name.get(raw_name, raw_name)
                    # `RESET` stripped here for the same reason it is stripped
                    # from `decisions` and `outputs` below — a mounted child
                    # runs its own `input.text`, so the marker arrives mid-run
                    # — but the consequence is worse on this channel: the
                    # other two merely ignore it, while `keep_latest_nonempty`
                    # *clears* on it by design. One child frame therefore wiped
                    # an answer the fold had already collected. `concierge`
                    # masks it (its mount runs before `out1`, which writes the
                    # answer again); agent → mount loses it outright.
                    #
                    # The fold is per-run, so it needs no turn reset at all:
                    # the parent's own `_input` fires before anything has been
                    # accumulated.
                    incoming = str(update.get("answer") or "")
                    if incoming != RESET:
                        answer = keep_latest_nonempty(answer, incoming)
                    # Strip the turn-reset marker before accumulating: this
                    # dict is per-run (it needs no reset), and a mounted
                    # child workflow's OWN input node emits the marker too —
                    # merged verbatim it would wipe the parent's already-
                    # collected decisions (the router branch showed as None
                    # whenever a subgraph ran after it, found live).
                    #
                    # Accumulated in place rather than through
                    # `merge_decisions`: that reducer returns `{**left,
                    # **right}`, so every frame rebuilt the whole dict —
                    # O(frames x distinct nodes) over a run, twice per frame.
                    # The two behaviours it adds over `dict.update` are the
                    # RESET short-circuit and left-then-right precedence;
                    # RESET is already stripped by the comprehensions below,
                    # so only the precedence remains, and that is exactly
                    # `update`. These dicts are local to this fold and are
                    # read once at the end (the `complete` frame), never
                    # snapshotted per frame, so mutating them cannot alias.
                    # Which document this frame belongs to, as a mount chain
                    # (ticket 40). Resolved here rather than further down
                    # because the accumulators below need it: a node id is
                    # unique only *within* a document, and `concierge` and
                    # `chinook-assistant` ship sharing `in1`, `router1` and
                    # `out1`. Flat maps therefore let the child's values land
                    # on the parent's keys and the parent's own facts vanish —
                    # captured live as `decisions.router1 = "b-data"`, the
                    # child's branch, with the parent's `b-music` gone.
                    frame_path, frame_slugs = run_path.resolve(raw_name, namespace)
                    # The chain of mounts above this frame's own node. Empty
                    # for the outermost document, which is exactly the set the
                    # flat maps now hold.
                    prefix = "/".join(frame_path[:-1]) if len(frame_path) > 1 else ""
                    into_decisions = decisions if not prefix else nested_decisions
                    into_outputs = outputs if not prefix else nested_outputs
                    key = (lambda k: f"{prefix}/{k}") if prefix else (lambda k: k)

                    into_decisions.update(
                        {
                            key(k): str(v)
                            for k, v in (update.get("decisions") or {}).items()
                            if k != RESET
                        }
                    )
                    unmet_tools.update(
                        {key(k): v for k, v in (update.get("unmet_tools") or {}).items()}
                    )
                    tool_use.update(
                        {key(k): v for k, v in (update.get("tool_use") or {}).items()}
                    )
                    retries.update(
                        {key(k): v for k, v in (update.get("retries") or {}).items()}
                    )
                    forced.update(
                        {key(k): str(v) for k, v in (update.get("forced") or {}).items()}
                    )
                    budget_stops.update(
                        {key(k): v for k, v in (update.get("budget_stops") or {}).items()}
                    )
                    unrouted.update(
                        {key(k): str(v) for k, v in (update.get("unrouted") or {}).items()}
                    )
                    into_outputs.update(
                        {
                            # Cleaned as it is accumulated, not as it is sent:
                            # this dict reaches the `done` frame *and* every
                            # surface's per-node inspector, and a value that
                            # is clean on one path and not the other is the
                            # shape of leak this whole seam exists to remove.
                            key(k): str(_clean_output(str(v)))
                            for k, v in (update.get("outputs") or {}).items()
                            if k != RESET
                        }
                    )
                    redactions.update(
                        {
                            key(k): v
                            for k, v in (update.get("redactions") or {}).items()
                            if k != RESET
                        }
                    )
                    if "attempts" in update:
                        attempts = max(0, int(update["attempts"]))
                    task_ids = list((update.get("worker_results") or {}).keys())
                    # Internal frames — `model`, `tools`, a middleware's own
                    # node — are real LangGraph steps inside an agent's
                    # compiled loop, but not canvas nodes. They are emitted
                    # *tagged* (`internal: true`) rather than dropped: the
                    # flat activity feed ignores them, and the trace tree
                    # (ticket 63) nests them under their owning canvas node —
                    # which is exactly where a LangSmith-style view wants
                    # them.
                    #
                    # A namespace is itself proof of internality, and the name
                    # alone is not enough (ticket 02). A namespaced frame comes
                    # from a nested graph — an agent's compiled loop or a
                    # mounted child document — so it is never a step of THIS
                    # canvas, whatever it happens to be called. Names collide
                    # across documents freely: `chinook-assistant` mounts
                    # `chinook-assistant`, and both have an `in1` and an `out1`.
                    # On the name test alone the child's own input and output
                    # steps came back `internal: false` and posted a second
                    # `in1` row to the activity feed halfway through the run,
                    # as though the parent's input node had run twice. (Latent
                    # until now only because the child's frames were not
                    # reaching this stream at all — see `NodeRuntime._subgraph`.)
                    is_internal = bool(namespace) or node_id not in canvas_node_ids
                    # The spawn moment is emitted *before* the frame that
                    # revealed it, so a child's own steps read as arriving
                    # after the row that announced it.
                    #
                    # TODO(future, deliberately not built): a spawn-confirmation
                    # gate would hook exactly here — `interrupt({...spawn})`
                    # before yielding, turning fire-and-run into ask-first.
                    # Default behaviour stays fire-and-run; nothing below
                    # blocks.
                    update_path, update_slugs = frame_path, frame_slugs
                    # The key this frame's own output is stored under, which is
                    # NOT `node_id`. `node_id` comes from the narrow map — the
                    # ids of the document the run was launched against — and
                    # that narrowness is deliberate for `node`/`activeNode`
                    # (ticket 01: a parent canvas must not glow on a card it
                    # does not contain). But the update dict being read here
                    # belongs to whichever document produced the frame, and its
                    # keys are *that* document's canvas ids, so a child's
                    # `agent-sql` was looked up as the mangled `agent_sql` and
                    # every mounted node reported `null`. `path` already
                    # resolves ids across every document in the run, and its
                    # last entry is this frame's own card.
                    output_id = update_path[-1] if update_path else node_id
                    for spawn in spawns.inspect(node_id, namespace, update, is_internal):
                        yield _sse("spawn", spawn)
                    # Which of a grader's two paths this frame is
                    # (`production-ready` 92). `BaseGrader.grade` rejects an
                    # empty candidate, or one beginning
                    # `Error`/`Traceback`/`Exception`, *before* reaching
                    # `self.model.invoke` — 0.021 ms against two seconds for a
                    # judged verdict — and until now the frame said nothing
                    # about it, so a reader looking at a grader row that
                    # returned instantly had only one available explanation and
                    # it was the wrong one (ticket 84).
                    #
                    # Absent together, like `withheld` on a token frame, and
                    # absence is the value: it says no deterministic check
                    # fired, which covers both an ordinary pass and a model's
                    # rejection. Only their presence is a claim.
                    #
                    # `reason` rides with it because `check` is an internal
                    # token — an open set, since a subclass overriding
                    # `deterministic_checks` names its own — so no client may
                    # turn it into a sentence. The sentence is `reason`, which
                    # the grader already wrote for a human reading a trace.
                    # Cleaned like every other prose field on this frame.
                    verdict_row = (update.get("verdicts") or {}).get(output_id)
                    skipped_check: dict[str, str] = {}
                    if isinstance(verdict_row, dict) and verdict_row.get("check"):
                        skipped_check = {
                            "check": str(verdict_row["check"]),
                            "reason": _redact_for(audience)(
                                _clean_output(str(verdict_row.get("reason") or ""))
                            )
                            or "",
                        }
                    update_active = active.resolve(node_id, namespace)
                    yield _sse(
                        "update",
                        {
                            "node": node_id,
                            "namespace": list(namespace),
                            "taskId": customer_task_id(
                                task_ids[0] if task_ids else None, audience
                            ),
                            "internal": is_internal,
                            # Additive (ticket 01): the canvas node a client
                            # should show as running for this frame. Both
                            # surfaces read it instead of guessing; an older
                            # client that ignores it behaves exactly as before.
                            "activeNode": update_active,
                            # See `stop_cancels`.
                            "interruptible": stop_cancels(update_active),
                            # Where this frame is on *every* canvas it touches,
                            # outermost document first — see `RunPathResolver`.
                            # `activeNode` is this list's first entry whenever
                            # both are non-empty; the rest is what an editor
                            # showing a mounted child needs and could not get.
                            "path": update_path,
                            # Which document each of those ids belongs to.
                            # Same length as `path`; ids alone are ambiguous
                            # across documents that share them.
                            "pathSlugs": update_slugs,
                            # Split like the final answer, and for the same
                            # reason: this is a node's own settled output and
                            # both surfaces render it in their trace.
                            # Redacted for a customer for the same reason the
                            # terminal frame's `outputs` is: a failure marker
                            # names an environment variable and a file, and a
                            # live trace frame is as much a surface as the
                            # final one (ticket 04).
                            "output": _redact_for(audience)(
                                _clean_output(
                                    (update.get("outputs") or {}).get(output_id)
                                    or (update.get("worker_results") or {}).get(
                                        task_ids[0] if task_ids else "", None
                                    )
                                )
                            ),
                            **skipped_check,
                        },
                    )
            elif mode == "custom":
                # A step saying something about itself mid-execution (22).
                #
                # `custom` is a channel LangGraph gives to everyone, so this
                # reads only what carries our envelope and steps over the
                # rest — deepagents and any middleware may be writing here
                # too, and rendering a stranger's dict as a user's status line
                # is the same leak as rendering a tool's payload as prose.
                # `progress_report` is total: anything it cannot read is None.
                report = progress_report(payload)
                if report is None:
                    continue
                # Resolved exactly as a `token` frame's are, and by the same
                # instances, so one honest sequence comes off the wire. The
                # writer is ambient — the payload cannot name its own canvas
                # id — so the node it stamped is mapped here like any other
                # graph-step name.
                progress_node = node_ids_by_name.get(report.node, report.node)
                progress_path, progress_slugs = run_path.resolve(report.node, namespace)
                progress_active = active.resolve(progress_node, namespace)
                yield _sse(
                    "progress",
                    {
                        "node": progress_node,
                        "namespace": list(namespace),
                        # Developer-authored copy, addressed to whoever is
                        # watching. Unlike a tool's *name* or its payload,
                        # this text was written to be read by the person
                        # running the workflow, so it crosses to a customer
                        # intact — a silent forty-second gap is worse for the
                        # audience that cannot open a trace to explain it.
                        "message": report.message,
                        # The evidence behind that message, in the words of
                        # whatever produced it — **developer only**
                        # (`launch-readiness/163`).
                        #
                        # The line above is composed under `143`'s customer
                        # seam, where no value from a result is interpolated
                        # and only integers are spoken, which is why a failed
                        # query says "That did not work." and nothing more.
                        # Right for a customer, useless for the person who can
                        # fix the workflow: the owner watched six of those and
                        # had to paste the raw payload into a chat before
                        # anybody could see `Invalid column name
                        # 'loading_time'`.
                        #
                        # So the split is made here, once, at the seam that
                        # already redacts per audience — not by widening the
                        # sentence, which would put a driver's message on
                        # every surface. `None` for a customer, and `None`
                        # for the overwhelming majority of developer frames
                        # too: nothing invents evidence it does not have.
                        "detail": (
                            report.detail if audience is Audience.DEVELOPER else None
                        ),
                        "current": report.current,
                        "total": report.total,
                        "activeNode": progress_active,
                        "interruptible": stop_cancels(progress_active),
                        "path": progress_path,
                        "pathSlugs": progress_slugs,
                    },
                )
            elif mode == "messages":
                message, metadata = payload
                # Block-shaped chunks are what a provider actually streams once
                # `"messages"` is in `stream_mode`. Gating on `isinstance(str)`
                # dropped them all: no live text, and the flow diagram never
                # lit up. See `openstategraph.messages`.
                raw_content = getattr(message, "content", "")
                content = content_text(raw_content)
                # The half of the same content list `content_text` drops on
                # purpose (ticket 23). A thinking model puts its deliberation
                # and its answer in one chunk, so until now they were one
                # frame kind and no client could tell them apart — while
                # reasoning effort has been a per-node field all along.
                thinking = reasoning_text(raw_content)
                # `message-finish` in the docs' vocabulary. It arrives on the
                # LAST chunk of a message, whose content is empty — which is
                # exactly why no usage ever reached a client: the gate below
                # used to read `if content:` and dropped the one frame
                # carrying the numbers.
                usage = usage_of(message)
                # The record is not a token — see `is_transcript_record`. Usage
                # still passes: it rides the last chunk of a message, and that
                # chunk is a chunk.
                if is_transcript_record(message) and not usage:
                    continue
                if content or thinking or usage:
                    raw_name = metadata.get("langgraph_node", "")
                    token_node = node_ids_by_name.get(raw_name, raw_name)
                    kind = "tool" if _is_tool_message(message) else "ai"
                    # Resolved for EVERY frame, above the gate, and only then
                    # is the frame's fate decided. The resolver's whole value
                    # is its stickiness (`ActiveNodeResolver`), so feeding it a
                    # customer-shaped subset of the run would make the two
                    # audiences disagree about where the run is — and the
                    # audience boundary is about what is *shown*, never about
                    # what is *known* server-side.
                    active_node = active.resolve(token_node, namespace)
                    token_path, token_slugs = run_path.resolve(raw_name, namespace)
                    # The rest of the streaming boundary (ticket 25). A
                    # customer's token stream carries the reply and nothing
                    # that produced it: no tool payload, no branch name, no
                    # verdict, no echo of their own question. A developer's
                    # carries everything — `AskPanel` folds tool frames into
                    # its per-call result cards, so gating them for both
                    # audiences would delete a feature rather than move it.
                    withheld = (
                        audience is not Audience.DEVELOPER
                        and not answer_channel.carries(token_node, kind, namespace)
                    )
                    # Cost is developer material, by the same rule that blanks
                    # a tool's NAME on this frame — and gated on the audience
                    # rather than on `withheld`, because an agent's own tokens
                    # ARE carried to a customer while what they cost is not.
                    shown_usage = usage if audience is Audience.DEVELOPER else None
                    common = {
                        "node": token_node,
                        "namespace": list(namespace),
                        "activeNode": active_node,
                        "interruptible": stop_cancels(active_node),
                        "path": token_path,
                        "pathSlugs": token_slugs,
                        "kind": kind,
                        "message": message,
                        "withheld": withheld,
                    }

                    # Reasoning first, because that is the order it was
                    # produced in: a model deliberates and then answers.
                    #
                    # **Dropped, not emptied, for a customer** — the opposite
                    # of the withheld text frame below, and deliberately so.
                    # That frame is kept because it is the only carrier of
                    # `activeNode` while a node works; a reasoning frame is
                    # always accompanied by that node's own text frames, which
                    # carry it already. So a customer's stream is byte for
                    # byte what it was before this ticket, and the rule
                    # `content_text` states in its docstring — that blindly
                    # concatenating would hand a customer the model's private
                    # deliberation as if it were the answer — survives being
                    # made visible to developers.
                    if thinking and audience is Audience.DEVELOPER:
                        # Its own guard instance: reasoning and answer are two
                        # sequences of chunks, and a shared fence tail would
                        # splice one into the other — the same reason the
                        # guard was already keyed per node and per kind.
                        guard = guards.setdefault((token_node, kind, "reasoning"), ProseGuard())
                        shown = guard.feed(thinking)
                        if shown:
                            yield _token_frame(common, "reasoning", shown, None)

                    text = content
                    if withheld:
                        # Emptied, **not dropped**, and the difference was
                        # measured rather than reasoned about. Dropping the
                        # frame drops its `activeNode` with it, and `token` is
                        # the only frame that arrives mid-node (ticket 02) — a
                        # customer watching the live flow diagram then saw the
                        # ring sit on `router1` for the eleven seconds the
                        # mounted analyst was working, which is precisely the
                        # bug ticket 02 fixed, reintroduced for the one
                        # audience that cannot open a trace to work it out.
                        #
                        # So the frame keeps saying *where* the run is and
                        # stops saying what was said. That is not the "empty
                        # token is a lie" case below: this frame states its own
                        # emptiness (`withheld`), rather than implying a model
                        # produced nothing. A client that has never heard of
                        # the field concatenates `""` and is correct anyway,
                        # which is the property that makes this a boundary —
                        # the bytes do not reach the browser at all.
                        text = ""
                    elif text:
                        # A frame whose whole content was fence is dropped
                        # rather than sent empty: an empty `token` there says
                        # "the model produced nothing just then", a lie.
                        guard = guards.setdefault((token_node, kind, "text"), ProseGuard())
                        text = guard.feed(text)

                    # Three reasons to send a text frame, and no others:
                    # it has something to say; it settles the message and
                    # carries what that cost; or it states its own withheld
                    # emptiness. A chunk that is none of the three is the lie
                    # above and stays dropped.
                    if text or shown_usage or (withheld and content):
                        yield _token_frame(common, "text", text, shown_usage)
    except (GraphRecursionError, StepBudgetExhausted) as exc:
        # **The one door that does not go through the blocking driver**
        # (`launch-readiness/176`). Every other door reaches the graph through
        # `run_doors.invoke_run`, where the same translation lives; this one
        # drives `astream` itself, so LangGraph's exhaustion surfaces here or
        # nowhere — and until this it surfaced whole, `describe_failure` in
        # `_stream_run` handing a developer `GraphRecursionError:` plus a
        # vendor URL.
        #
        # The row is written from the fold's own accumulators, exactly as the
        # stop handler below writes its own: this door has no returned state,
        # and what it *does* have is more than the blocking driver ever sees —
        # the answer a candidate node had already produced, and the laps the
        # grader had already taken.
        #
        # Re-raised rather than turned into a frame here: `_stream_run` owns
        # the one place an exception becomes an `error` frame, and it already
        # renders our own errors as the copy for a developer and the generic
        # sentence for a customer.
        raise budget_exhausted(
            exc,
            budget=(config or {}).get("recursion_limit"),
            workflow=str(run_identity(config).get("workflow_slug") or ""),
            state=dict(folded, attempts=attempts, answer=answer),
            turn=turn,
        ) from exc
    except (GeneratorExit, asyncio.CancelledError):
        # **Stop, or a closed tab — and it is still a row** (`44`).
        #
        # Nothing may be *yielded* from here (see `_stream_run`), but writing
        # is not yielding, and this is the row `guardrails/07` most needs: the
        # provider call already issued is still billed, and Stop is exactly
        # what a person presses when a run is costing money.
        #
        # `kind="stopped"`, not `failed=True` and not a plain run. `failed`
        # means a node wrote the failure sentinel, and calling an abandoned
        # run failed would corrupt every failure rate read out of this table;
        # calling it a finished turn would hand `launch-readiness/99` half a
        # sentence to learn from. A kind is the one of the three that costs no
        # existing sink anything — which is why `RunRecord.kind` is a tolerant
        # string rather than a `Literal`.
        turn.record(
            dict(folded, attempts=attempts, answer=answer),
            warnings=_built_warnings(plan, runtime),
            kind=STOPPED_KIND,
            # A stopped run keeps its cadence too — it is the row that says
            # *how far it got before the reader walked away*, which is exactly
            # what a stopped run is asked afterwards.
            bursts=recorder.bursts() if recorder else None,
        )
        raise
    finally:
        # Explicit, not left to refcounting. CPython happens to close the
        # inner generator when this frame is destroyed, but "happens to" is
        # not a contract, and under a stop the checkpointer/DB handles the
        # LangGraph stream holds should be released at a defined moment
        # rather than at the collector's convenience.
        # `aclose()` since the drive went async, and `CancelledError`
        # suppressed beside `Exception` for the reason `_stream_run`'s own
        # close gives: this runs while a cancelled task unwinds, where the
        # first `await` re-raises, and the close would then be skipped on
        # exactly the path it exists for.
        closer = getattr(stream, "aclose", None)
        if callable(closer):
            with suppress(Exception, asyncio.CancelledError):
                await closer()

    snapshot = await graph.aget_state(config)
    # **Above the pause branch, and the door's only terminal record** — a turn
    # that ended at a gate is a turn that happened, and the library door has
    # always written one. `record` is idempotent, so the stop handler above and
    # this line cannot both produce a row.
    #
    # The state handed over is the fold's own accumulators, which is what this
    # door has instead of a returned `RunResult`: `folded` is already the
    # mapping `run_health_from_state` reads below, and `attempts`/`answer` are
    # the two the fold keeps as scalars.
    turn.record(
        dict(folded, attempts=attempts, answer=answer),
        warnings=_built_warnings(plan, runtime),
        bursts=recorder.bursts() if recorder else None,
    )
    if snapshot.next:
        interrupts = snapshot.tasks[0].interrupts if snapshot.tasks else ()
        payload_value = interrupts[0].value if interrupts else {}
        # Which node is waiting, not merely that something is. `snapshot.next`
        # is the scheduled-but-not-run node — precisely the one that called
        # `interrupt()` — mapped back to a canvas id like every other frame.
        # Without it a surface can only mark the last node that *reported*,
        # which is the node before the approval: found live on `/chat`, where
        # the paused ring landed on `in1` while `approve1` was waiting.
        paused = [node_ids_by_name.get(name, name) for name in (snapshot.next or ())]
        yield _sse(
            "interrupt",
            {
                "threadId": thread_id,
                "node": paused[0] if paused else "",
                "message": (payload_value or {}).get("message", "Approval needed"),
                # Cleaned too: a `human.approval` node shows the customer
                # the candidate text a model produced, so it is prose on a
                # customer surface exactly like `answer` is.
                "candidate": _clean_output((payload_value or {}).get("candidate", "")) or "",
                # What the grader immediately upstream thought of that exact
                # text (`workflow-gallery` 32). Optional, like `withheld` on a
                # token frame: both keys are absent together when no grader
                # produced the candidate, and absence is the value — it says no
                # machine opinion exists, not that the machine said nothing.
                #
                # The reason is model prose on the same surface as the
                # candidate, so it is cleaned the same way.
                **(
                    {
                        "verdict": str((payload_value or {}).get("verdict") or ""),
                        "reason": _clean_output(
                            str((payload_value or {}).get("reason") or "")
                        )
                        or "",
                        # And, when the judgement cost no model call, which
                        # check made it (`production-ready` 92). Same door,
                        # same fact as the trace's own row: a reviewer told
                        # "the grader asked for a revision" deserves to know
                        # whether a model formed that opinion. Present only
                        # when one fired — `_upstream_verdict` omits the key
                        # otherwise.
                        **(
                            {"check": str((payload_value or {}).get("check") or "")}
                            if (payload_value or {}).get("check")
                            else {}
                        ),
                    }
                    if (payload_value or {}).get("verdict")
                    else {}
                ),
            },
        )
        return

    # Unconditional, and above the audience check on purpose: this is what
    # makes "a developer-only payload cannot appear in a customer answer" a
    # property of the code rather than of the client that reads it.
    prose, suggestion = split_suggestion(answer)
    from openstategraph.compile.workflow_compiler import (
        RUN_FAILED_ANSWER,
        redact_failure_markers,
        capability_door,
        run_health_from_state,
        suggestion_from_rejection,
    )

    # One assembly for all three doors — see `run_health`. Neither endpoint
    # adds a source locally; that is exactly how these drifted twice
    # (`every-workflow-green` 14, 16).
    #
    # **Off the signature, not by hand.** This door used to call `run_health`
    # positionally, which made it the one door that could silently fall behind
    # — and it had: `retries` was passed as `None` because the fold never
    # collected it, so a recovered retry reached `/api/runs` and the library
    # door and never the door both shipped UIs read (`production-ready` 97).
    # `folded` is keyed by state key, so a seventh source arriving as a
    # `run_health` parameter is either folded here or a red test
    # (`test_the_streaming_door_cannot_fall_behind_a_health_source`), never a
    # missing sentence nobody notices.
    health = run_health_from_state(folded)
    # A fallback, never an override: the model's own fence wins when it wrote
    # one (ticket 15's card), and this fills the silence when it did not.
    if suggestion is None:
        suggestion = suggestion_from_rejection(unmet_tools)
    failures = health.failures
    # The capabilities that did not reach this run, kept as their own list —
    # ticket 51. `failures` are a *step* that broke while running and already
    # have their own customer-facing floor below (`RUN_FAILED_ANSWER`); these
    # are a capability that never bound at all, which is the case where the run
    # succeeds, reads confident, and is quietly worse than it looks.
    # Nodes that ran and produced nothing — `every-workflow-green` 01. Beside
    # `failures` rather than inside them: a silent node is a report about how
    # the answer was reached, not a claim the run failed, and only the latter
    # may reach the CLI's exit code.
    silent = health.silent
    degraded = list(plan.warnings) + runtime_warnings(runtime)
    channel = DeveloperChannel(
        warnings=degraded
        + silent
        # Both doors report it, or `/api/runs` becomes the only one telling
        # the truth — see the same promotion in `api/main.py` (ticket 04).
        + failures,
        suggestion=suggestion,
        # Only when nothing could be placed: a gap with a tool that fits is a
        # suggestion, not something to build (`every-workflow-green` 34).
        # One verdict, both doors — `capability_door`. Neither endpoint asks
        # this locally: the model's own decline wins when it wrote one, and the
        # run's shape fills the silence when it did not
        # (`every-workflow-green` 35).
        capability_gap=capability_door(answer, suggestion, tool_use),
        redactions=redaction_report(redactions),
        # The same read as the blocking door's (`one-chinook-honest/30`), off
        # the `tool_use` this door already folded out of the frames.
        statements=statements_executed(tool_use),
    )

    # A step failed and no answer was produced; see `RUN_FAILED_ANSWER` for
    # why `node_runtime`'s never-blank floor cannot reach this case. And the
    # marker is developer guidance, so it leaves a customer's `outputs` too.
    if not prose.strip() and failures:
        prose = RUN_FAILED_ANSWER
    # **Ticket 51 — the customer's half of the capability report.**
    #
    # A degraded run used to reach `/chat` as a confident answer with nothing
    # to suggest a tool was missing, so the only explanation available to the
    # reader was that the product does not know things. It rides `answer`
    # rather than a new field or a new frame, and that is a constraint rather
    # than a shortcut: `done` may not grow a `warnings` key on a customer run
    # (`test_audience_boundary.py` requires it *absent*), and a field only
    # reaches clients that grow a branch for it while `answer` is what every
    # customer surface already renders. `with_capability_notice` owns the
    # audience split; a developer gets the sentences themselves instead.
    prose = with_capability_notice(prose, degraded, audience)
    if not channel.payload(audience).get("developer"):
        outputs = redact_failure_markers(outputs)
        nested_outputs = redact_failure_markers(nested_outputs)

    yield _sse(
        "done",
        {
            # The thread this run happened in — on every terminal frame, not
            # only on `interrupt` (ticket 11). A thread IS the conversation:
            # `messages` accumulates in it, and every conversation-aware node
            # this runtime has (`_thread_question`'s history block, the
            # agent's `state["messages"]` payload, the mounted child's
            # dialogue hand-off) reads it from there. A client that omits
            # `thread_id` gets an invented one — and, until this line, had no
            # way to learn what it was, so it could never send a second turn
            # into the same conversation. That is not a theoretical gap: the
            # editor's Ask panel omits it, and the recorded four-turn run in
            # `tests/data/recorded_chinook_followup_thread.json` shows
            # "How did you get that?" reaching the router as that bare
            # sentence, with no antecedent, and being answered as if it were
            # a fresh question. The server mints the id, so the server owes
            # it back.
            "threadId": thread_id,
            "answer": prose,
            "decisions": decisions,
            "outputs": outputs,
            # Everything below the outermost document, keyed by mount path
            # (ticket 40). Always present, even when empty: a client that
            # reads it unconditionally should not have to special-case the
            # common single-document run.
            "nested": {"outputs": nested_outputs, "decisions": nested_decisions},
            "attempts": attempts,
            # Topology, not guidance, and `/chat` draws its live flow diagram
            # from it — `GET /api/workflows/{slug}/graph` already serves the
            # same text to that page. See the table in `api/audience.py`.
            # The composition, in this reader's own vocabulary. Until
            # `workflow-gallery` 62 this drew `graph.get_graph()
            # .draw_mermaid()`: a customer's terminal frame carried
            # `__start__`, `__default_error_handler__` and `safe_name`d ids,
            # and every mount as one box. The seam is shared with
            # `RunResponse.mermaid` and with the preview route, so a reader
            # who opens the preview and then runs the workflow is not shown
            # two shapes for one workflow.
            "mermaid": workflow_mermaid(
                graph, document, runtime=runtime, audience=audience, store=store
            ),
            # Both audiences, on purpose — `launch-readiness` 25, the same
            # fact `RunResponse.published_rejected` carries on `/api/runs`.
            # The grader's reason stays inside `channel.payload`'s
            # `developer` block; this is only whether it happened.
            "publishedRejected": health.published_rejected,
            **channel.payload(audience),
        },
    )


