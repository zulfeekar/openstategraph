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

### The worker ceiling is one, and since ticket 06 it is enforced

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

**Scale-and-adopt ticket 06 stopped writing this down and started enforcing
it.** A limit that lives only in a comment is a limit somebody's deploy script
does not read: `openstategraph.deployment` refuses `--workers N`,
`WEB_CONCURRENCY`, `UVICORN_WORKERS` and `GUNICORN_WORKERS` before a socket is
bound, and takes an exclusive OS lock on `<state dir>/serve.lock` to catch
`uvicorn --workers 4` and `gunicorn -w 4`, which leave no environment trace at
all. `uvicorn --workers 1` stays in `Dockerfile` and `scripts/dev.sh`; it is now
the *only* thing that starts.

`PostgresSaver` + `PostgresStore` shipped in the same ticket
(`openstategraph/postgres.py`, the `[postgres]` extra,
`OPENSTATEGRAPH_POSTGRES_URL`) — dropped into these same two seams, which
`WorkflowServices` already took by argument. Read what that does and does not
mean carefully, because the obvious reading is wrong: **it does not raise the
ceiling, and the refusal does not soften when it is set.** It moves durable
state into a database an operations team backs up, which is worth having on one
worker. The second cause of the ceiling is directly below, and until it is
answered too, Postgres alone would be a scale-out story that fails silently —
which is precisely the trade this section exists to refuse.

### Live catalogue events ride the same ceiling

`GET /api/events` streams `workflows.changed` so an open `/chat` picker or
Workflows panel sees a publish without a reload
(`openstategraph/api/catalogue_events.py`). Its fan-out is **in-process**: a
publish reaches subscribers of *this* Python process and no other. That is not
a new constraint — it is the same one worker this section already justifies —
but it does mean raising the ceiling is now a **two-part** change, and skipping
the second part fails silently rather than loudly:

| | Second worker today | What it needs |
| --- | --- | --- |
| Checkpoints | uncoordinated sqlite writes | `PostgresSaver` / `PostgresStore` — **shipped** (ticket 06) |
| Catalogue events | a publish on worker A never reaches a surface on worker B | Redis pub/sub or Postgres `LISTEN`/`NOTIFY` behind the same `publish`/`subscribe` pair — **not shipped** (gap register RC-17) |

The endpoint and both clients are unchanged by that swap — `CatalogueBroadcaster`
is the whole seam. One half shipped and one did not, and that asymmetry is why
ticket 06's answer to "support multi-worker or refuse it" was **refuse**: a
deployment that fixed the checkpointer and kept the in-process fan-out would
look correct and drop catalogue updates, which is a worse failure than the one
it fixed. Both halves or neither.

Two further honest limits, stated so nobody has to discover them:

- **Only writes through the API emit.** Save, publish/unpublish and delete each
  emit exactly once; a read emits nothing. A `workflow.json` edited by hand on
  disk, or arriving via `git pull`, emits nothing at all — the editor writes
  through the API, a text editor does not. A filesystem watch (`watchfiles`)
  would close that gap and is **future work**, not something to assume works.
  (Separately, the editor polls `savedAt` every 5s for the one *document* it has
  open — `src/app/workflowFileWatch.ts` — which is a different question from the
  catalogue.)
- **No replay.** A surface receives what happens while it is connected;
  `EventSource` reconnects on its own and both clients refetch on open, which is
  the only correct recovery anyway — the catalogue is the truth, the event is a
  hint to go and look.

### Thread identity and retention

`thread_id` is supplied by the client (the run endpoint generates a random one
when it is not) and is now a **persistent** identity rather than a
process-lifetime one, in a namespace shared by every workflow under the root.
Two consequences worth stating: a client that reuses a fixed literal
`thread_id` will resume the old conversation rather than start a new one, and
two workflows that both hardcode one would share it. `/chat` avoids both by
deriving the thread from its session.

Retention is **manual**, and this is a statement about **checkpoints only**.
Nothing prunes them, and the file grows with use. It is a plain sqlite database
with no other content — deleting it (or the `.openstategraph` directory)
discards paused runs and thread history and nothing else. An automatic reaper
is deliberately not built; a TTL that silently eats a pending approval would be
the same class of bug this ticket just closed.

**The Store's retention story is the opposite, and the difference is not an
inconsistency** (memory-hardening ticket 04). A checkpoint may be a person
waiting on an approval, so expiring one destroys work in progress. A long-term
memory is a durable *claim* — "the user prefers concise answers" — and a wrong
or stale one is not merely dead weight: `search_memory` shows four results per
scope, so stale facts actively crowd correct ones out of the window. Expiring
them is a feature; expiring a checkpoint is data loss.

So long-term memory has both a manual and an automatic answer, and the
checkpointer has neither:

| | Manual | Automatic |
| --- | --- | --- |
| Long-term memory (Store) | `forget_memory(handle)`, bound to every agent | `OPENSTATEGRAPH_MEMORY_TTL_MINUTES`, durable stores only |
| Checkpoints | delete the file | **deliberately none**, for the reason above |

Retention is `int | None` minutes with unset meaning "never expire", and
`refresh_on_read` is **False** — against LangGraph's own default — because a
fact an agent merely looked at would otherwise live another full term, making
a stale fact immortal precisely because it keeps surfacing in search.

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
