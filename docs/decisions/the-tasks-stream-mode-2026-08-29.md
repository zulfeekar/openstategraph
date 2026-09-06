# The start event we never asked for

*2026-08-29 — `memory-and-replay` 48. Verified against LangGraph **1.2.10**,
the version installed here, and against `/oss/python/langgraph/streaming` on
the `docs-langchain` server. Where the two disagree, this document says so and
the installed package wins.*

## The claim that was wrong

`src/view/ask/timeline.ts` explained its inferred durations by naming a
library limitation:

> `durationMs` is the wall-clock gap since the previous frame … because
> LangGraph's `updates` stream reports a node only *after* it finishes —
> **there is no start event to subtract.**

The first half is true and stays. The second half is a statement about
LangGraph, and LangGraph emits a start event. `api/streaming.py` asks for
three of the seven stream modes:

```python
stream_mode=["updates", "messages", "custom"], subgraphs=True, version="v2"
```

`tasks` is the fourth, and it has been there the whole time. The gap is a
subscription nobody made.

## What `tasks` actually emits

Two events per task, both under `TasksStreamPart` — `{"type": "tasks", "ns",
"data"}` — with no discriminator inside `data`. Telling a start from a finish
is the reader's job: **a finish is the one with a `result` key.**

| Start — `TaskPayload` | |
| --- | --- |
| `id` | a UUID minted per task per superstep. Not a UUID4: it is derived, and stable across a replay of the same checkpoint |
| `name` | the **graph** node name — `worker_web`, and inside an agent `model`, `NarrationMiddleware.before_model` |
| `input` | the state handed to this task. For a `Send`-dispatched worker, that worker's own payload |
| `triggers` | what scheduled it — `("branch:to:plan",)`, or `("__pregel_push",)` for a `Send`. A **tuple**, though the TypedDict annotates `list[str]` |
| `metadata` | only when the task config carried user-meaningful keys; absent otherwise |

| Finish — `TaskResultPayload` | |
| --- | --- |
| `id` | the same id as its start |
| `name` | the same name |
| `error` | the error message **for this task**, or `None` |
| `result` | channel name → what this task wrote |
| `interrupts` | this task's `Interrupt`s, as dicts |

And one thing that is **not** there, in either payload: **a time.** No `ts`,
no `timestamp`, no offset. Every field above is pinned in
`backend/tests/test_the_tasks_stream_mode_is_a_start_event.py`, derived by
running a graph rather than quoted from a page.

## The three things this had to decide

### 1. It does not make ticket 46 unnecessary. It makes 46 the prerequisite.

The survey flagged that `tasks` might carry timing and so reduce 46 to a
smaller job. It does not carry timing. What it changes is *what a stamp would
measure*: today's number is the gap between two arrivals with no idea whose
work filled it; with `tasks` it becomes the gap between one task's own start
and its own finish. That is a categorically better measurement — and it is
still measured by whichever clock stamps the frames, which is exactly the
question 46 owns.

`debug` is the one mode that stamps: it wraps these same payloads with `step`
and a server-side `datetime.now(timezone.utc).isoformat()`. It is not the cheap
route to a clock, because it also carries every checkpoint's **full state
values** on every superstep. Recorded so nobody reaches for it on the strength
of the timestamp alone.

**Recommendation for 46:** mint the stamp in `streaming.py`, uniformly, on all
frame kinds. `token` and `progress` — the two frames that arrive while a node
is still working, and the two that explain a stall — are invisible to `tasks`
entirely, so a clock that comes only from task events is a clock with holes in
exactly the places 47 cares about.

### 2. The id joins to nothing we currently emit, and that must not be papered over

`taskId` on our wire is already three things, all of them domain ids minted by
our own nodes: a planner's subtask id (`task-1`), an async tool-call id, or
`None`. LangGraph's task id is a UUID that never enters graph state. Two
vocabularies for one word is the `loop` / `slug` mistake in a new costume, so
if `tasks` is ever subscribed, its id ships under a **different name** —
`runtimeTaskId` — and never overwrites `taskId`.

There is exactly one bridge, and we already carry it: a subgraph's task events
arrive under `ns == ("<node>:<parent task id>",)`. The namespace string our
frames already have **contains** the parent's runtime task id. That is what
lets an agent's internal `model` step be attributed to the canvas node that
owns it without inventing a correlation.

### 3. Nothing collides

`tasks` composes with `subgraphs=True` and `version="v2"` — `ns` is populated
for nested tasks, the envelope is the same `StreamPart`, and `_stream_part`
already decodes it generically, so the fold's `if mode == ...` chain ignores an
unrequested mode rather than breaking on it. The docs page says `tasks`
*"requires a checkpointer"*; on 1.2.10 the events are emitted from the Pregel
loop's `tick` before any saver is consulted and arrive in full without one.
Pinned, not acted on: every run here has a checkpointer, and depending on an
undocumented behaviour buys nothing.

## What it costs, measured

A scripted three-worker fan-out, on the modes we send today versus those plus
`tasks`: **+2 frames per task and nothing else** — the other three modes emit
byte-identical payloads, so `tasks` is additive the way `custom` was. No
measurable latency (379 ms vs 380 ms on a 380 ms run).

On real runs against `ollama:gpt-oss:120b-cloud`, where token frames dominate:

| package | frames | of which `tasks` | payload bytes | `tasks` share |
| --- | --- | --- | --- | --- |
| `parallel-workers-join` | 678 | 24 | 505 KB | 3.5% of frames, 4.1% of bytes |
| `archetype-orchestrator-report` | 1342 | 32 | 1.05 MB | 2.4% of frames, 6.4% of bytes |

The byte share runs ahead of the frame share because `input` and `result`
carry state — an agent task's `input` is the whole message list. That is the
real cost, and it is also an audience-boundary problem: task events name
`NarrationMiddleware.before_model` and carry unredacted state, so nothing here
reaches a customer channel unfiltered.

## The recommendation

**Subscribe — but not here, and not alone.** Adding `tasks` to the stream is
one line; putting it *on the wire* is a new frame kind, which is a Pydantic
model, a regenerated `docs/openapi.json`, a hand-written mirror in
`src/core/runtime/RuntimeClient.ts` and the drift test that pins them — the
three-file change ticket 46 exists to price once. Shipping it separately means
paying that price twice and arguing the clock question twice.

So the order is: **46 first** (the stamp, on every frame kind), then `tasks`
alongside it, with `runtimeTaskId` distinct from `taskId` and the machinery
names filtered at the audience boundary. Ticket 47 is unaffected: `tasks` says
nothing about token cadence, which is the whole of what 47 is about.
