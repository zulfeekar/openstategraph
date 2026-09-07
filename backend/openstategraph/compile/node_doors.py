"""One node body, both doors — the bridge Phase D needed and had not sized.

`async-first/06`. `docs/decisions/async-seam.md` establishes that sync and
async node bodies **coexist** inside one graph, because LangGraph converts a
node function to a `RunnableLambda`, "which add batch and async support to your
function". That is true, and it is what makes Phase D a per-family migration
rather than a big bang.

It is also only half the question, and the other half is about the *caller*
rather than about the graph. Measured on the installed `langgraph 1.2.10`:

    >>> compiled.invoke({...})
    TypeError: No synchronous function provided to "n".
    Either initialize with a synchronous function or invoke via the async API
    (ainvoke, astream, etc.)

A `RunnableLambda` built from a coroutine function has an async door and no
sync one, so **one** `async def` node makes the whole compiled graph
async-only. This backend has four synchronous doors onto the same compiled
object — the blocking `/api/runs`, the MCP server, `CompiledWorkflow.run` (the
library path a package's own `tests/` uses) and the CLI — and none of them is
in this map's scope. Migrating `_agent` alone, without this module, took 203
tests red.

**So the body stays single and the adapter is the pair.** LangGraph's own
`RunnableCallable` takes a sync function *and* an async one; the async door is
the migrated body itself, and the sync door runs that same body on a private
loop. Nothing is written twice: two spellings of one node body is the
duplication rule failing in the place it is most expensive, since the two would
drift and only one of them would be under test.

**`RunnableCallable` and not `RunnableLambda`, and that was measured rather
than preferred.** `RunnableLambda` works — both doors answer, narration
survives, cancellation still reaches the async body — but LangGraph asks a
`Runnable` node for its `deps`, which calls `langchain_core`'s
`get_function_nonlocals`, an `lru_cache(maxsize=256)` **keyed on the sync
function**. A node closure holds this workflow's tools and model, so 256 stale
compiles' worth of them are pinned in a process-wide cache that nothing here
can clear: caught by `tests/test_production_audit_2026_08_15.py`, which fails
on object growth across repeated compiles and read 265 objects per cycle.
`RunnableCallable` is the type LangGraph already wraps a plain `def` node in,
so a migrated node is the same shape as an un-migrated one rather than a
foreign one, and it is not asked for `deps` at all — measured at zero drift
over the same 25 cycles.

This is the mirror of what Phase A did at the other end of the same seam
(`async-first/02`): one checkpointer shared by transports that are not all
async, bridged rather than swapped, applied at the doors and nowhere else.

**What each door is worth, stated plainly so nobody mistakes the bridge for
the feature.** The async door is genuinely cancellable — cancelling the task
driving `astream` stops the body outright, which is the whole of this map's
promise. The sync door is not, and cannot be: `asyncio.run` on a private loop
is a blocking call like any other, and this is precisely today's behaviour
preserved rather than an improvement smuggled in. A caller who wants *stop
means stop* has to come through the async door, which the streaming run path
already does.

**Applied once, at the compiler's own `add_node` call**, which is the last
thing between a node body and LangGraph and the seam every node of every family
passes through — including families contributed by an installed distribution,
which therefore gain the sync door without knowing this module exists. Outside
`recording_attempts` rather than inside it, so that wrapper keeps seeing the
raw body it already knows how to handle in either kind. Never on a base class: a sync door is needed by node families
that share no ancestor, so it is a collaborator (CLAUDE.md's boundary rule),
and never per builder: a builder that had to remember is a builder that
eventually will not.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Callable

__all__ = [
    "both_doors",
    "interruptible_nodes",
    "is_interruptible",
    "with_both_doors",
]

#: Set on the two-door pair, and read back off the compiled graph.
#:
#: **The marker exists because the fact is not otherwise readable**
#: (`async-first/07`). LangGraph gives *every* node an `afunc` — a plain `def`
#: gets one that hops to an executor — so "has an async door" cannot tell a
#: migrated body from a threaded one. Measured on the installed 1.2.10 against
#: `morning-brief`: all seven nodes reported `afunc`, only four were
#: cancellable. What distinguishes them is who installed the door, which is
#: knowable exactly here and nowhere downstream.
INTERRUPTIBLE = "__openstategraph_interruptible__"


#: The message `asyncio` raises when a resource outlives the loop that made it.
#: Matched as a substring because it arrives wrapped — LangGraph appends
#: ``During task with name '<node>'`` — and because the raiser is
#: `asyncio.base_events`, not a library whose exception type we could catch.
_CLOSED_LOOP = "Event loop is closed"

#: What that failure means when it comes out of the sync door, and the one
#: thing a reader can act on (`async-first/13`).
#:
#: **A diagnosis, raised at the failure rather than refused at compile.** The
#: ticket's second shape was to detect at build time — the compiler knows how
#: many `INTERRUPTIBLE` nodes a graph has — and that is wrong, because more
#: than one migrated body is not a predicate for failure: two `async def`
#: nodes with nothing loop-bound in them run through `.invoke()` perfectly
#: well, and so does a pair sharing a pooled `httpx.AsyncClient`. Refusing
#: them would refuse working code, and `CompiledWorkflow.graph` is documented
#: as unwrapped precisely because wrapping it is where the execution engine
#: this project refuses to write would begin. So nothing that works stops
#: working; only the run that was already dead learns to say which door.
#:
#: It is chained (`raise ... from exc`), never substituted. A diagnosis is a
#: guess about somebody else's traceback, and the day a body raises this for a
#: reason of its own, `__cause__` is what says so.
_WRONG_DOOR = (
    "This graph has an async node body and was driven through LangGraph's "
    "synchronous API, which gives one event loop per node call — a connection "
    "pool, a model client's transport, or anything else a body leaves bound to "
    "the first loop does not survive the second. Drive the compiled graph with "
    "`ainvoke` / `astream` instead, or use a door this package ships "
    "(`workflow.ask(...)`, `openstategraph run`, `POST /api/runs`), which run "
    "one loop for the whole run. See 'The escape hatches' in "
    "docs/what-is-this.md."
)


def both_doors(body: Callable[..., Any]) -> Any:
    """`body`, presented to LangGraph with a sync door as well as an async one.

    `body` must be a coroutine function; callers that may hold either kind
    want `with_both_doors`, which is total.
    """
    from langgraph.utils.runnable import RunnableCallable

    def through_a_private_loop(*args: Any, **kwargs: Any) -> Any:
        # **This loop is per node call, and that is a real limit** — read
        # `openstategraph/run_doors.py` before changing anything here.
        # `async-first/12`: a node body does not only use a loop, it leaves
        # things bound to it (a model client's pooled sockets), so a second
        # node call driven this way finds the first one's loop closed —
        # `RuntimeError: Event loop is closed`, measured live against
        # `morning-brief`. The four blocking doors no longer come this way:
        # they drive `ainvoke` on a loop that lives as long as the *run*,
        # which is the scope that actually has an owner. What still comes
        # here is a caller holding the escape hatch and calling
        # `compiled.invoke(...)` itself, and a graph LangGraph drives
        # synchronously for its own reasons. `async-first/13` decided to keep
        # it that way and diagnose instead — see `_WRONG_DOOR` above for the
        # argument, and for the two shapes that were rejected.
        #
        # `asyncio.run` and not a shared loop, deliberately. A sync door is
        # reached from a thread with no loop running — a FastAPI threadpool
        # worker, a pytest process, the CLI — so there is nothing to reuse,
        # and a module-level loop would be a shared mutable this module has no
        # reason to own. The `Task` it creates copies the ambient context, so
        # `get_stream_writer()` and `ensure_config()` still answer from inside
        # the body: pinned in
        # `tests/test_a_migrated_node_still_answers_the_sync_door.py`, because
        # a lost writer is a blank panel with a green suite
        # (`launch-readiness/110`).
        try:
            return asyncio.run(body(*args, **kwargs))
        except RuntimeError as exc:
            if _CLOSED_LOOP not in str(exc):
                raise
            raise RuntimeError(_WRONG_DOOR) from exc

    pair = RunnableCallable(
        through_a_private_loop, body, name=getattr(body, "__name__", None)
    )
    # Said on the object rather than recorded in a table beside it: a table is
    # a second place to keep in step, and this one would be keyed on node ids
    # that only the compiler ever sees. See `INTERRUPTIBLE`.
    setattr(pair, INTERRUPTIBLE, True)
    return pair


def is_interruptible(node: Any) -> bool:
    """True if cancelling the task driving `astream` cancels this node's body.

    False for everything else, including things that are not nodes at all —
    `__start__`, LangGraph's error handler, `None`. **Never true by omission**:
    a `False` earns the sentence this product has always shown a stopped run
    ("steps already dispatched finish in the background"), so an unrecognised
    node keeps the claim that was honest before any of this existed.

    It is not the whole truth about a cancelled body and must not be read as
    one. A cancelled body unwinds at its **next await**, so the model call
    already in flight is still paid for — measured at 0.41–4.85 s across nine
    live runs on 2026-08-27, against 12.65–24.16 s for the same fan-out
    running to completion. The claim this supports is "the step was
    cancelled", never "nothing is running".
    """
    return bool(getattr(node, INTERRUPTIBLE, False))


def interruptible_nodes(graph: Any) -> set[str]:
    """The LangGraph node names of `graph` whose bodies a stop cancels.

    Empty for anything that cannot be asked — which is most of the test
    suite's stub graphs, and would be a plugin-supplied graph object too. An
    empty answer costs a reader the *better* of two true sentences; a raise
    would cost them the run.
    """
    nodes = getattr(graph, "nodes", None) or {}
    try:
        items = nodes.items()
    except AttributeError:  # pragma: no cover - a graph shaped like nothing
        return set()
    return {
        name
        for name, node in items
        if is_interruptible(getattr(node, "bound", None))
    }


def with_both_doors(node: Any) -> Any:
    """`node` if it is already synchronous, else the two-door pair.

    Total, and the sync case is **identity**: a `def` body handed on untouched
    is a `def` body LangGraph wraps in its own `RunnableCallable`, exactly as it
    did before this module existed. Wrapping one here would replace that with
    ours for no behaviour anybody asked for, and would make every un-migrated
    family's diff non-empty for the same nothing.
    """
    if inspect.iscoroutinefunction(node):
        return both_doors(node)
    return node
