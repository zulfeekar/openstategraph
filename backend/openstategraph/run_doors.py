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
loop, and therefore keeps this defect — `async-first/13` carries the argument
for why the escape hatch is a narrower promise than a door, and the three
shapes a fix there could take.

**One seam, not four call sites.** Four doors that each had to remember two
calls is the defect `api/diagram.py` was created to end for Mermaid, with a
test that fails when a fifth surface writes its own. The same test is here:
`tests/test_a_fan_out_answers_the_blocking_door.py` parses every module under
`openstategraph/` for a bare `.invoke(` on a compiled graph.
"""

from __future__ import annotations

from typing import Any

__all__ = ["invoke_run"]


def invoke_run(graph: Any, payload: Any, config: Any = None, **extra: Any) -> Any:
    """Run `graph` to completion from synchronous code, on a single loop.

    `payload` is whatever `ainvoke` takes — the initial state, or a
    `Command(resume=...)` for a paused thread. `extra` carries the keyword
    arguments a door passes through untouched (`context=`), which is `None`
    means *pass no argument at all* honoured by the callers rather than
    invented here.

    Safe from a thread that already has a running loop: `to_completion`
    detects that and gives the run a thread of its own with a loop of its own,
    because `asyncio.run` refuses to nest. That is the same answer
    `abc/async_doors.py` gives one layer down, and it is imported rather than
    written again — two spellings of one feature is the duplication rule
    failing.
    """
    # Imported inside the call: `import openstategraph` must stay cheap, and
    # `openstategraph.abc` re-exports the whole ladder surface at import time.
    from openstategraph.abc.async_doors import to_completion

    return to_completion(lambda: graph.ainvoke(payload, config, **extra))
