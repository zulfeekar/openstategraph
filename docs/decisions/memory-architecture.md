# The memory architecture — four kinds, one spine

**Status: accepted (owner + assistant sweep, 2026-08-09). Companion to
`knowledge-architecture.md`; supersedes nothing.**

## The four kinds

| Kind | Construct | Written by | Survives restart? |
| --- | --- | --- | --- |
| **Context [RAM]** | checkpointer thread (`thread_id`) — `messages` is the record; turn-scratch (`outputs`/`answer`/`feedback`/`attempts`/`decisions`) is wiped at each turn boundary by the input node's `RESET` update | the graph itself | opt-in: `settings.checkpointer: "sqlite"` |
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

- Store: `OPENSTATEGRAPH_MEMORY_PATH=/path/memory.sqlite` → sqlite-backed
  `SqliteStore` (autocommit connection, `check_same_thread=False`); unset →
  `InMemoryStore`. An unusable path degrades loudly to in-memory.
- Checkpointer: per-workflow `settings.checkpointer: "sqlite"` →
  `.dev/checkpoints-<slug>.sqlite`.
- Both share the **single-worker constraint**: one uvicorn worker, one
  shared connection. Multi-process hosting means PostgresStore/PostgresSaver
  dropped into the same seams — nothing else changes.

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
