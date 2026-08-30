# The graph is compiled on every request, and it costs 27 ms

**Status: measured 2026-08-29, and the cache is declined.** Resolves
`launch-readiness/113`, whose own first instruction was *measure before
building*. The number said no, so no cache was written. This document exists
because the suspicion will be raised again — it is the obvious one — and
"someone measured it once" is worth nothing if the measurement is not written
down beside the argument.

The instrument is committed: `scripts/measure_setup_path.py`. The claim is
pinned: `backend/tests/test_the_setup_path_stays_cheap.py`.

---

## What was measured

Everything `api/routes/runs.py` does before the graph starts, and nothing else:

| Segment | What happens |
| --- | --- |
| `compiler.plan(document)` | the document is read into a plan |
| `services.runtime_for(...)` | **every `tools/*.py` is `exec_module`d** (`api/capability_discovery.py` deliberately bypasses `sys.modules`), every `skills/*.md` is read |
| `compiler.build(...)` | the `StateGraph` is assembled and compiled |

No model, no network, no spend — the measurement uses a stub model that raises
if anything calls it, so a number from this instrument cannot have a model call
hiding inside it. The socket pin in the test file says the same thing the other
way round.

Measured in the backend, not the browser, because `launch-readiness/108` says
the timeline panel is not yet trustworthy and every duration the editor shows is
`performance.now()` on frame arrival in the tab.

## The numbers

A private package — 28 nodes, four `tools/*.py`
importing Databricks and sqlglot, five `skills/*.md` totalling 10,889 bytes.
The heaviest real package this project has; deliberately not a toy.

| | pass 1 (cold process) | warm passes | mean warm |
| --- | --- | --- | --- |
| **run 1** | 156.2 ms | 28.7 / 26.5 / 26.9 ms | **27.4 ms** |
| **run 2** (fresh process) | 156.7 ms | 26.0 / 26.3 / 27.3 ms | **26.5 ms** |

Split, warm: `plan` 0.5 ms · tool import + skill read **13 ms** · `build`
**13 ms**.

Two smaller packages, for shape rather than for the decision:
`guarded-lookup` (7 nodes, one tool) **6.4 ms**; `nested-mounts` (three
documents, three levels) **9.5 ms** — a mount compiles its child and it is
still single-digit milliseconds.

**Pass 1 is not a per-request cost.** It is lazy imports — `langchain`,
`databricks`, `sqlglot` — landing in `sys.modules` on the first document a
process compiles. A live server pays it once, on the first run after start.
Read the warm rows.

## What fraction of a turn that is

`launch-readiness/109`'s head-to-head stopwatch measured whole turns of
27.63 s, 39.71 s and 56.63 s on that package, of which **97–99 % was model
inference**.

> **27 ms of a 27.6 s turn is 0.10 %. Of the 39.7 s median, 0.07 %.**

It is smaller than the jitter on a single model call — individual calls in that
session ran 2.21 s to 9.15 s. And it is a third of the gap between two runs of
the *same question*, which varied by 29 s purely on how many ReAct laps the
model chose to take.

The earlier estimate on `109` — "≤ 60 ms, ~0.15 % of the turn" — was taken from
response-header timing on an MCP package that ships **no** `tools/*.py`.
This measurement is the one that includes the tool-import half the ticket was
actually worried about, on the package that has the most of it, and it lands
lower rather than higher.

## The decision

**No compiled-graph cache.** Not because caching would be wrong in principle,
but because the price of the cure is larger than the disease by orders of
magnitude, and it is paid in the currency this repository is worst at:

> Every correctness defect on `launch-readiness` is **two situations rendering
> identically**. A stale compiled graph is exactly that shape — a developer
> edits a node, runs it, sees the old behaviour, and nothing on screen says
> why. Buying 27 ms with a new instance of the defect class that has cost this
> map the most is a bad trade at any latency.

`113`'s own trap section reaches the same place from the other side, and this
is what makes the invalidation genuinely hard rather than merely fiddly: the
sanctioned `code → canvas` channel means a package's behaviour can change with
`workflow.json` untouched. Keying on the document is **not** sufficient.

## If it is ever revisited, this is the invalidation list

Recorded so that a future attempt starts from the full list rather than
rediscovering it one stale run at a time. A cache that misses **any** of these
is worse than no cache:

1. **The document** — a save through `/api/workflows/{slug}`, and the same
   document arriving inline on a request that names no slug.
2. **`tools/*.py`** — content, not just mtime granularity; a file added, a file
   deleted, a file edited. This is the channel `workflow.json` cannot see.
3. **`functions/*.py`** and **`middlewares/*.py`** — same channel, same
   argument.
4. **`skills/*.md`** — read into the prompt at setup, so an edit changes
   behaviour with no document change.
5. **`knowledge/`** — the second brain a package's tools bind against.
6. **A capability refresh** — `api/capability_discovery.py` re-import is what
   the editor's refresh *is*; a cache that survives one makes the refresh
   button a lie.
7. **Every mounted child package, transitively** — a mount is by reference, so
   a child's document, tools, skills and knowledge are all inputs to the
   parent's compiled graph. `NodeRuntime.mounted_graphs` already records the
   set the compiler actually reached, which is the honest key rather than a
   re-derivation from the document.
8. **Provider and credential state** — the resolved model is built into the
   graph's closures.

And two conditions on the mechanism itself, which is where an async-first
codebase gets this wrong:

- **A lock around a cache is a place to serialise concurrent requests.** OSG is
  async-first (`docs/decisions/async-seam.md`). Any cache introduced here would
  need a concurrency proof, not a comment.
- It would have to cache the **compiler's output** and interpret nothing.
  That part is easy and would have been fine — caching a compiled artifact does
  not make us a runtime, and it reads no runtime object back into the model, so
  neither *"never write an execution engine"* nor portability rule 3 is
  troubled by it. **The architecture was never the objection. The invalidation
  surface is.**

## Where the time actually goes, for `109`

Nowhere in this repository. `109`'s own conclusion stands and this measurement
strengthens it: 97–99 % of a turn is model inference, the "ours" bucket is
0.09–0.13 s of a 27–57 s turn, and per-request compile is a quarter of that
bucket. The lever is `reasoningEffort` and the number of ReAct laps, which is
the owner's decision, not ours.

The one thing worth keeping an eye on is the *cold* pass — 156 ms on the first
run after a server starts. That is a first-user-of-the-morning cost, not a
per-turn cost, and if it ever matters the fix is to warm the imports at startup
rather than to cache a graph.
