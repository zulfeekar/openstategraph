"""SSE framing and the stream fold (ticket 72 split)."""

from __future__ import annotations

import json
import logging
from contextlib import suppress
from typing import Any

logger = logging.getLogger(__name__)

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


def _sse(event: str, data: dict[str, Any]) -> str:
    """One Server-Sent Event frame: an `event:` line, a `data:` line, blank line.

    `json.dumps` rather than string interpolation, because a node's output can
    contain newlines and quotes, and SSE's `data:` line is newline-delimited —
    an unescaped newline would silently split one event into two.
    """
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


#: The event names that *end* a stream. Exactly one of these is the last
#: frame of every stream that lives long enough to send one — see
#: `_stream_run`, which is what guarantees it. Anything else (`update`,
#: `token`, `spawn`) is progress, and a client must keep waiting after it.
TERMINAL_EVENTS: tuple[str, ...] = ("done", "interrupt", "error")


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
) -> Any:
    """The stream, with its ending guaranteed (UX-02).

    `_run_frames` below does the actual work; this wrapper exists for one
    reason, and it is a protocol rule rather than a convenience:

    > **Every stream ends with a frame that says how it ended.** A client must
    > never have to tell "still working", "finished" and "died" apart by
    > waiting and guessing.

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
        graph, graph_input, config, plan, node_ids_by_name, runtime, thread_id
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
            yield _sse("error", {"detail": f"{type(exc).__name__}: {exc}"})
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
        yield _sse("error", {"detail": "The run ended without reporting a result."})


def _run_frames(
    graph: Any,
    graph_input: Any,
    config: dict[str, Any],
    plan: Any,
    node_ids_by_name: dict[str, str],
    runtime: Any,
    thread_id: str,
) -> Any:
    """Drives one `graph.stream()` call and yields SSE frames.

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
                            k: str(v)
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
                    is_internal = node_id not in canvas_node_ids
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
                            "output": (update.get("outputs") or {}).get(node_id)
                            or (update.get("worker_results") or {}).get(
                                task_ids[0] if task_ids else "", None
                            ),
                        },
                    )
            elif mode == "messages":
                message, metadata = payload
                content = getattr(message, "content", "")
                if isinstance(content, str) and content:
                    raw_name = metadata.get("langgraph_node", "")
                    yield _sse(
                        "token",
                        {
                            "node": node_ids_by_name.get(raw_name, raw_name),
                            "namespace": list(namespace),
                            "content": content,
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
        yield _sse(
            "interrupt",
            {
                "threadId": thread_id,
                "message": (payload_value or {}).get("message", "Approval needed"),
                "candidate": (payload_value or {}).get("candidate", ""),
            },
        )
        return

    warnings = list(plan.warnings) + runtime_warnings(runtime)

    yield _sse(
        "done",
        {
            "answer": answer,
            "decisions": decisions,
            "outputs": outputs,
            "attempts": attempts,
            "mermaid": graph.get_graph().draw_mermaid(),
            "warnings": warnings,
        },
    )


