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
from datetime import datetime
from typing import Any, Iterable

from openstategraph.developer_channel import transcript_text
from openstategraph.compile.workflow_compiler import node_failure_warnings
from openstategraph.compile.state import published_answer
from openstategraph.api.audience import Audience, visible_channel_names, visible_state
from openstategraph.api.schemas import (
    ThreadHistoryResponse,
    ThreadStep,
    ThreadSummary,
    ThreadTokens,
    ThreadToolCall,
)

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
    savers: Iterable[Any],
    thread_id: str,
    *,
    audience: Audience = Audience.CUSTOMER,
    limit: int = 200,
) -> ThreadHistoryResponse | None:
    """One past run, oldest checkpoint first — or `None` if no saver holds it.

    **Who is reading is a parameter, and its default is the closed one**
    (`the-boundary-nobody-checked/02`). A customer gets their own turn — the
    question, the answer, the decisions, the outputs — and none of the
    machinery that produced it: no tool name, no arguments, no result, no
    usage, and only the state channels `compile/state.py` marks
    `CUSTOMER_VISIBLE`. A developer gets the whole run, exactly as this door
    has always returned it.

    The alternative was to declare the door developer-only and be done. It was
    rejected on the product question rather than on cost: a customer-facing
    history panel — *"what did I ask yesterday"* — is an obvious thing to build
    on a product whose own front page says a third client is supported
    (`api/main.py`), and a door that refuses one forecloses it. So the door
    takes an audience, and a customer's history is the same shape as a
    customer's live run.
    """
    config = {"configurable": {"thread_id": thread_id}}
    for saver in _distinct(savers):
        tuples = list(_safe_list(saver, config, limit))
        if not tuples:
            continue
        summary = _summarize(thread_id, tuples[0], steps=len(tuples))
        # Oldest first, and the reader is stateful over that order — it counts
        # a channel's new messages against what earlier checkpoints already
        # held, which only means anything walked forwards.
        oldest_first = list(reversed(tuples))
        tools = _ToolCallReader(oldest_first)
        clock = _ClockReader()
        usage = _UsageReader()
        steps = [_step(tuple_, tools, clock, usage, audience) for tuple_ in oldest_first]
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
        # A stored thread is read back through the same seam a live run is
        # published through, so a resumed conversation cannot show a different
        # answer from the one the run door gave (`launch-readiness/174`).
        answer=_text(published_answer(values)),
        status="paused" if _is_paused(tuple_) else "finished",
        # The same sentinel `node_failure_warnings` reports on a live run
        # (`cli.run_exit_code`'s channel), read back from `outputs` here —
        # never from emptiness, which `silent_node_warnings` already covers
        # and which is not a failure (production-ready/78).
        failed=bool(node_failure_warnings(values.get("outputs") or {})),
        pause=_pause_payload(tuple_),
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

    **So is the subgraph counter**, for the same reason and by the same
    sentence. When one task invokes a subgraph more than once, LangGraph
    appends `|1`, `|2`, … to the namespace (`PregelLoop.__init__` asks the
    task's `PregelScratchpad.subgraph_counter()`, which returns 0 the first
    time). Kept, that segment reads on screen as `Data Analyst › 1` — a nested
    graph called `1`, which no document contains and no reader can act on
    (`memory-and-replay` 40). Dropped, the invocations key alike and the panel
    calls them `· run 2`, `· run 3`, which is what they are.

    Narrow, because the narrowness is the safety: a counter is **all digits
    and carries no `_NS_END`**, and every genuine segment carries one — the
    scheduler builds `f"{name}{NS_END}{task_id}"` before a task ever sees it.
    Anything else is left exactly as stored.
    """
    raw = str(((tuple_.config or {}).get("configurable") or {}).get("checkpoint_ns") or "")
    names = []
    for segment in raw.split(_NS_SEP):
        if _NS_END not in segment and segment.isdigit():
            continue
        head = segment.split(_NS_END)[0]
        if head:
            names.append(head)
    return names


class _ToolCallReader:
    """Which tool calls belong to which step, across one thread.

    Stateful on purpose, and one instance per `read_thread`, because the two
    facts it needs cannot be seen from a single checkpoint:

    - **The message channel is cumulative.** Every checkpoint holds the whole
      history, so "what this step called" is the *new tail*, not the contents.
      One counter per namespace — a worker's channel is not the workflow's, and
      sharing a counter would make a second graph's first call look like
      something already seen.
    - **A request and its answer land in different supersteps.** LangGraph
      writes the `AIMessage` in one and the `ToolMessage` in the next, so the
      results are collected in a first pass over the whole thread and paired
      onto the step that asked.

    A `ToolMessage` whose request is no longer in the stored history is still
    reported, with no arguments. It is an execution point, and dropping it
    would be exactly the quiet loss this exists to end.
    """

    def __init__(self, tuples: Iterable[Any]) -> None:
        self._results: dict[str, tuple[str, str]] = {}
        self._answered: set[str] = set()
        self._seen: dict[str, int] = {}
        for tuple_ in tuples:
            for message in _messages(tuple_):
                call_id = str(getattr(message, "tool_call_id", "") or "")
                if not call_id:
                    continue
                name = str(getattr(message, "name", "") or "")
                self._results[call_id] = (name, _text(getattr(message, "content", "")))

    def at(self, tuple_: Any) -> list[ThreadToolCall]:
        """The calls this checkpoint added, in the order it added them."""
        key = "|".join(_namespace(tuple_)) or ""
        messages = _messages(tuple_)
        already = self._seen.get(key, 0)
        self._seen[key] = len(messages)
        found: list[ThreadToolCall] = []
        for message in messages[already:]:
            for call in getattr(message, "tool_calls", None) or []:
                call_id = str(_call_field(call, "id") or "")
                name, result = self._results.get(call_id, ("", ""))
                self._answered.add(call_id)
                found.append(
                    ThreadToolCall(
                        name=str(_call_field(call, "name") or name),
                        arguments=_text(_call_field(call, "args")),
                        result=result,
                    )
                )
            call_id = str(getattr(message, "tool_call_id", "") or "")
            if call_id and call_id not in self._answered:
                # An answer whose request is gone — a truncated history, or a
                # thread joined mid-run. Reported without arguments rather than
                # dropped.
                self._answered.add(call_id)
                name, result = self._results.get(call_id, ("", ""))
                found.append(ThreadToolCall(name=name, arguments="", result=result))
        return found



class _ClockReader:
    """How long each superstep took, from the timestamps already stored.

    A checkpoint is written *after* its superstep runs, so the gap between one
    checkpoint's `ts` and the previous one's is that superstep's own elapsed
    time. No frame table, no write-side change — the ticket priced durations as
    the expensive half of replay and the store already had them
    (`memory-and-replay` 37, part 2).

    **Per namespace**, for the same reason the tool-call reader counts per
    namespace: an agent subgraph's supersteps are interleaved with its parent's
    in one list, so differencing against whatever row happens to precede this
    one would charge the parent a worker's time and the worker the gap since
    the parent.

    Silence rather than a zero wherever the arithmetic cannot be done — a first
    step, an unreadable `ts`, a clock that went backwards. `0` is the claim
    *this took no time*, and none of those three support it.

    **A `source: "input"` checkpoint is not timed at all.** It records what was
    handed in; no superstep ran. On a thread carrying a second turn, the gap
    from the previous turn's last checkpoint is how long the *person* took to
    type — `morning-brief`'s stored run read `Step 6 · input — 1m 36s` in the
    column that everywhere else means how long the graph took. It still
    advances the clock, so the superstep after it is timed from the moment the
    turn began, which is right.
    """

    def __init__(self) -> None:
        self._last: dict[str, datetime] = {}

    def at(self, tuple_: Any) -> int | None:
        moment = _moment(tuple_)
        if moment is None:
            return None
        key = "|".join(_namespace(tuple_))
        previous = self._last.get(key)
        self._last[key] = moment
        if previous is None or _source(tuple_) == "input":
            return None
        elapsed = (moment - previous).total_seconds()
        if elapsed < 0:
            return None
        return int(round(elapsed * 1000))


def _source(tuple_: Any) -> str:
    return str(_metadata(tuple_).get("source") or "")


def _moment(tuple_: Any) -> datetime | None:
    raw = str((tuple_.checkpoint or {}).get("ts") or "")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


class _UsageReader:
    """What each superstep's model call cost, off `AIMessage.usage_metadata`.

    LangChain populates it for every provider that reports usage, and it has
    ridden in the checkpoints since the message channel did. Same two rules as
    the tool-call reader, and for the same reasons:

    - **The channel is cumulative**, so this counts the *new tail* only.
      Summing the channel would charge the last row for the whole run.
    - **One counter per namespace** — a worker's channel is not the workflow's.

    A superstep whose new messages report no usage gets `None`, not a zeroed
    row: a bookkeeping step did not spend zero tokens, it called no model.
    """

    def __init__(self) -> None:
        self._seen: dict[str, int] = {}

    def at(self, tuple_: Any) -> ThreadTokens | None:
        key = "|".join(_namespace(tuple_))
        messages = _messages(tuple_)
        already = self._seen.get(key, 0)
        self._seen[key] = len(messages)
        totals = [0, 0, 0]
        found = False
        for message in messages[already:]:
            usage = getattr(message, "usage_metadata", None)
            if not isinstance(usage, dict):
                continue
            found = True
            for index, field in enumerate(("input_tokens", "output_tokens", "total_tokens")):
                totals[index] += _count(usage.get(field))
        if not found:
            return None
        return ThreadTokens(
            input_tokens=totals[0], output_tokens=totals[1], total_tokens=totals[2]
        )


def _count(value: Any) -> int:
    """A usage field as a whole number, tolerating a provider that omits it.

    Read tolerantly, trusted strictly: anything that is not a number counts as
    nothing rather than raising, because a malformed usage block must not turn
    a readable run into a 500.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


def _call_field(call: Any, key: str) -> Any:
    """A tool call is a dict on every message class we read, but not on every
    one that exists — a provider object with attributes reads the same way."""
    if isinstance(call, dict):
        return call.get(key)
    return getattr(call, key, None)


def _messages(tuple_: Any) -> list[Any]:
    value = _values(tuple_).get("messages")
    return list(value) if isinstance(value, (list, tuple)) else []


def _step(
    tuple_: Any,
    tools: _ToolCallReader | None = None,
    clock: _ClockReader | None = None,
    usage: _UsageReader | None = None,
    audience: Audience = Audience.CUSTOMER,
) -> ThreadStep:
    """One checkpoint as a row, holding back what this audience may not read.

    Three of the four withholdings are the live stream's, applied to the same
    facts one surface later: `streaming.py` blanks a tool call, withholds
    usage, and `DeveloperChannel.payload` drops `redactions` — a stored run
    must not answer a question the live one refused.

    **A customer's tool calls are dropped, not blanked.** The stream empties a
    withheld `token` frame and keeps it because the frame is the only thing
    saying a run is mid-node; here the *step row* already says that, so an
    emptied call would add a shape with nothing in it. The step is still
    listed, still timed, and still names the node that ran.

    `duration_ms` stays on both audiences, for `api/frame_clock.py`'s recorded
    reason: elapsed time is a property of the deployment, not of the content,
    and `docs/api.md` already argues why a clock is not a disclosure.
    """
    namespace = _namespace(tuple_)
    metadata = _metadata(tuple_)
    developer = audience is Audience.DEVELOPER
    return ThreadStep(
        checkpoint_id=str((tuple_.checkpoint or {}).get("id") or ""),
        step=int(metadata.get("step") or 0),
        at=str((tuple_.checkpoint or {}).get("ts") or ""),
        source=str(metadata.get("source") or ""),
        values={
            key: _text(value)
            for key, value in sorted(visible_state(_values(tuple_), audience).items())
            if not key.startswith(_PRIVATE_PREFIXES)
        },
        namespace=namespace,
        node=namespace[-1] if namespace else "",
        wrote=[
            str(channel)
            for channel in visible_channel_names(
                (tuple_.checkpoint or {}).get("updated_channels") or [], audience
            )
            if not str(channel).startswith(_PRIVATE_PREFIXES)
        ],
        tool_calls=tools.at(tuple_) if tools is not None and developer else [],
        duration_ms=clock.at(tuple_) if clock is not None else None,
        tokens=usage.at(tuple_) if usage is not None and developer else None,
    )


def _is_paused(tuple_: Any) -> bool:
    """Did this run stop at an `interrupt()` and is it waiting for an answer?

    A pending write on the `__interrupt__` channel is exactly what LangGraph
    leaves behind for a thread parked at an interrupt — confirmed against the
    installed version, not inferred from the name.
    """
    return any(channel == "__interrupt__" for _, channel, _ in (tuple_.pending_writes or []))


def _pause_payload(tuple_: Any) -> dict[str, str] | None:
    """What a paused thread is waiting to be told, or `None` if it is not.

    `CompiledWorkflow.pause()` reads the identical value off `graph.get_state`,
    but that needs a compiled graph, and this module deliberately compiles
    nothing to answer "is this thread waiting on me". The same payload rides
    on the pending `__interrupt__` write `_is_paused` already inspects — a
    LangGraph `Interrupt`'s `.value` is the node's own `{"message",
    "candidate"}` dict, put there by `_human_approval` — so this reads the
    checkpoint tuple a second way rather than a second store.

    Every value is rendered through `_text`, the same tolerant, fence-scrubbed
    rendering every other channel value gets here — a candidate is exactly the
    kind of thing `workflow-architect` might have made an entire document, and
    a customer may be reading.

    **Not audience-filtered, and the reason is what the payload is**: an
    interrupt's value is the question the run is asking *the person*, written
    by the node's own author for them to answer. Withholding it from a
    customer would leave a paused thread with nothing to approve — the gate's
    message is the one piece of machinery that is addressed to the reader.
    """
    for _, channel, value in tuple_.pending_writes or []:
        if channel != "__interrupt__":
            continue
        for interrupt in value or ():
            payload = getattr(interrupt, "value", interrupt)
            if isinstance(payload, dict):
                return {key: _text(item) for key, item in payload.items()}
            return {"message": _text(payload)}
    return None


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

    **Every string passes `transcript_text` first, and before `_cap`.** The
    checkpointed `answer` keeps its ```suggestion fence on purpose — the live
    seam splits it, this door read it raw and published the machinery to
    History and to `GET /api/threads` (`memory-and-replay` 38). Stripping
    before capping matters on its own: a truncated fence cannot be parsed by
    anything, so it is worse than a whole one.

    That sentence used to open *"this is a customer surface"*, and the door it
    described took no audience at all — so it was a claim about a payload that
    also carried tool names, arguments, results, usage and `redactions`
    (`the-boundary-nobody-checked/02`). The door **serves** a customer now,
    which is a different sentence: `read_thread` takes the audience and
    `visible_state` decides the channels, and this function stays what it
    always was — the rendering, applied to whatever survived that decision.
    Unconditional on purpose: a developer has no more use for a half-parsed
    fence than a customer does.

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
