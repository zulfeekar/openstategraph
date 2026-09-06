# The async seam: a size, and where the work belongs

**Status: recommendation recorded 2026-08-16.** Resolves organisms-first-class
ticket 25 (`.scratch/organisms-first-class/tickets/25-*.md`), which asked for a
size and a decision about where the work belongs — explicitly **not** for the
work. No code was written for this document.

Tracked here rather than left on the map because it is a standing answer to a
question that will be asked again: *why is this backend synchronous, and what
would changing it cost?* A map is deleted when it closes; this outlives it.

Measurements re-taken **2026-08-16** against the versions this repository
currently resolves: `langgraph 1.2.10`, `langchain 1.3.14`, `langchain-core
1.5.3`, `langgraph-checkpoint 4.2.0`, `fastapi 0.141.1`, Python 3.13. The
research file measured on 2026-08-14 and one of its numbers has already moved
(below), which is the reason gate 11 exists.

---

## The framing, first, because everything else is downstream of it

> **Going async is a change to the compile seam, not to the endpoint.**

This is the single most important sentence in the document, and it is easy to
get wrong in the opposite direction: `api/streaming.py` is where the blocking
shows up, so it reads like a FastAPI tidy-up. It is not. The endpoint is
blocking *because every node it runs is*, and swapping `graph.stream` for
`graph.astream` in a file that drives 13 synchronous node builders changes
nothing a user could observe.

Every async finding in the whole sweep is upstream-blocked here.

---

## What is actually true today

| Fact | Now (2026-08-16) | Research said (2026-08-14) |
| --- | --- | --- |
| `async def` in `compile/` | **0** | 0 |
| `def` in `node_runtime.py` | **67** | 56 |
| `await` anywhere in `compile/` | **0** | 0 |
| `ainvoke` / `astream` calls in the backend | **0** | 0 |
| `async def` in `api/` | **12** | — |
| Node builders in the registry | **13** | — |
| `.invoke(` sites in `compile/` + `abc/` + `prebuilt_*` | **8 + 4 + 1 = 13** | — |
| `def _execute` (the tool ladder) | **26**, of which async: **0** | — |

The one `ainvoke`/`astream` grep hit in the whole backend is a **docstring**
(`loader.py:72`, listing what a compiled graph can do). Nothing calls either.

Two details worth stating precisely because they are counter-intuitive:

- **The run endpoints are not async either.** `run_workflow_stream` and
  `resume_workflow_stream` (`api/routes/runs.py:273`, `:396`) are plain `def`.
  The 12 `async def`s in `api/` are auth middleware, the lifespan hook, the
  `/api/events` catalogue feed, and the two disconnect racers in
  `streaming.py`. The run path reaches asyncio only through
  `iterate_in_threadpool` at `streaming.py:443`.
- **`node_runtime.py` grew 11 `def`s in two days.** The file is 3032 lines. A
  size quoted against it decays; this document is dated for that reason.

---

## The fact that decides the shape of the migration

**Sync and async node builders coexist, by construction, with no adapter from
us.** LangGraph converts a node function to a `RunnableLambda`, which — the
graph-api doc's own words — "add batch and **async** support to your function".
So `graph.astream()` over a graph whose nodes are all `def` works *today*, and
a half-migrated graph is not a broken graph.

That removes the worst possibility: this is **not** a big-bang. It is a
per-family migration that can land one node family per commit.

**But coexistence buys nothing on its own, and this is where a plan would
over-promise.** A sync node running under `astream` is run in a worker thread,
which is exactly what `iterate_in_threadpool` already does for the whole
generator. It still cannot be interrupted mid-call. So:

> The cancellation win is **per node, not per graph**, and it only arrives for
> the nodes that are actually long — `_agent`, `_worker`, `_orchestrator`,
> `_subgraph`. Migrating `_static_text` first would be measurable in nothing.

An incremental plan is therefore honest only if it is ordered by node duration
rather than by node simplicity, which is the opposite of the order a
refactorer naturally picks.

---

## What it buys

Re-confirmed against the current tree, not restated from the sweep:

1. **Cancellation that cancels.** `stop_when_client_leaves` already names its
   own ceiling: the pending step "is a blocking model call that cannot be
   interrupted", so a client disconnect **abandons** rather than cancels. The
   comment in `_stream_run`'s `GeneratorExit` handler puts numbers on it,
   measured live: an early stop trailed model calls for ~15s, a stop
   mid-fan-out for ~75s. This is the only user-visible item on the list.
2. **Concurrent consumption of the projections** (`asyncio.gather`) — but see
   the sequencing note: that is **ticket 24's** benefit, not this one's.
3. **Async subagents at all** — ticket 20, which is already parked behind this.
4. **`astream_events`**, the surface the docs now lead with.

Note what is *not* on the list: throughput. The Deep Agents production page is
explicit that LangChain already "runs sync tools in a separate thread to avoid
blocking", and native async merely "avoids the threading overhead entirely".
Nobody has reported a thread-pool ceiling here, and one worker thread per live
run is not a number this project is anywhere near.

---

## The size, in phases

Ordered by dependency, not by preference. Each is separately shippable, which
is a consequence of the coexistence fact above.

| Phase | What | Size | The trap |
| --- | --- | --- | --- |
| **A** | `_run_frames`/`_stream_run` → `async def`, `graph.astream`, drop `iterate_in_threadpool`, the two route handlers → `async def` | **M** | The source change is small. **Nine test files script this fold** with hand-written chunks and a `for` loop; every one needs an async driver. The cost is in tests, and it is most of the phase. |
| **B** | `AsyncSqliteSaver` beside `SqliteSaver` (`memory.py:794`, `:819`) | **S**, plus a dependency | Needs `aiosqlite`, which this project does not currently ship. `memory.py` already carries two savers and a comment at `:886` about how non-obvious their behaviour is; this makes it four code paths, not three. |
| **C** | Async variants on the **published ladders** — `BaseTool`, and the router/grader/agent/orchestrator families | **M, and a stability event** | The one most likely to be under-estimated. See below. |
| **D** | The node builders themselves, longest-running first | **M–L** | 13 builders, but only **13 `.invoke(` sites** across `compile/`, `abc/` and `prebuilt_*`. The fan-out is in the closures around them, not in the model calls. Smaller than `node_runtime.py`'s 3032 lines suggest. |

### Phase C is a stability-contract event, not a refactor

`BaseTool` is **Tier 1, semver-public** — `docs/stability.md`'s "Tier 1,
exactly" block lists it, `backend/tests/public_api.txt` pins its signature, and
`openstategraph.abc`'s own docstring calls the tool ladder "the *most* public
thing the framework ships". There are 26 `def _execute` implementations in
tree and every adopter's `tools/*.py` has one.

So `_execute` **cannot become `async def`**. That is a breaking change to
published API, and `docs/stability.md`'s deprecation policy would apply: ship
the shim first, and pre-1.0 a breaking change bumps MINOR. The workable move is
an **added** `_aexecute` whose default implementation runs `_execute` in a
thread — additive, no adopter touched, and the same shape LangChain itself uses
(`invoke`/`ainvoke` side by side on one class).

Anyone sizing this as "make the functions async" has missed this phase
entirely, which is the main reason the ticket asked for a written size.

---

## Answers to the three questions the ticket asked

**One refactor or a per-family migration?** A **per-family migration**, in four
dependency-ordered phases, ordered *within* phase D by how long a node
actually runs. Not one refactor.

**Can sync and async node builders coexist during it?** **Yes, with no work
from us** — LangGraph wraps node functions in `RunnableLambda` and supplies the
async support. The caveat that matters: an un-migrated node keeps today's
"abandons rather than cancels" behaviour, so a partially migrated graph has
partially migrated cancellation. There is no point at which the feature is
half-true; there is a point at which it is true for some nodes.

**Does it belong on this map?** **No.**

---

## Recommendation to the owner: defer to a new map, sequenced after 24

Three reasons, in order of weight.

1. **Ticket 24 may make phase A's work partly wasted.** 24 is deciding whether
   to adopt `stream_events(version="v3")` and its projections, which would
   replace the ~500-line fold that phase A is about to rewrite — and that
   surface has its own async story (`asyncio.gather` over projections is
   listed as *24's* benefit precisely because it is unreachable without it).
   Rewriting the fold for async and then replacing the fold is the one
   sequencing mistake available here.
2. **It touches three things this map does not otherwise touch**: a published
   ladder under the deprecation policy, a new runtime dependency, and the
   compile seam. `organisms-first-class` is a docs-sweep map whose stream-seam
   tickets were deliberately sized S, M, M. This is none of those.
3. **The map's stream-seam work is done without it.** 21, 22 and 23 have
   landed and not one of them needed async. That is the empirical answer to
   "is this blocking the map": it was not.

**What the new map would be called and contain:** cancellation is the user-
visible promise, so the map is about *stopping a run*, not about *asyncio*.
Phases A–D above are its tickets, with phase C filed first as a design ticket
(the `_aexecute` shim shape) because it is the one with a published contract
attached.

**What to do on this map instead: nothing.** No preparatory refactor. A
"make it async-ready" pass with no async caller is the kind of speculative
generality CLAUDE.md's portability section already refuses to pay for.

---

## Carried into tickets 20 and 24

Both were written assuming an answer here and now point at this file:

- **20 (async subagents)** was already "parked behind the stream seam" and
  named 24 and 25 as upstream. 25 is now answered: the seam it is waiting for
  is a *new map*, so 20 is parked behind that map rather than behind this one.
- **24 (adopt the projection or keep deriving)** must be argued **before** the
  async map is scheduled, per reason 1 above — not after, and not in parallel.
  **Superseded — see the amendment below.**

---

## Amendment, 2026-08-27: reason 1 does not hold, and was measured

Recorded here rather than only on a map because this document is the standing
answer, and its recommendation was acted on: the owner chartered the async map
anyway, and its first ticket (`async-first/01`) was spent testing exactly the
claim reason 1 rests on.

Reason 1 says adopting `stream_events(version="v3")` "would replace the
~500-line fold that phase A is about to rewrite". Two things in that sentence
are wrong, and they are wrong in opposite directions:

- **Phase A does not rewrite the fold.** It rewrites the fold's *drive* — the
  `async def` on two generators, the `graph.stream` call site, the `for` at
  `streaming.py:1210`, `get_state`, `iterate_in_threadpool`, and the two route
  handlers.
- **The projection does not replace the fold.** It replaces the fold's *front
  end*: `_stream_parts` (`streaming.py:651`) plus the pure helper classes
  `SpawnWatcher`, `ActiveNodeResolver` and `RunPathResolver`, none of which any
  async migration touches, because none of them perform I/O.

The two diffs intersect at one call site and one thirty-line decoder.

Measured against the installed `langgraph 1.2.10` rather than read off the
page, since that is where the surprise was:

- `stream_events(..., version="v3")` emits **only `values` events by default**.
  "Modes that no transformer requests are never emitted" is literal, so an
  adoption is not "consume the typed projections" — every accumulator in
  `_run_frames` is fed from `updates`, and there is no `updates` projection. It
  is "register a `StreamTransformer` declaring `required_stream_modes` and keep
  reading `updates`".
- With one registered, the raw `ProtocolEvent` (`{"seq", "method", "params":
  {"namespace", "timestamp", "data"}}`) carries the same channel names, the
  same `name:runtime_id` namespaces and, for `updates`, the same
  `{node_name: delta}` payload as the v2 `StreamPart` that `_stream_parts`
  decodes today. The `messages` channel is the one branch whose *payload* also
  moves (to content blocks), and it too is a pure decode.
- `version="v3"` raises `LangChainBetaWarning: The v3 streaming protocol on
  Pregel is experimental.` at `pregel/main.py:3708` and `:3558`. Pinning a
  published SSE contract to it is an owner decision, so "keep deriving" stays a
  live outcome of ticket 24.

The test cost that made reason 1 feel expensive is symmetric: the scripted-fold
tests — **21** of them now, not the nine counted on 2026-08-16 — need an async
driver *and* a chunk restamp in either order, and the async half is not thrown
away by an adoption, because an adopting fold calls `astream_events`.

**So the sequencing recommendation is withdrawn, and only that.** Phases A–D
and the phase C stability argument stand exactly as written. The correction is
that ticket 24 need not precede them; if it lands later it inherits an async
fold, which is strictly easier for it than a sync one.

---

## Amendment, 2026-08-27 — the cancellation ceiling, measured (async-first/09)

The charter's headline is *stop means stop*, and `_stream_run`'s
`GeneratorExit` handler stated its ceiling as a fact about the library:
"there is no cancellation seam inside a superstep at this version". Ticket 01
turned up a member that sentence did not mention — `GraphRunStream.abort()`,
alongside `stream_events`' `control: RunControl | None`. Ticket 09 probed both
on the installed `langgraph 1.2.10`, because a claim about a library that
nobody re-checks is exactly the defect class this project keeps paying for.

**The ceiling stands.** `abort()`
(`langgraph/stream/run_stream.py:148`) is `graph_iter.close()` plus a mux
close, wrapped in `except Exception: pass`. From the pumping thread that is
the identical `GeneratorExit` the fold already handles. From any other thread
it is a **silent no-op**: `close()` on a generator inside `next()` raises
`ValueError: generator already executing`, which `abort()` swallows — probed,
the call returned at t=3.00 s raising nothing while the node ran to completion
at 20.01 s, and the caller was handed an empty final state because the mux had
been closed under it. It also requires the experimental v3 protocol
(`GraphRunStream` carries the `@beta` marker on the class), so it costs
something and buys nothing. `RunControl.request_drain()` stops where the
source says it does — its check is the first statement of `PregelLoop.tick()`,
before dispatch — measured at +17.01 s with a 20 s node. LangChain's own
fault-tolerance page agrees in words: drain "does not cancel running asyncio
tasks or kill threads".

**But the number the charter quotes needed relabelling.** Probing the
production shape rather than a bare generator shows `stop_when_client_leaves`
already races the disconnect and abandons the pending step without awaiting
it, so **the client-visible stop is already instant** — 0.00 s, today, with
sync nodes:

| Arm (10 s node, stop at t=3 s) | Client-visible stop | Node body |
| --- | --- | --- |
| today: sync fold + race/abandon | +0.00 s | ran to completion — 9.00 s billed after the stop |
| `astream` + **sync** node, `task.cancel()` | +0.00 s | ran to completion in its worker thread |
| `astream` + **async** node, `task.cancel()` | +0.00 s | **never completed** — genuinely cancelled |

So the ~15 s and ~75 s in the handler are **seconds of model work billed after
the stop**, never latency a user waits through. They remain the right targets;
only their label changes. Phase A moves neither column, which is what the
phase's own ticket already said — it now says it with a measurement.

Corroboration from an independent seam: `add_node(timeout=...)` is the one
construct in 1.2.10 that interrupts a node mid-flight, and
`_internal/_timeout.py` rejects it at compile time for sync nodes — *"Node
timeouts are only supported for async nodes."* Two seams, one conclusion, and
it is the charter's: **the node is the only place cancellation can happen, and
only an `async def` one.**

---

## Amendment, 2026-08-27 — phase B is *upstream* of phase A, and phase A shipped anyway (async-first/02)

The phase table above is headed "Ordered by dependency". On one pair it is
ordered backwards, and phase A found out by running.

`graph.astream()` does not merely prefer an async checkpointer; LangGraph's
async loop calls **only** the async four, and the server's default saver
answers none of them. Measured on the installed `langgraph-checkpoint-sqlite
3.1.1`, first superstep, no model involved:

```
NotImplementedError: The SqliteSaver does not support async methods.
Consider using AsyncSqliteSaver instead.
```

The docs say the same in words — an async run needs `InMemorySaver` or one of
the `Async*` savers — which is why the whole suite went green on the async fold
before anything real did: `conftest.py` opts the tests out of the durable
default, so every fold test holds an `InMemorySaver`, which *does* implement
the async four.

Two of phase B's three sentences also turn out to be wrong, in our favour:

- **`aiosqlite` already ships.** It is a hard dependency of
  `langgraph-checkpoint-sqlite>=3.1`, which is the `[sqlite]` extra that
  `[server]` requires — `pyproject.toml`'s own comment about the extra says so
  two paragraphs above the line that made it sound optional. There is no new
  dependency to add.
- **`AsyncSqliteSaver` is not a drop-in, for a reason the phase table could not
  see.** One saver is shared by every transport, and three of them are still
  synchronous (`/api/runs`, the MCP server, `load_workflow`).
  `AsyncSqliteSaver` answers the *sync* four through
  `run_coroutine_threadsafe` against a loop captured at construction, so it
  cannot be built at all in a plain script. Swapping the shared saver trades a
  broken async path for a broken sync one.

**What phase A did instead**: `memory.async_capable` wraps the shared saver at
the two async doors, supplying the async four over the sync ones in a worker
thread — the same shape LangChain uses for sync tools, which this document
already quotes its production page saying. Additive, applied nowhere else, and
pinned by `backend/tests/test_the_async_run_path_can_use_the_servers_saver.py`,
whose first test **fails on the day the library grows async sqlite support**,
so the bridge cannot quietly outlive its reason.

So phase B is not deleted and not blocking: it becomes an optimisation (drop a
thread hop) rather than the thing that unblocks phase A, and it still owes an
answer to the shared-saver problem above. Its size ("S, plus a dependency")
should be re-taken before it is scheduled.

Nothing else in the phase table moved. Phase A's own claim is unchanged and
was re-confirmed rather than re-derived: it buys no cancellation, per
`async-first/09`'s measurements and the amendment above.

## Amendment (2026-08-27): the blocking doors got a loop of their own

`async-first/12`. This charter's coexistence fact is about **nodes in a
graph**, and phase D's `compile/node_doors.py` answered the other half — the
*caller* — by giving each migrated body a sync door that runs it on a private
`asyncio.run` loop. That is right for one node and wrong for two: a node body
leaves things bound to its loop (a model client's pooled sockets), so the
second node call in the same synchronous run finds the first one's loop
closed. `POST /api/runs` on `morning-brief` returned `502 RuntimeError: Event
loop is closed`; a green suite of 5305 said nothing, because no test drove two
model-calling nodes through a blocking door.

**A loop's owner is the run, and the run is owned by the door.** So the four
blocking doors — `POST /api/runs`, the MCP server's `run_workflow`,
`CompiledWorkflow.ask`/`resume`, and the CLI through the library one — now
drive `graph.ainvoke` through `openstategraph/run_doors.invoke_run` instead of
`graph.invoke`. A blocking run therefore executes exactly as the streaming
door's `astream` already does: one loop, migrated bodies on it, un-migrated
`def` bodies dispatched to a thread by LangGraph itself. **One execution
model instead of two** is worth more here than the bug it fixes.

It buys no cancellation and must not be read as doing so — the caller still
blocks. `node_doors.py` is unchanged and still needed; what still reaches it
is a caller driving `.graph.invoke()` itself, which is `async-first/13`.
