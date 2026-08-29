"""The blocking doors drive one run on **one loop** (`async-first/12`).

## The defect

Phase D gave every migrated node body a synchronous door that runs it on a
private loop — `asyncio.run(body(...))` in `compile/node_doors.py`, one loop
per node call, created and closed inside that call. That is correct for one
node and wrong for two, because a node body does not only *use* a loop, it
**leaves things bound to it**: a model client caches an async transport, and
`httpx`/`httpcore` hold a connection pool whose sockets belong to the loop
that opened them. The second node call finds that loop closed.

    POST /api/runs   morning-brief   -> 502 RuntimeError: Event loop is closed

Measured live on 2026-08-27: `morning-brief` — a lead and three fanned-out
workers — failed at 8.3 s through `CompiledWorkflow.ask`, and answered in
13.7 s when the whole run was driven on a single loop instead.

## Why the fix is here and not in `node_doors`

**A loop needs an owner, and a node is not one.** The node door is reached
once per node call and knows nothing about the run around it, so the only
loop it can own is one it creates and destroys inside its own call — which is
exactly the defect — or a process-wide loop, which is a shared mutable with
none of the properties that make `mcp_sessions.py`'s daemon loop defensible.
That module owns a loop for the life of the process **because MCP transports
must outlive a call**, and it says in as many words that it is deliberately
*not* an ambient loop for graph code to run on. Putting user node bodies on
such a loop would serialise every blocking body in the process onto one
thread and would deadlock the moment a body reached a synchronous door of its
own.

The run *does* have an owner: the door that started it. So the loop's
lifetime is **the run**, and it is opened and closed by the four blocking
doors — `POST /api/runs`, the MCP server's `run_workflow`,
`CompiledWorkflow.ask`/`resume` (the library path a package's own `tests/`
uses) and the CLI, which reaches the library one.

## The correction — the run is not always the owner (`launch-readiness/171`)

That paragraph was true of the loop and silent about the client, and the
silence was the next defect. A stranger installed the wheel and ran the
README's headline shape:

    lap0: 'banana'   lap1: ''   lap2: 'banana'   lap3: ''

**Every second `ask` answered nothing, silently.** Exact alternation, 5 of 10
on two independent ten-lap trials, identical on three packages, on Anthropic
as well as on Ollama. It is this same defect one scope up: `load_workflow`
builds the model **once** and the `CompiledWorkflow` holds it for its whole
life, so run 2 reached a keep-alive connection pool bound to the loop run 1
closed on its way out. Run 3 answered because run 2's failure discarded the
dead connection, which is the alternation.

So the rule this module states is narrower than "the run owns the loop", and
it is the rule that survives both instances:

> **The loop is owned by whatever owns the transport, and never by anything
> shorter-lived.**

Read against each door, that is not a change of answer for three of them:

| door | who owns the client | who owns the loop |
| --- | --- | --- |
| `POST /api/runs` | the request — `_build_model` per call | the run |
| MCP `run_workflow` | the call — `build_chat_model` per call | the run |
| `openstategraph run` | one ask, then the process exits | the run |
| `CompiledWorkflow.ask` / `resume` | **the workflow** — built in `load_workflow` | **the workflow** (`RunLoop`) |

**Why not shorten the client instead.** A client per run is a connection pool
per question, which is the handshake-per-call defect `777e829` measured and
fixed (1.21 s → 0.54 s). Paying it back to fix a loop-scope bug would be
trading a measured win for a bug that has a cheaper answer.

**Why a thread of its own and not `run_until_complete` on the caller's.**
Because of the second thing the lifetime has to survive: a workflow is a fair
thing to hold in a server and ask from two threads at once. Two
`run_until_complete` calls on one loop object is a `RuntimeError`; two
`RunLoop.run` calls interleave on the one loop, which is exactly what the
streaming door has always done under uvicorn — and `serve` is the surface
this defect was invisible to, precisely because its loop already outlived the
run.

**And this is not the ambient loop the section above refuses.** That refusal
is about a *module-level* loop for `compile/node_doors.py` to reach — a shared
mutable owned by nobody, reached by a node body that knows nothing about the
run around it. A `RunLoop` is owned by one object, closed by that object's
`close()`, and never looked up: it is passed in. Blocking `def` node bodies
are still dispatched to threads by LangGraph itself, so nothing serialises on
it, and a body that reaches a synchronous door of its own still gets
`to_completion`'s thread rather than a deadlock. Both are true under uvicorn
today.

## What this changes, stated plainly

The blocking doors now drive the compiled graph through `ainvoke` rather than
`invoke`, so a run through a blocking door executes exactly as the streaming
door's `astream` already does: one loop, migrated bodies on it, un-migrated
`def` bodies dispatched to a thread by LangGraph itself. **One execution
model instead of two** — which is worth more than the bug, because the
streaming door is the one under live load, and two models is two sets of
behaviour to keep true.

It is not a cancellation improvement and must not be read as one. The caller
still blocks; `to_completion` runs the loop to completion like any other
blocking call. *Stop means stop* still requires the async door.

`compile/node_doors.py` stays exactly as it is, and is still needed: a `def`
body is untouched, and a caller holding the escape hatch may still call
`compiled.invoke(...)` directly. That caller keeps the old per-node-call
loop, and therefore keeps this defect. `async-first/13` settled what to do
about it: **the loop stays, and the failure learns to name the fix.** A
run-scoped loop for the node door was rejected a second time on a measurement
— a node body has no `run_id`, `checkpoint_ns` is per node, `thread_id` is the
conversation rather than the run, and no signal at all says a run has *ended*,
so there is still no owner — and refusing at compile time was rejected because
more than one migrated body is not a predicate for failure. See `_WRONG_DOOR`
in `compile/node_doors.py`.

**One seam, not four call sites.** Four doors that each had to remember two
calls is the defect `api/diagram.py` was created to end for Mermaid, with a
test that fails when a fifth surface writes its own. The same test is here:
`tests/test_a_fan_out_answers_the_blocking_door.py` parses every module under
`openstategraph/` for a bare `.invoke(` on a compiled graph.
"""

from __future__ import annotations

import asyncio
import contextvars
import threading
from concurrent.futures import Future
from typing import Any, Callable, Coroutine, TypeVar

T = TypeVar("T")

__all__ = ["RunLoop", "invoke_run"]


class RunLoop:
    """One event loop, for as many runs as its owner lives through.

    Held by a caller that **caches a provider client** — today exactly one,
    `CompiledWorkflow` — because a cached client's pooled sockets belong to
    the loop that opened them, and a loop that dies between runs takes them
    with it. See this module's docstring for the rule and for why the client
    is not shortened instead.

    Cheap to construct and lazy to start: the thread appears on the first
    `run`, so a workflow that is loaded and never asked costs nothing. A
    daemon thread, so a process that forgets to `close()` still exits.
    """

    __slots__ = ("_lock", "_loop", "_thread")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

    def run(self, make_coroutine: Callable[[], Coroutine[Any, Any, T]]) -> T:
        """Drive one coroutine to completion on this loop, blocking the caller.

        **The caller's context is copied in**, and that is not tidiness:
        `ask()` wraps its run in `get_usage_metadata_callback()`, a context
        variable set on the calling thread, so a loop on a thread of its own
        that did not copy it would report every run's token usage as empty —
        the blank panel beside a green suite of `launch-readiness/110`. The
        same reason `abc/async_doors.to_completion` copies it, and the reason
        `asyncio.run_coroutine_threadsafe` is not enough on its own: the task
        it makes inherits the *loop thread's* context, not the caller's.
        """
        loop = self._started()
        context = contextvars.copy_context()
        answer: Future[T] = Future()

        def start() -> None:
            # Inside `context`, so the task created here inherits it.
            try:
                task = loop.create_task(make_coroutine())
            except BaseException as exc:  # pragma: no cover - a bad factory
                answer.set_exception(exc)
                return
            task.add_done_callback(_settle(answer))

        loop.call_soon_threadsafe(start, context=context)
        return answer.result()

    def close(self) -> None:
        """Stop the loop and join its thread. Idempotent, and never raises.

        Called by the owner's own `close()` — `CompiledWorkflow.close()` —
        beside the sqlite handles that load opened, because they are the same
        kind of fact: things this object opened and must therefore release.
        """
        with self._lock:
            loop, thread = self._loop, self._thread
            self._loop, self._thread = None, None
        if loop is None:
            return
        loop.call_soon_threadsafe(loop.stop)
        if thread is not None:
            thread.join(timeout=5)
        loop.close()

    def _started(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is None:
                self._loop = asyncio.new_event_loop()
                self._thread = threading.Thread(
                    target=self._loop.run_forever,
                    name="osg-run-loop",
                    daemon=True,
                )
                self._thread.start()
            return self._loop


def _settle(answer: "Future[Any]") -> Callable[[Any], None]:
    """Hand a finished task's outcome to the waiting caller, whichever it is."""

    def done(task: Any) -> None:
        if task.cancelled():  # pragma: no cover - nothing cancels this task
            answer.cancel()
            return
        error = task.exception()
        if error is not None:
            answer.set_exception(error)
        else:
            answer.set_result(task.result())

    return done


def invoke_run(
    graph: Any,
    payload: Any,
    config: Any = None,
    *,
    loop: RunLoop | None = None,
    **extra: Any,
) -> Any:
    """Run `graph` to completion from synchronous code, on a single loop.

    `payload` is whatever `ainvoke` takes — the initial state, or a
    `Command(resume=...)` for a paused thread. `extra` carries the keyword
    arguments a door passes through untouched (`context=`), which is `None`
    means *pass no argument at all* honoured by the callers rather than
    invented here.

    `loop` is the door's own, and passing one is how a door says *my client
    outlives my run*. Omit it and the run gets a loop of its own for its own
    length, which is correct for the three doors that build a model per call.

    Without a `loop`, safe from a thread that already has a running loop:
    `to_completion` detects that and gives the run a thread of its own with a
    loop of its own, because `asyncio.run` refuses to nest. That is the same
    answer `abc/async_doors.py` gives one layer down, and it is imported
    rather than written again — two spellings of one feature is the
    duplication rule failing. A `RunLoop` is safe there for the same reason
    by construction: it never runs on the caller's thread at all.
    """
    if loop is not None:
        return loop.run(lambda: graph.ainvoke(payload, config, **extra))

    # Imported inside the call: `import openstategraph` must stay cheap, and
    # `openstategraph.abc` re-exports the whole ladder surface at import time.
    from openstategraph.abc.async_doors import to_completion

    return to_completion(lambda: graph.ainvoke(payload, config, **extra))
