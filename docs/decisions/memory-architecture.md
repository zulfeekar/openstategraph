# The memory architecture — four kinds, one spine

**Status: accepted (owner + assistant sweep, 2026-08-09), amended 2026-08-10 by
ticket 05 — the checkpointer is durable by default and the worker ceiling's
reason has changed (see "Durability"). Companion to
`knowledge-architecture.md`; supersedes nothing.**

## The four kinds

| Kind | Construct | Written by | Survives restart? |
| --- | --- | --- | --- |
| **Context** | checkpointer thread (`thread_id`) — `messages` is the record; turn-scratch (`outputs`/`answer`/`feedback`/`attempts`/`decisions`) is wiped at each turn boundary by the input node's `RESET` update | the graph itself | **yes, by default** (ticket 05); opt out with `OPENSTATEGRAPH_CHECKPOINT_PATH=memory` |
| **Procedural** | `skills/` (always in the prompt, small) + `knowledge/` (on-demand `knowledge_lookup`, chunked) | developers and build-time trainers | yes — files in git |
| **Episodic** | the Store, via `save_memory`/`search_memory`, three scopes: `("memories", user)` / `("workflow-memory", slug)` / `("app-memory",)` | agents at runtime | opt-in: `OPENSTATEGRAPH_MEMORY_PATH` |
| **Knowledge** | the second brain (see `knowledge-architecture.md`) | builders on the button, **never** runtime agents | yes — files in git |

**Knowledge ≠ memory** stays an invariant: promoting a runtime learning into
`knowledge/` is a human act.

## The spine rule

The ROOT workflow (concierge) is the **app spine**: app-wide memory is its
home scope. Every workflow — root or mounted child — holds its OWN stateful
memory: its `("workflow-memory", <its-own-slug>)` namespace, its own
`knowledge/`, its own skills. Config carries identity: `workflow_slug`,
`user_email`, `thread_id`, `session_id` ride in `configurable`, and at every
subgraph/team mount the runtime **overrides `workflow_slug` to the child's
slug** (`node_runtime._subgraph`) while everything else crosses untouched.

## Sharing matrix

| Scope | Read | Write |
| --- | --- | --- |
| user `("memories", email)` | every workflow (search labels `[user]`) | every workflow — the person is one person everywhere |
| workflow `("workflow-memory", slug)` | only that workflow (its own slug via config) | only that workflow — the slug is config-derived, **never a tool argument** |
| app `("app-memory",)` | every workflow (`[app via <slug>]`) | permissive-read, **deliberate-write**: any workflow may deposit, but every deposit is provenance-stamped with the originating slug so the spine stays auditable |

The parent's **thread messages** deliberately cross into mounted children
(ticket 73 — a routed conversational child needs the dialogue), but graph
state does not, and Send-dispatched **workers stay isolated**: they see only
their Send payload (`task_id`, `task_instruction`).

## Durability

- **Checkpointer — durable by default (ticket 05).** `WorkflowServices` owns
  one saver and hands it to HTTP, MCP and `load_workflow` alike; there is no
  second wiring path and no module-level saver anywhere. Resolution order:
  an explicit `checkpointer=` argument, then
  `OPENSTATEGRAPH_CHECKPOINT_PATH` (a file, or the literal `memory` to opt
  out), then the default `<workflows root>/.openstategraph/checkpoints.sqlite`.
  A single document may still claim its own file with
  `settings.checkpointer: "sqlite"` → `.dev/checkpoints-<slug>.sqlite`.
  **Exactly one startup line states which one it got** — `approvals persist at
  X` at INFO, or `approvals are in-memory and will NOT survive a restart` at
  WARNING. The previous behaviour (a process-lifetime `InMemorySaver` in
  `api/main.py`) lost every paused `human.approval` on restart, and the dev
  stack restarts on every file save, so that was a daily loss rather than a
  hosting concern.
- Store: `OPENSTATEGRAPH_MEMORY_PATH=/path/memory.sqlite` → sqlite-backed
  `SqliteStore` (autocommit connection, `check_same_thread=False`); unset →
  `InMemoryStore`. An unusable path degrades loudly to in-memory. Still opt-in,
  and that asymmetry is deliberate: losing a *paused approval* loses a person's
  in-flight decision, while losing accumulated memories degrades quality — only
  the first is a correctness bug.
- **Dependency.** The default is sqlite, so `langgraph-checkpoint-sqlite` moved
  onto the `[server]` extra rather than into the core four (it drags
  `aiosqlite` and the `sqlite-vec` binary wheel, which a `load_workflow`
  consumer who never pauses a run should not pay for). An install missing it
  degrades **loudly**, naming `pip install 'openstategraph[sqlite]'` — never
  silently.

### The worker ceiling is still one, for a smaller reason

Checked against the package rather than assumed. `langgraph-checkpoint-sqlite`
3.1.1's `SqliteSaver` docstring: *"meant for lightweight, synchronous use cases
(demos and small projects) and does not scale to multiple threads"*, and
LangChain's own checkpointer-library page rates it *"ideal for experimentation
and local workflows"* against Postgres's *"ideal for using in production"*.
Its `setup()` does set `PRAGMA journal_mode=WAL`, so multiple *processes* on
one host can read the file — but its only write serialisation is a
`threading.Lock` held **per instance**, which two OS processes do not share.

So the change to the ceiling is a change of *reason*, not of number:

| | Before ticket 05 | After |
| --- | --- | --- |
| Second worker | cannot see the first's threads at all | can read the same file |
| Restart | every paused approval lost | approvals resume |
| Concurrent writes | n/a | uncoordinated across processes — silent |

`uvicorn --workers 1` stays, in `Dockerfile` and `scripts/dev.sh`, and both say
this. Raising it means `PostgresSaver` + `PostgresStore` passed to
`WorkflowServices(checkpointer=…, store=…)`; nothing else changes.

### Thread identity and retention

`thread_id` is supplied by the client (the run endpoint generates a random one
when it is not) and is now a **persistent** identity rather than a
process-lifetime one, in a namespace shared by every workflow under the root.
Two consequences worth stating: a client that reuses a fixed literal
`thread_id` will resume the old conversation rather than start a new one, and
two workflows that both hardcode one would share it. `/chat` avoids both by
deriving the thread from its session.

Retention is **manual**: nothing prunes checkpoints, and the file grows with
use. It is a plain sqlite database with no other content — deleting it (or the
`.openstategraph` directory) discards paused runs and thread history and
nothing else. An automatic reaper is deliberately not built; a TTL that
silently eats a pending approval would be the same class of bug this ticket
just closed.

## Efficiency

`search_memory` caps each scope at 4 hits (≤12 one-liners total).
`_thread_question` bounds history to the last 6 turns and marks the new
message as THE task ("the conversation above is context only, never the
task" — pinned wording; a softer framing let history dominate a mounted team
supervisor). Long threads opt into `SummarizationMiddleware` via the agent's
`summarize` toggle. The ambient `knowledge_lookup` binding scans
`knowledge/` once per runtime construction, not once per agent.

## Antipatterns (each pinned by a test)

- A child writing the parent's (or any other workflow's) workflow-scope —
  impossible: the namespace is config-derived and the mount overrides the slug.
- Runtime agents writing `knowledge/` — builders only, through `write_topic`.
- Workers reading parent state beyond their Send payload.
- Unstamped app-scope writes — every deposit names its workflow.
- Forwarding LangGraph's internal `configurable` keys (`__*`, `checkpoint*`)
  into a mounted child's config.
