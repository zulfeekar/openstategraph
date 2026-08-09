"""SSE framing and the stream fold (ticket 72 split)."""

from __future__ import annotations

import json
import logging
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
        is_canvas_node = not self._known or mounted in self._known or mounted in self._known.values()
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


def _sse(event: str, data: dict[str, Any]) -> str:
    """One Server-Sent Event frame: an `event:` line, a `data:` line, blank line.

    `json.dumps` rather than string interpolation, because a node's output can
    contain newlines and quotes, and SSE's `data:` line is newline-delimited —
    an unescaped newline would silently split one event into two.
    """
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _stream_run(
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
    """
    from openstategraph.compile.node_runtime import RESET, keep_latest_nonempty, merge_decisions

    answer = ""
    spawns = SpawnWatcher(node_ids_by_name)
    decisions: dict[str, str] = {}
    outputs: dict[str, str] = {}
    attempts = 0

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
                    decisions = merge_decisions(
                        decisions,
                        {
                            k: str(v)
                            for k, v in (update.get("decisions") or {}).items()
                            if k != RESET
                        },
                    )
                    outputs = merge_decisions(
                        outputs,
                        {
                            k: str(v)
                            for k, v in (update.get("outputs") or {}).items()
                            if k != RESET
                        },
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
                    is_internal = node_id not in node_ids_by_name.values()
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
    except Exception as exc:  # noqa: BLE001 — reported to the client, not swallowed
        yield _sse("error", {"detail": f"{type(exc).__name__}: {exc}"})
        return

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


