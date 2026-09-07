"""One run, as events, with no web framework anywhere in it.

## Why this exists

`docs/wiring-it-in.md` §3 taught an adopter to stream by dropping to
`.graph.astream_events()` and writing the fold themselves — forty-five lines,
`version="v2"`, a `node_ids` set built from the document because an event
carries a name and no way to tell a node from a middleware step, and four
things `ask()` does that the loop silently does not. Every adopter who wants a
token in a browser wrote that, and wrote it slightly differently.

Shipping the fold instead is easy. Shipping it **without picking their web
framework** is the whole design, and it is the constraint that decides every
line below:

> **No framework may appear here.** Not FastAPI, not Starlette, not Flask, not
> Django, not an ASGI type, not `receive`. The moment this module imports one
> it is that framework's adapter, and the adopter who uses another one is back
> to writing the fold.

That is `CLAUDE.md`'s existing rule on the other side of the codebase — `core/`
imports neither React nor JointJS, pinned by `src/layerBoundaries.test.ts` —
applied to the Python half. It is pinned the same way, by
`tests/test_the_run_surface_names_no_framework.py`, which resolves imports
rather than matching names.

## The shape

An **async iterator of events**, and a synchronous iterator over the same fold
for a framework that has no event loop. That is the shape because it is the
only one every framework can consume: an ASGI response body is an async
iterator, a WSGI response body is a sync iterator, and both of them are
`for … in` over something that yields. The framework-specific part is then
small enough to read at a glance — `docs/adding-openstategraph-to-your-project.md`
§8 carries one for FastAPI and one for Flask, and they are eight lines and six.

Three shapes were considered and rejected:

- **A callback interface** (`on_token=…`). It inverts control, so the adopter
  cannot `await` their own work between events, cannot apply backpressure, and
  cannot stop.
- **A queue the caller drains.** It buffers, which is the pacing defect
  `the-cost-of-one-more/15` and `/20` are about, and it needs a lifecycle of
  its own that an iterator gets from the language.
- **A base class the adopter subclasses per framework.** That is a family with
  one member per framework, which is exactly the binding this module refuses.

## Backpressure, stated rather than implied

**There is no buffer.** An async generator is pull-based: the run is suspended
at its `yield` until the consumer asks for the next event. A consumer slower
than the producer therefore *slows the run*; nothing queues, nothing is
coalesced, and nothing is dropped. That is the contract, and it is the
conservative half of the pair — the two client-side incidents this repository
has had (`the-cost-of-one-more/15`, `/20`: two thousand frames killed a browser)
were a *consumer* that could not keep up with a transport that never asked it
to. If an adopter wants to shed load, they do it in their adapter, over events
that carry enough to shed safely.

## Errors are events

The stream yields an `error` event and then ends. Nothing is raised out of the
middle of an iteration, where a framework has already sent its response headers
and can render nothing. The two exceptions are stated rather than left to be
discovered:

- **Before the first event**, `CompiledWorkflow.events(...)` itself raises —
  `RunContextError` for a context key this document does not declare, the same
  `OpenStateGraphError` subclass `ask()` raises, in the same place a handler
  can still turn it into a 422.
- **`asyncio.CancelledError` propagates**, because a consumer that cancelled
  the task is not a consumer waiting for an event about it.

A run that finishes having produced no answer is a `done` event whose `answer`
is empty, exactly as it is on the wire. It is **not** the `RunProducedNothing`
that `ask()` raises: a stream has already told the consumer everything that
happened, so raising at the end would be a second, later account of a run they
watched. `workflow.failure_warnings` is the gate that needs no run at all.

## The vocabulary is the published one

Event names and their fields are **not declared here**. They are the names the
SSE wire already publishes — `api/streaming.RUN_EVENTS` and its payload table,
which `docs/openapi.json` carries — and this module emits a subset of them with
the same spellings. `tests/test_the_run_surface_names_no_framework.py` asserts
the subset, so an event this module invents, or a field it renames, is a red
test rather than a second contract. Pydantic stays the single source of truth
for the run/stream seam and nothing here mirrors it.

What the subset costs is worth naming: the SSE fold knows the compiler's
`plan`, the server's `runtime` and its audience, so its frames carry
`activeNode`, `path`, `interruptible`, spawn and tool lanes, and a redaction
pass. A `CompiledWorkflow` has none of those, so this surface does not pretend
to: it carries what a compiled graph and its document can honestly answer for.
"""

from __future__ import annotations

import asyncio
import threading
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Iterator, Mapping

from openstategraph.stream_parts import stream_part

__all__ = ["RunEvent", "RunStream", "abandon_pending"]


def abandon_pending(task: Any) -> None:
    """Drop a task we are no longer waiting on, without a warning storm.

    A cancelled `__anext__` whose worker thread is still inside a synchronous
    node does not finish immediately (a blocking call cannot be interrupted),
    so the task outlives us. Retrieving its outcome here is what stops asyncio
    logging "exception was never retrieved" for work nobody wanted.

    Cancelled **without awaiting**, and that is measured rather than tidy
    (`async-first/09`): the pending step may be a blocking model call, and
    awaiting it would turn today's instant stop into a stop the consumer sits
    through. Only an `async def` node body is genuinely cancelled here.

    One declaration, two readers — `api/streaming._abandon` is this function.
    The SSE fold met the problem first; the direction of the import is the only
    thing that changed when this surface met it too.
    """
    task.cancel()
    task.add_done_callback(lambda done: done.cancelled() or done.exception())


@dataclass(frozen=True)
class RunEvent:
    """One thing worth telling a consumer, named the way the wire names it.

    An envelope and nothing else: `type` is one of the published event names
    and `data` carries that event's published fields. Deliberately **not** a
    class per event kind — that would be thirty field names declared a second
    time, in a repository whose stated rule is that Pydantic owns the
    run/stream seam and nobody mirrors it. The envelope declares no field at
    all, so there is nothing here to drift.
    """

    type: str
    data: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """`{"type": …, **fields}` — the shape an adapter serialises.

        `type` cannot collide with a payload key: no published frame carries a
        field of that name, and the boundary test asserts it.
        """
        return {"type": self.type, **dict(self.data)}


class RunStream:
    """One run of one workflow, iterated as events.

    Constructed by `CompiledWorkflow.events(...)` rather than directly, because
    the run's identity, its step budget and its context validation are the
    workflow's to resolve and it already knows how — `ask()` resolves the same
    four keys, and two spellings of a run's identity is the defect
    `run_identity.py` exists to prevent.

    Iterate it **once**, either way:

        async for event in stream: ...   # any async framework
        for event in stream: ...         # any synchronous framework

    The synchronous form drives the same async fold on the workflow's own
    `RunLoop` — the loop that already owns the provider client's connection
    pool (`run_doors.py`) — so a WSGI worker and an ASGI one execute the run
    identically rather than through two engines.
    """

    def __init__(
        self,
        workflow: Any,
        question: str,
        *,
        thread_id: str,
        config: dict[str, Any],
        identity: Mapping[str, str],
        run_context: Any = None,
    ) -> None:
        self._workflow = workflow
        self._question = question
        self._thread_id = thread_id
        self._config = config
        # **Handed in, never read back out of `config`.** The run's identity is
        # resolved once by the door that starts the run — `run_identity.py`
        # says why there is one accessor and not five — and a module that
        # spells the keys again is the drift that census exists to stop. This
        # one names none of them.
        self._identity = dict(identity)
        self._run_context = run_context
        self._stop_flag = threading.Event()
        self._stopped: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def thread_id(self) -> str:
        """The conversation this run is in — send it back to continue.

        Readable before the first event, because a handler frequently has to
        put it in a header or a response envelope it writes before the body.
        """
        return self._thread_id

    def stop(self) -> None:
        """Stop the run. Idempotent, and callable from any thread.

        **This is the whole cancellation story, and it is a method rather than
        a parameter on purpose.** A framework-agnostic surface cannot take an
        ASGI `receive`, an `asyncio.Event` the caller made on a loop we cannot
        see, or a `Future`; every one of those names a runtime. A method names
        nothing — a FastAPI adapter calls it from a disconnect listener, a
        Flask adapter from a `finally`, a test from a timer.

        It is needed, and the measurement is on the record
        (`launch-readiness/10`): **Starlette does not notice a client
        disconnect** on a modern ASGI server. It drops the `listen_for_disconnect`
        branch for `spec_version >= 2.4` and finds out only when a `send()`
        raises `OSError`, which uvicorn's socket writes do not do promptly. So
        an adapter that merely stops reading does not stop the run — a browser
        that aborted its fetch mid-crew left the run streaming to its natural
        end, every remaining superstep billed to nobody. Whoever knows the
        consumer has gone has to say so.

        **The boundary is the same one the server has**, and it is not widened
        here: stop means *nothing further is scheduled*. Work already dispatched
        into the current superstep finishes and is discarded, because a blocking
        model call has no cancellation seam. A migrated `async def` node body is
        genuinely cancelled.

        **After a stop there is no terminal event.** The stream ends, silently,
        because the consumer it would be addressed to is the one that left. A
        consumer that stopped the run knows it did; a consumer that reads a body
        ending with no terminal event knows the connection dropped. That is the
        same rule both of this project's own clients already implement.
        """
        self._stop_flag.set()
        loop, stopped = self._loop, self._stopped
        if loop is not None and stopped is not None:
            with suppress(RuntimeError):
                loop.call_soon_threadsafe(stopped.set)

    async def __aiter__(self) -> AsyncIterator[RunEvent]:
        """Every event of the run, racing each against a `stop()`.

        The race is what makes `stop()` mean anything: a plain `if stopped:
        break` is only consulted between events, and the event a consumer wants
        to stop *during* is the ninety-second one. Found and fixed on the SSE
        side first (`launch-readiness/10`), and the ordering below is that
        ticket's follow-on correction — the stop is asked about **first**, never
        read as "the step lost the race", because an async fold with an event
        buffered resolves its `__anext__` without suspending and is therefore
        only *also* ready, never ahead.
        """
        self._loop = asyncio.get_running_loop()
        self._stopped = asyncio.Event()
        if self._stop_flag.is_set():
            self._stopped.set()

        source = self._events().__aiter__()
        gone = asyncio.ensure_future(self._stopped.wait())
        try:
            while True:
                step = asyncio.ensure_future(source.__anext__())
                await asyncio.wait({step, gone}, return_when=asyncio.FIRST_COMPLETED)
                if gone.done():
                    abandon_pending(step)
                    return
                try:
                    event = step.result()
                except StopAsyncIteration:
                    return
                yield event
        finally:
            abandon_pending(gone)

    def __iter__(self) -> Iterator[RunEvent]:
        """The same events, for a framework with no event loop.

        One `__anext__` at a time on the workflow's own `RunLoop`, which is a
        real loop on a thread of its own rather than a loop per call — see
        `run_doors.py` for why that ownership is not negotiable once a provider
        client is cached. `stop()` from another thread still works, because the
        flag it sets is a `threading.Event` and the wake-up is
        `call_soon_threadsafe`.

        A WSGI server that abandons the response — the client went away, the
        write raised — closes this generator, and the `finally` stops the run.
        That is genuine cancellation on a transport that has no disconnect
        signal to listen for, and it is why the sync door needs no equivalent of
        the ASGI adapter's listener.
        """
        loop = self._workflow._loop
        iterator: Any = None

        async def _open() -> Any:
            return self.__aiter__().__aiter__()

        async def _next(it: Any) -> Any:
            try:
                return await it.__anext__()
            except StopAsyncIteration:
                return _DONE

        try:
            iterator = loop.run(_open)
            while True:
                event = loop.run(lambda: _next(iterator))
                if event is _DONE:
                    return
                yield event
        finally:
            self.stop()
            if iterator is not None:
                with suppress(Exception):
                    loop.run(iterator.aclose)

    async def _events(self) -> AsyncIterator[RunEvent]:
        """The fold: LangGraph's chunks in, published events out.

        The terminal event is assembled from `CompiledWorkflow._result` — the
        very assembly `ask()` and `resume()` share — rather than folded by hand
        here. That is the point: a run must not be able to report a different
        answer, a different set of decisions or a different token bill
        depending on which door watched it. Five doors folding one channel
        their own way is how two of them came to publish two different answers
        for one run (`launch-readiness/175`).
        """
        from openstategraph.compile.workflow_compiler import safe_name
        from openstategraph.messages import (
            content_text,
            is_transcript_record,
        )
        from openstategraph.run_journal import run_turn

        workflow = self._workflow
        thread_id = self._thread_id
        yield RunEvent("started", {"threadId": thread_id})

        # A node's LangGraph name is `safe_name(document id)` — colons are
        # illegal there — so every event is translated back to the id the
        # document uses, which is the only name a consumer of ours has ever
        # seen. Asked of the document rather than of the graph, because the
        # document is what the consumer also holds.
        node_ids = {
            safe_name(str(node.get("id"))): str(node.get("id"))
            for node in (workflow.document.get("nodes") or [])
            if node.get("id")
        }
        graph_input = {
            "question": self._question,
            "attempts": 0,
            "decisions": {},
            "outputs": {},
        }
        # `None` means *pass no argument at all*: a workflow that declares no
        # run context must stream exactly as it did before this existed, and
        # `None` and absent are not guaranteed to be the same thing to a
        # library we do not own (`organisms-first-class/70`).
        supplied = {"context": self._run_context} if self._run_context is not None else {}

        terminal: RunEvent
        try:
            # The fifth door onto one turn (`memory-and-replay/44`). It owns
            # the clock and LangChain's per-model usage meter, which is how
            # this surface gives back the token accounting §3 of
            # `wiring-it-in.md` lists as lost — and it writes the run down, so
            # a run watched through this door lands in the journal like one
            # asked through any other.
            with run_turn(
                workflow_slug=workflow.slug or "",
                thread_id=thread_id,
                **self._identity,
                question=self._question,
                warnings=workflow.warnings,
                failures=workflow.failure_warnings,
                registry=workflow._run_sinks(),
            ) as turn:
                stream = workflow.graph.astream(
                    graph_input,
                    self._config,
                    **supplied,
                    stream_mode=["updates", "messages"],
                    # Verbatim from the doc and not to be disturbed: without
                    # it, `stream_mode="messages"` on the parent graph will not
                    # emit token chunks from an inner agent's model calls.
                    subgraphs=True,
                    # One chunk shape whatever we ask for — `stream_parts.py`.
                    version="v2",
                )
                async for chunk in stream:
                    decoded = stream_part(chunk)
                    if decoded is None:
                        continue
                    namespace, mode, payload = decoded
                    if mode == "updates":
                        for name, update in (payload or {}).items():
                            node_id = node_ids.get(name, name)
                            yield RunEvent(
                                "update",
                                {
                                    "node": node_id,
                                    "namespace": list(namespace or ()),
                                    # **This node's own settled output**, which
                                    # is what the wire's `update` frame carries
                                    # — never the raw state update. The update
                                    # holds `messages` (LangChain objects, not
                                    # JSON), the turn-reset markers, and every
                                    # channel the node touched; publishing it
                                    # would hand a consumer machinery it has no
                                    # vocabulary for and could not serialise.
                                    "output": _node_output(update, name, node_id),
                                },
                            )
                    elif mode == "messages":
                        message, metadata = _message_chunk(payload)
                        if message is None:
                            continue
                        # **The record is not a token.** `_input` logs the
                        # question and `_output` logs the answer where every
                        # path converges, and this channel emits both — so
                        # without this gate a consumer that concatenates tokens
                        # holds the answer twice before the terminal event
                        # shows it a third time (`every-workflow-green/02`,
                        # measured on the wire; the predicate carries the
                        # measurement).
                        if is_transcript_record(message):
                            continue
                        text = content_text(getattr(message, "content", ""))
                        if not text:
                            continue
                        name = str((metadata or {}).get("langgraph_node") or "")
                        yield RunEvent(
                            "token",
                            {
                                "node": node_ids.get(name, name),
                                "namespace": list(namespace or ()),
                                "content": text,
                            },
                        )

                state = await workflow.graph.aget_state(self._config)
                final = dict(getattr(state, "values", None) or {})
                # **A pause is not on the state, and this is where a stream
                # would otherwise lose it.** `graph.ainvoke` returns the
                # pending `Interrupt` objects under `__interrupt__`; a *read*
                # of the checkpoint does not — they are on the state's pending
                # tasks. So they are put back where `_result` already reads
                # them, rather than given a second reader here: one assembly
                # decides what a paused run looks like, whichever door watched
                # it (`workflow-gallery/24`).
                pending, paused_name = _pending_interrupts(state)
                if pending:
                    final["__interrupt__"] = pending
                # Read inside the block: the meter clears the variable on exit.
                spent = turn.spent()
                result = workflow._result(final, spent, thread_id)
                # Before anything can raise, and whatever the run produced: a
                # failed run is the one most worth having in the journal.
                turn.record(final, answer=str(result))
                terminal = _terminal_event(
                    result, thread_id, node_ids.get(paused_name, paused_name)
                )
        except asyncio.CancelledError:
            # Never an event. A consumer that cancelled the task is not waiting
            # to be told about it, and swallowing it here would make a
            # cancelled task look like a finished one to everything above.
            raise
        except Exception as exc:
            yield RunEvent(
                "error",
                {
                    "threadId": thread_id,
                    "detail": f"{type(exc).__name__}: {exc}",
                    "usage": {},
                },
            )
            return
        yield terminal


#: The sentinel the sync door uses to tell "the fold ended" from "the fold
#: yielded `None`". A module-level object rather than `None` for exactly that
#: reason: an event is never `None` today, and a sentinel that is also a value
#: is a bug waiting for the day one is.
_DONE = object()


def _pending_interrupts(state: Any) -> tuple[list[Any], str]:
    """The interrupts a read checkpoint waits on, and the graph node holding them.

    The name is why this reads the tasks rather than `state.next`: a run can
    only pause at a gate, and the consumer being asked to answer needs to know
    *which* gate. `ainvoke`'s `__interrupt__` carries the payload and not the
    node, so the two are collected together here and separated again by
    `_terminal_event`.
    """
    found: list[Any] = []
    name = ""
    for task in getattr(state, "tasks", None) or ():
        interrupts = list(getattr(task, "interrupts", None) or ())
        if interrupts and not name:
            name = str(getattr(task, "name", "") or "")
        found.extend(interrupts)
    return found, name


def _node_output(update: Any, graph_name: str, node_id: str) -> Any:
    """One node's settled output out of its state update, or `None`.

    The same two reads the SSE fold makes, in the same order: a node writes its
    result into `outputs` under its own id, and a fanned-out worker writes into
    `worker_results` under a task id. Anything else is a node that produced no
    output this step, which is a real and unremarkable thing for a router or a
    reset to do — `None`, never an invented empty string.
    """
    if not isinstance(update, Mapping):
        return None
    outputs = update.get("outputs") or {}
    for key in (node_id, graph_name):
        if isinstance(outputs, Mapping) and key in outputs:
            return outputs[key]
    results = update.get("worker_results") or {}
    if isinstance(results, Mapping) and len(results) == 1:
        return next(iter(results.values()))
    return None


def _message_chunk(payload: Any) -> tuple[Any, Mapping[str, Any] | None]:
    """A `messages` payload as `(chunk, metadata)`, read tolerantly.

    LangGraph documents this mode as 2-tuples of `(token, metadata)`. Read
    tolerantly and trusted narrowly, the way this project reads everything it
    did not write: a shape that is not that pair costs one event rather than
    the stream.
    """
    if isinstance(payload, (list, tuple)) and len(payload) == 2:
        message, metadata = payload
        return message, metadata if isinstance(metadata, Mapping) else None
    return None, None


def _terminal_event(result: Any, thread_id: str, paused_node: str = "") -> RunEvent:
    """`interrupt` if a gate paused the run, else `done`.

    A pause is not an answer, and this is where the two stop looking alike
    (`workflow-gallery/24`). Both carry `usage`, because a paused run is a real
    checkpoint here and has been paid for like a finished one — "the terminal
    frame carries the cost, except that one" is the rule with an exception in
    it that `memory-and-replay/54` refused.
    """
    pause = getattr(result, "pause", None)
    if pause:
        return RunEvent(
            "interrupt",
            {
                "threadId": thread_id,
                "node": paused_node,
                "message": pause.get("message") or "",
                "candidate": pause.get("candidate"),
                "usage": result.usage,
            },
        )
    return RunEvent(
        "done",
        {
            "threadId": thread_id,
            "answer": str(result),
            "decisions": result.decisions,
            "routes": result.routes,
            "outputs": result.outputs,
            "attempts": result.attempts,
            "usage": result.usage,
        },
    )
