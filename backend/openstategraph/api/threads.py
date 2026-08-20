"""Past runs: listing the threads a checkpointer already holds, and reading one back.

Identity was never the gap. `thread_id`, `session_id`, `user_email` and
`workflow_slug` have ridden in `configurable` since the run endpoints were
written, memory is namespaced per user, and the checkpointer has been storing
every superstep of every thread to sqlite. What was missing is the other
half of that sentence: **nothing could enumerate what had been stored, or
read one thread back.** Thread continuity lived entirely in a browser's
`localStorage`; clearing it orphaned server-side history that no API could
reach.

So this module invents no store. It reads the one that already exists.

Two facts about LangGraph make that possible, both verified against the
installed version rather than remembered:

1. `BaseCheckpointSaver.list(None)` — a *null* config — enumerates
   checkpoints across every thread, newest first. With a thread-bearing
   config it enumerates one thread.
2. Every non-private key of `configurable` is persisted into each
   checkpoint's `metadata`. That is where `session_id`, `user_email` and
   `workflow_slug` come back from — no second table, no parallel index that
   could disagree with the checkpoints it describes.

**Reading is not replaying.** Everything here is a view of what happened:
values already recorded, rendered as text. No graph is compiled, no model is
resolved, no tool is called, so re-reading a run that sent an email does not
send it again. The one operation that *does* execute is
`POST /api/runs/resume`, which continues a `paused` thread from its
interrupt — a different verb, a different endpoint, and named so on the wire.

`get_state_history()` is the API most reach for here, and it is deliberately
not used: it is a method on a *compiled graph*, so viewing a past run would
mean rebuilding the workflow, resolving a model and constructing every tool —
all of it to read rows the saver can hand over directly, and all of it able
to fail for reasons that have nothing to do with the run being read.
"""

from __future__ import annotations

import json
from typing import Any, Iterable

from openstategraph.developer_channel import transcript_text
from openstategraph.api.schemas import ThreadHistoryResponse, ThreadStep, ThreadSummary

#: Checkpoint channels that belong to the scheduler, not to the run. Showing
#: them would bury the two values anyone actually came for.
_PRIVATE_PREFIXES = ("__", "branch:")

#: One value's ceiling in a rendered step. A history endpoint that streams a
#: megabyte of accumulated messages per checkpoint is a denial of service with
#: a JSON content type.
_VALUE_LIMIT = 4000

#: How many checkpoints a listing may scan to find `limit` distinct threads.
#: A thread costs several checkpoints, so the scan must exceed the answer;
#: unbounded would mean the first request after a long-lived deployment reads
#: the entire sqlite file.
_SCAN_MULTIPLIER = 40
_SCAN_FLOOR = 400


def list_threads(
    savers: Iterable[Any],
    *,
    workflow_slug: str | None = None,
    user_email: str | None = None,
    session_id: str | None = None,
    limit: int = 25,
) -> list[ThreadSummary]:
    """Past runs across every given saver, newest first.

    The filters are a **filter, not an authorization check**. This platform
    authenticates one shared token and `user_email` is whatever the client
    said it was on the run, so `user_email=` narrows a list for a person who
    is already trusted with the whole deployment. Anything stronger has to
    wait for per-user auth, and pretending otherwise here would be the
    dangerous kind of convenience.
    """
    scan = max(limit * _SCAN_MULTIPLIER, _SCAN_FLOOR)
    latest: dict[str, ThreadSummary] = {}
    counts: dict[str, int] = {}
    for saver in _distinct(savers):
        for tuple_ in _safe_list(saver, None, scan):
            thread_id = _thread_id(tuple_)
            if not thread_id:
                continue
            counts[thread_id] = counts.get(thread_id, 0) + 1
            # `list` yields newest first, so the first sighting of a thread is
            # its latest checkpoint — and the only one whose answer is final.
            if thread_id not in latest:
                latest[thread_id] = _summarize(thread_id, tuple_, steps=0)

    rows = [
        summary.model_copy(update={"steps": counts.get(summary.thread_id, 0)})
        for summary in latest.values()
    ]
    rows = [
        row
        for row in rows
        if _matches(row, workflow_slug=workflow_slug, user_email=user_email, session_id=session_id)
    ]
    rows.sort(key=lambda row: row.updated_at, reverse=True)
    return rows[:limit]


def read_thread(
    savers: Iterable[Any], thread_id: str, *, limit: int = 200
) -> ThreadHistoryResponse | None:
    """One past run, oldest checkpoint first — or `None` if no saver holds it."""
    config = {"configurable": {"thread_id": thread_id}}
    for saver in _distinct(savers):
        tuples = list(_safe_list(saver, config, limit))
        if not tuples:
            continue
        summary = _summarize(thread_id, tuples[0], steps=len(tuples))
        steps = [_step(tuple_) for tuple_ in reversed(tuples)]
        return ThreadHistoryResponse(thread=summary, steps=steps)
    return None


def savers_for(services: Any, workflow_slug: str | None = None) -> list[Any]:
    """Every saver a listing should look in.

    A workflow whose settings ask for `checkpointer: "sqlite"` gets a file of
    its own, so "the checkpointer" is genuinely plural and a listing that read
    only the default one would report a workflow as having never run. Naming a
    slug opens (or reuses) that workflow's file; naming none searches the
    shared default plus whatever this process already has open.
    """
    savers = [services.checkpointer]
    if workflow_slug:
        try:
            document = services.store.load(workflow_slug)
        except Exception:
            # An unknown or unreadable slug is not an error for a *listing* —
            # the threads may still be in the shared saver, and a 500 here
            # would make a deleted workflow poison the history of the runs it
            # once had.
            return savers
        settings = (document.get("document") or document).get("settings")
        savers.append(services.checkpointer_for(settings, workflow_slug))
    return savers


def _distinct(savers: Iterable[Any]) -> list[Any]:
    seen: dict[int, Any] = {}
    for saver in savers:
        if saver is not None:
            seen.setdefault(id(saver), saver)
    return list(seen.values())


def _safe_list(saver: Any, config: Any, limit: int) -> list[Any]:
    """`saver.list(...)`, tolerating a saver that cannot enumerate.

    A custom or future saver may refuse a null config. That must degrade to
    "this saver contributed nothing", never to a failed request — the caller
    is asking what history exists, and the honest answer from a saver that
    cannot say is silence.
    """
    try:
        return list(saver.list(config, limit=limit))
    except Exception:  # pragma: no cover - defensive, saver-specific
        return []


def _thread_id(tuple_: Any) -> str:
    return str((tuple_.config or {}).get("configurable", {}).get("thread_id") or "")


def _metadata(tuple_: Any) -> dict[str, Any]:
    return dict(tuple_.metadata or {})


def _values(tuple_: Any) -> dict[str, Any]:
    return dict((tuple_.checkpoint or {}).get("channel_values") or {})


def _summarize(thread_id: str, tuple_: Any, *, steps: int) -> ThreadSummary:
    metadata = _metadata(tuple_)
    values = _values(tuple_)
    return ThreadSummary(
        thread_id=thread_id,
        workflow_slug=str(metadata.get("workflow_slug") or ""),
        session_id=str(metadata.get("session_id") or ""),
        user_email=str(metadata.get("user_email") or ""),
        updated_at=str((tuple_.checkpoint or {}).get("ts") or ""),
        steps=steps,
        question=_text(values.get("question")),
        answer=_text(values.get("answer")),
        status="paused" if _is_paused(tuple_) else "finished",
    )


#: How LangGraph spells a checkpoint namespace: segments joined by `|`, each
#: `<graph-node-name>:<instance-id>`. Written out rather than imported —
#: `NS_SEP` and `NS_END` were made private and deprecated in LangGraph 1.0, and
#: `streaming.py` already reads the same shape by hand.
_NS_SEP = "|"
_NS_END = ":"


def _namespace(tuple_: Any) -> list[str]:
    """Which graph this checkpoint belongs to, outermost first.

    The parent graph checkpoints under `""` and every agent loop or mounted
    workflow under a namespace that **names the node owning it**, so this is
    the field that tells one graph's supersteps from another's. Without it the
    `morning-brief` replay is forty rows in which `Step 3 · loop` appears five
    times with nothing to say they are five different graphs
    (`memory-and-replay` 37).

    The instance id is dropped. Two subtasks dispatched to one `worker_web`
    land in two namespaces, and they are one node that ran twice — a panel
    grouping by name should say so.
    """
    raw = str(((tuple_.config or {}).get("configurable") or {}).get("checkpoint_ns") or "")
    return [
        segment.split(_NS_END)[0]
        for segment in raw.split(_NS_SEP)
        if segment.split(_NS_END)[0]
    ]


def _step(tuple_: Any) -> ThreadStep:
    namespace = _namespace(tuple_)
    metadata = _metadata(tuple_)
    return ThreadStep(
        checkpoint_id=str((tuple_.checkpoint or {}).get("id") or ""),
        step=int(metadata.get("step") or 0),
        at=str((tuple_.checkpoint or {}).get("ts") or ""),
        source=str(metadata.get("source") or ""),
        values={
            key: _text(value)
            for key, value in sorted(_values(tuple_).items())
            if not key.startswith(_PRIVATE_PREFIXES)
        },
        namespace=namespace,
        node=namespace[-1] if namespace else "",
        wrote=[
            str(channel)
            for channel in ((tuple_.checkpoint or {}).get("updated_channels") or [])
            if not str(channel).startswith(_PRIVATE_PREFIXES)
        ],
    )


def _is_paused(tuple_: Any) -> bool:
    """Did this run stop at an `interrupt()` and is it waiting for an answer?

    A pending write on the `__interrupt__` channel is exactly what LangGraph
    leaves behind for a thread parked at an interrupt — confirmed against the
    installed version, not inferred from the name.
    """
    return any(channel == "__interrupt__" for _, channel, _ in (tuple_.pending_writes or []))


def _matches(
    row: ThreadSummary,
    *,
    workflow_slug: str | None,
    user_email: str | None,
    session_id: str | None,
) -> bool:
    if workflow_slug and row.workflow_slug != workflow_slug:
        return False
    # Case-folded, like the memory namespace: the same person typing
    # `A@b.com` today and `a@b.com` tomorrow is one person, and a history that
    # disagrees with their memories about who they are is worse than none.
    if user_email and row.user_email.casefold() != user_email.casefold():
        return False
    if session_id and row.session_id != session_id:
        return False
    return True


def _scrub(value: Any) -> Any:
    """The same strip, one level down, for a channel that holds a mapping.

    `outputs` and `worker_results` are dicts of node id → answer text, and they
    carry the identical fence the top-level `answer` does. Rendering them meant
    `json.dumps` of the raw strings, so the machinery survived under a key
    instead of at the top level (`memory-and-replay` 38) — a leak is a leak
    whichever channel it rides in on.
    """
    if isinstance(value, str):
        return transcript_text(value)
    if isinstance(value, dict):
        return {key: _scrub(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub(item) for item in value]
    return value


def _text(value: Any) -> str:
    """One channel value as readable text, bounded.

    Messages are the case worth handling by hand: a `messages` channel is a
    list of LangChain objects whose `repr` is unreadable and whose `content`
    is the entire point.

    **Every string passes `transcript_text` first, and before `_cap`.** This is
    a customer surface, and the checkpointed `answer` keeps its ```suggestion
    fence on purpose — the live seam splits it, this door read it raw and
    published the machinery to History and to `GET /api/threads`
    (`memory-and-replay` 38). Stripping before capping matters on its own: a
    truncated fence cannot be parsed by anything, so it is worse than a whole
    one.

    `split_suggestion` beneath it is narrow by design — both `nodeType` and
    `attachTo`, or nothing — which is what makes it safe over arbitrary channel
    values in a product whose answers are routinely JSON: SQL result rows, and
    `workflow-architect` replying with an entire workflow document. That
    narrowness is pinned in this ticket's test rather than trusted here.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return _cap(transcript_text(value))
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return _cap("\n".join(_text(item) for item in value if item is not None))
    content = getattr(value, "content", None)
    if content is not None:
        role = getattr(value, "type", "") or value.__class__.__name__
        prose = transcript_text(str(content))
        return _cap(f"{role}: {prose}" if role else prose)
    if isinstance(value, dict):
        try:
            return _cap(json.dumps(_scrub(value), default=str, sort_keys=True))
        except (TypeError, ValueError):  # pragma: no cover - default=str covers it
            return _cap(str(value))
    return _cap(str(value))


def _cap(text: str) -> str:
    if len(text) <= _VALUE_LIMIT:
        return text
    return text[:_VALUE_LIMIT] + f"… (+{len(text) - _VALUE_LIMIT} chars)"
