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
    from openstategraph.compile.node_runtime import keep_latest_nonempty, merge_decisions

    answer = ""
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
                    decisions = merge_decisions(
                        decisions, {k: str(v) for k, v in (update.get("decisions") or {}).items()}
                    )
                    outputs = merge_decisions(
                        outputs, {k: str(v) for k, v in (update.get("outputs") or {}).items()}
                    )
                    if "attempts" in update:
                        attempts = int(update["attempts"])
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


