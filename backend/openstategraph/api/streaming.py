"""SSE framing and the stream fold (ticket 72 split)."""

from __future__ import annotations

import json
import logging
from contextlib import suppress
from typing import Any

logger = logging.getLogger(__name__)

from openstategraph.api.audience import (  # noqa: E402
    AnswerChannel,
    Audience,
    DeveloperChannel,
    clean_output as _clean_output,
    split_suggestion,
)
from openstategraph.developer_channel import ProseGuard  # noqa: E402
from openstategraph.api.registries import runtime_warnings  # noqa: E402


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


def _is_tool_message(message: Any) -> bool:
    """Whether a streamed message is a tool's *result* rather than model text.

    Duck-typed on LangChain's own `type` discriminator rather than
    `isinstance(message, ToolMessage)`: the `messages` stream yields chunk
    classes (`ToolMessageChunk`) as well as settled messages, and both answer
    `"tool"` here, so one test covers the family without importing it.
    """
    return str(getattr(message, "type", "")) == "tool"


class SpawnWatcher:
    """Turns raw `updates` frames into *spawn* events — the moment a run
    creates a child worker or subagent.

    Three signals, because the runtime spawns in three structurally different
    ways and a user cannot be expected to know which one they are looking at:

    1. **Fan-out plan.** An orchestrator writes `subtasks[node_id] = [...]`
       and the conditional edge `Send`s one task each. The plan frame is the
       spawn moment — it names every child *before* any of them runs, with
       the instruction that was handed to it.
    2. **Deep-agent `task` tool call.** A deep agent spawns a subagent by
       calling its `task` tool; the call's arguments carry the subagent type
       and the task description. Detected on the agent's own model frame,
       which is where the tool call surfaces.
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
                if str(call.get("name") or "") != "task":
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
                        "kind": "subagent",
                        "parent": node_id,
                        "label": str(args.get("subagent_type") or "") or "subagent",
                        "instruction": _snippet(
                            args.get("description") or args.get("instruction")
                        ),
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


async def _client_left(receive: Any) -> None:
    """Resolves the moment the ASGI server reports the client is gone."""
    while True:
        message = await receive()
        if message.get("type") == "http.disconnect":
            return


def _abandon(task: Any) -> None:
    """Drops a task we are no longer waiting on, without a warning storm.

    A cancelled `__anext__` whose thread is still inside `graph.stream` does
    not finish immediately (a blocking call cannot be interrupted), so the
    task outlives us. Retrieving its outcome here is what stops asyncio
    logging "exception was never retrieved" for work nobody wanted.
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
    """
    import asyncio

    from starlette.concurrency import iterate_in_threadpool

    stream = iterate_in_threadpool(frames)
    gone = asyncio.ensure_future(_client_left(receive))
    try:
        while True:
            step = asyncio.ensure_future(stream.__anext__())
            done, _ = await asyncio.wait({step, gone}, return_when=asyncio.FIRST_COMPLETED)
            if step not in done:
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


def _sse(event: str, data: dict[str, Any]) -> str:
    """One Server-Sent Event frame: an `event:` line, a `data:` line, blank line.

    `json.dumps` rather than string interpolation, because a node's output can
    contain newlines and quotes, and SSE's `data:` line is newline-delimited —
    an unescaped newline would silently split one event into two.
    """
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


#: The event names that report progress. A client must keep waiting after
#: every one of them — none of these can be the last frame of a healthy run.
PROGRESS_EVENTS: tuple[str, ...] = ("update", "token", "spawn")

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


def _is_terminal(frame: str) -> bool:
    """True if this SSE frame is one of the three that end a stream."""
    return any(frame.startswith(f"event: {name}\n") for name in TERMINAL_EVENTS)


def _stream_run(
    graph: Any,
    graph_input: Any,
    config: dict[str, Any],
    plan: Any,
    node_ids_by_name: dict[str, str],
    runtime: Any,
    thread_id: str,
    audience: Audience = Audience.CUSTOMER,
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
    frames = _run_frames(
        graph, graph_input, config, plan, node_ids_by_name, runtime, thread_id, audience
    )
    ended = False
    try:
        for frame in frames:
            ended = ended or _is_terminal(frame)
            yield frame
    except GeneratorExit:
        # Stop, pressed, or the client hung up. Nothing may be yielded from
        # here — see the docstring. Logged rather than silent because "did the
        # run actually stop?" is otherwise unanswerable from outside, and a
        # Stop button whose effect cannot be observed is a fake cancel.
        #
        # The honest boundary, measured live against the Store Analytics crew
        # rather than assumed: `graph.stream` is a generator driven BY the
        # fold, so nothing further is *scheduled*. But tasks LangGraph already
        # dispatched for the current superstep run in its own executor, a
        # blocking model call cannot be interrupted, and closing the fold
        # drains them — an early stop trailed model calls for ~15s, a stop
        # mid-fan-out for ~75s, in both cases ending far short of the run
        # itself. Their results are discarded. There is no cancellation seam
        # inside a superstep at this version: `RunControl.request_drain()`
        # (langgraph 1.2) stops at exactly the same boundary.
        logger.info(
            "run stream stopped by the client (thread_id=%s) — no further supersteps",
            thread_id,
        )
        raise
    except Exception as exc:  # noqa: BLE001 — reported to the client, not swallowed
        # One place turns an exception into a frame, so there is one spelling
        # of a failed run no matter where in the pipeline it failed.
        if not ended:
            # `threadId` on the failure path too (ticket 11): the turn that
            # died is still checkpointed, and a client that wants to try again
            # in the *same* conversation needs to name the thread it was in.
            yield _sse(
                "error",
                {"threadId": thread_id, "detail": f"{type(exc).__name__}: {exc}"},
            )
        return
    finally:
        # Not left to refcounting: under a stop the checkpointer/DB handles
        # the LangGraph stream holds should be released at a defined moment
        # rather than at the collector's convenience. `close()` is idempotent,
        # so the normal path pays nothing for it.
        frames.close()

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


def _run_frames(
    graph: Any,
    graph_input: Any,
    config: dict[str, Any],
    plan: Any,
    node_ids_by_name: dict[str, str],
    runtime: Any,
    thread_id: str,
    audience: Audience = Audience.CUSTOMER,
) -> Any:
    """Drives one `graph.stream()` call and yields SSE frames.

    `audience` decides only what the **terminal** `done` frame carries beyond
    the answer — see `api/audience.py`. It deliberately does not branch the
    fold: the suggestion fence is split out of the answer on every run,
    whatever the audience, so there is no code path that could put developer
    guidance in a customer's `answer` and none to keep audited.

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

    answer = ""
    spawns = SpawnWatcher(node_ids_by_name)
    active = ActiveNodeResolver(node_ids_by_name)
    # `dict.values()` is a *view*, so `x in view` is a linear scan. Asking it
    # once per update frame made "is this an internal step" O(canvas nodes)
    # per frame; the mapping never changes during a run, so the set is built
    # once here instead.
    canvas_node_ids = set(node_ids_by_name.values())
    decisions: dict[str, str] = {}
    outputs: dict[str, str] = {}
    attempts = 0
    # One guard per streamed text — per node, per message kind — because each
    # is its own sequence of chunks and a shared tail would splice two
    # unrelated streams together. See `ProseGuard`: the settled answer is
    # cleaned at the end, but `token` frames reach a client while the model is
    # still typing, and that is the half a `done`-frame fix cannot reach.
    guards: dict[tuple[str, str], ProseGuard] = {}
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
        stream = graph.stream(
            graph_input,
            config,
            stream_mode=["updates", "messages"],
            subgraphs=True,
        )
        for namespace, mode, payload in stream:
            if mode == "updates":
                for raw_name, raw_update in payload.items():
                    update = _coerce_update(raw_update)
                    node_id = node_ids_by_name.get(raw_name, raw_name)
                    answer = keep_latest_nonempty(answer, str(update.get("answer") or ""))
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
                    decisions.update(
                        {
                            k: str(v)
                            for k, v in (update.get("decisions") or {}).items()
                            if k != RESET
                        }
                    )
                    outputs.update(
                        {
                            # Cleaned as it is accumulated, not as it is sent:
                            # this dict reaches the `done` frame *and* every
                            # surface's per-node inspector, and a value that
                            # is clean on one path and not the other is the
                            # shape of leak this whole seam exists to remove.
                            k: str(_clean_output(str(v)))
                            for k, v in (update.get("outputs") or {}).items()
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
                    for spawn in spawns.inspect(node_id, namespace, update, is_internal):
                        yield _sse("spawn", spawn)
                    yield _sse(
                        "update",
                        {
                            "node": node_id,
                            "namespace": list(namespace),
                            "taskId": task_ids[0] if task_ids else None,
                            "internal": is_internal,
                            # Additive (ticket 01): the canvas node a client
                            # should show as running for this frame. Both
                            # surfaces read it instead of guessing; an older
                            # client that ignores it behaves exactly as before.
                            "activeNode": active.resolve(node_id, namespace),
                            # Split like the final answer, and for the same
                            # reason: this is a node's own settled output and
                            # both surfaces render it in their trace.
                            "output": _clean_output(
                                (update.get("outputs") or {}).get(node_id)
                                or (update.get("worker_results") or {}).get(
                                    task_ids[0] if task_ids else "", None
                                )
                            ),
                        },
                    )
            elif mode == "messages":
                message, metadata = payload
                content = getattr(message, "content", "")
                if isinstance(content, str) and content:
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
                        content = ""
                    else:
                        # A frame whose whole content was fence is dropped
                        # rather than sent empty: an empty `token` there says
                        # "the model produced nothing just then", a lie.
                        guard = guards.setdefault((token_node, kind), ProseGuard())
                        content = guard.feed(content)
                        if not content:
                            continue
                    yield _sse(
                        "token",
                        {
                            "node": token_node,
                            "namespace": list(namespace),
                            "content": content,
                            # Present and true only when the text was the
                            # machinery rather than the reply. Absent on every
                            # frame a developer receives, so "did I get the
                            # whole stream" stays answerable.
                            **({"withheld": True} if withheld else {}),
                            # Ticket 02, and the whole point of it: `activeNode`
                            # means exactly what it means on an `update` frame —
                            # the canvas node to show as running — but a `token`
                            # frame is the only one that arrives while a node is
                            # STILL WORKING. `updates` fires on completion, so a
                            # highlight fed by update frames alone can only ever
                            # show who last finished. Measured on a real run: 135
                            # consecutive token frames streamed out of the mounted
                            # analyst over ~20s while the last update frame still
                            # said `router1`.
                            #
                            # Same resolver instance as the update branch, so the
                            # stickiness is shared and one honest sequence comes
                            # off the wire rather than two that can disagree.
                            #
                            # NOT coalesced here. The field is attached to every
                            # frame because its meaning must not vary by frame
                            # ("present = changed" would be a second, implicit
                            # field), and because an SSE consumer may join late or
                            # drop frames. Coalescing is the clients' job and is
                            # cheap there — both compare against the node they
                            # last highlighted and do nothing when it is unchanged,
                            # so a 135-token model turn is one state write.
                            "activeNode": active_node,
                            # WHAT produced this text, so a client can stop
                            # treating a tool's result as the model's prose.
                            #
                            # LangGraph's `messages` mode carries every message
                            # a node emits, not only model tokens — a
                            # `ToolMessage` rides the same stream (documented,
                            # and observed: `list_all_tables` streamed its
                            # eleven-row Markdown table through here). Untagged,
                            # the client concatenated tool output and model
                            # reasoning into one blob and rendered the result as
                            # Markdown, which collapsed the table onto a single
                            # line — a tool result made unreadable precisely
                            # because it was long.
                            #
                            # Additive: a client that ignores these two fields
                            # behaves exactly as before.
                            "kind": kind,
                            # A tool result's identity for the client's fold.
                            # `name` alone cannot separate two consecutive calls
                            # to the same tool (`get_table_schema` on Invoice,
                            # then on InvoiceLine); `tool_call_id` can.
                            #
                            # Withheld with the content, because the ticket
                            # names the tool NAME as its own leak: QA read
                            # `music_store` on the customer surface, and
                            # `chinook_execute_sql` says as much about the
                            # machinery as the table it returned.
                            "tool": {"name": "", "callId": ""}
                            if withheld
                            else {
                                "name": str(getattr(message, "name", "") or ""),
                                "callId": str(getattr(message, "tool_call_id", "") or ""),
                            },
                        },
                    )
    finally:
        # Explicit, not left to refcounting. CPython happens to close the
        # inner generator when this frame is destroyed, but "happens to" is
        # not a contract, and under a stop the checkpointer/DB handles the
        # LangGraph stream holds should be released at a defined moment
        # rather than at the collector's convenience.
        closer = getattr(stream, "close", None)
        if callable(closer):
            with suppress(Exception):
                closer()

    snapshot = graph.get_state(config)
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
            },
        )
        return

    # Unconditional, and above the audience check on purpose: this is what
    # makes "a developer-only payload cannot appear in a customer answer" a
    # property of the code rather than of the client that reads it.
    prose, suggestion = split_suggestion(answer)
    channel = DeveloperChannel(
        warnings=list(plan.warnings) + runtime_warnings(runtime),
        suggestion=suggestion,
    )

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
            "attempts": attempts,
            # Topology, not guidance, and `/chat` draws its live flow diagram
            # from it — `GET /api/workflows/{slug}/graph` already serves the
            # same text to that page. See the table in `api/audience.py`.
            "mermaid": graph.get_graph().draw_mermaid(),
            **channel.payload(audience),
        },
    )


