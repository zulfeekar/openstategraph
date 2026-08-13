---
title: The memory system
description: Long-term Store namespaces, episodic checkpointers, and skills as procedural memory.
type: page
---

# The memory system

Three kinds, each mapped to the LangGraph construct that owns it. Source:
[`backend/openstategraph/memory.py`](../../backend/openstategraph/memory.py).

## Long-term — the `Store`

> **Corrected 2026-08-13.** This section described the memory system as it was
> before the memory-hardening pass, and one of its statements documented a
> cross-user data leak as intended behaviour. Corrections are marked inline.

- One process-wide store, built by `build_store()`. **The backend seam is
  filled**: `OPENSTATEGRAPH_MEMORY_PATH` gives a sqlite-backed store and
  `OPENSTATEGRAPH_POSTGRES_URL` a Postgres one; `InMemoryStore` is the fallback,
  not the only option. Injected once at `compiler.build(..., store=...)`.
- **Three scopes, not one.** `user` → `("memories", <folded identity>)`,
  `workflow` → `("workflow-memory", <slug>)`, `app` → `("app-memory",)`.
  `MemoryScope` is the single declaration of the set.
- **An unidentified run has no user scope at all.** It does **not** get
  `("memories", "anonymous")` — that was a *merge*, one namespace shared by
  every unidentified person on a deployment, while `save_memory` told the model
  it held "facts about this person". `_user_namespace()` now returns `None`, and
  `save_memory` refuses with `NOT SAVED.` rather than writing. Who a run is for
  is decided by the **server** (`openstategraph/principal.py`), never sent by a
  client — `user_email` was removed from `RunRequest`, and sending it is a 422.
- **`thread_id` / `session_id` never appear in a Store namespace.** They scope
  the checkpointer and the run config only. (Still true.)
- `memory_tools()` returns **three** plain LangChain tools — `save_memory`,
  `search_memory` and `forget_memory` — reaching the running graph's store
  through `langgraph.config.get_store()`, so they work bound to any agent in any
  workflow with zero per-workflow code. **The capability flag is no longer just
  the store**: a document's `settings.memory` can disable memory or narrow which
  scopes bind, and the narrowing is applied to the tool *schema* so a scope a
  package does not use is one the model is never offered.
- **Retention:** `OPENSTATEGRAPH_MEMORY_TTL_MINUTES`, `int | None` with unset
  meaning never expire. Durable stores only; `refresh_on_read` is deliberately
  `False`.

## Episodic — checkpointer threads

- **Durable by default** since ticket 05 — one sqlite file under the workflows
  root's state directory, shared by every transport, so a paused
  `human.approval` survives a restart. `OPENSTATEGRAPH_CHECKPOINT_PATH` moves it
  or (`=memory`) opts out, loudly. A document may still claim its **own** file
  with `settings.checkpointer: "sqlite"`, resolved by `checkpointer_for()` into
  `<state dir>/checkpoints-<slug>.sqlite`. **Not `.dev/`** — that was a defect
  (relative to the working directory, so a run from a home directory created
  `~/.dev/`), fixed by ticket 03.
- If sqlite is unavailable it degrades **loudly** in the log to the in-memory
  saver rather than failing the run.
- The same checkpointer is what makes `human.approval` resumable:
  `/api/runs/stream` emits an `interrupt` event carrying the `thread_id`, and
  `/api/runs/resume` continues that exact thread with a `Command`.

## Procedural — skills

`workflows/<slug>/skills/*.md` are read by `discover_skills()`
([`capability_discovery.py`](../../backend/openstategraph/api/capability_discovery.py)),
concatenated as `## Skill: <stem>` sections, and handed to `NodeRuntime` as
`skills_context`. Every agent and worker in that workflow receives it as prompt
*context* — above the developer's rules, below the locked preamble, with
ordering owned by `SystemPrompt`.

This is the simplest honest tier of the skills ladder; full progressive
disclosure (deepagents' three-level `SKILL.md` loading) belongs to the deep
tier and is not implemented here.

A canvas `input.markdown` node wired into an agent's `skill` port is the
per-node counterpart: it compiles to a **binding**, not a graph edge.

## Subagents do not receive state

Graph state flows to *nodes* through the shared schema and reducers. A subagent
is invoked as a tool and gets back a `ToolMessage` — it never sees the parent's
message history or graph state. Never build plumbing that implies otherwise.
