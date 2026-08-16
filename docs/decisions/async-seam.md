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
