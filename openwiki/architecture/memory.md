---
title: The memory system
description: Long-term Store namespaces, episodic checkpointers, and skills as procedural memory.
type: page
---

# The memory system

Three kinds, each mapped to the LangGraph construct that owns it. Source:
[`backend/openstategraph/memory.py`](../../backend/openstategraph/memory.py).

## Long-term — the `Store`

- One process-wide store, built by `build_store()` (an `InMemoryStore`; the
  seam a `PostgresStore` drops into) and injected once at
  `compiler.build(..., store=memory_store)`.
- Namespace: `("memories", <user_email>)`. Emails are lowercased and their
  periods substituted, because Store namespace labels forbid `.`. An
  unidentified user gets `("memories", "anonymous")` rather than an error.
- **`thread_id` / `session_id` never appear in a Store namespace.** They scope
  the checkpointer and the run config only.
- `memory_tools()` returns two plain LangChain tools — `save_memory` and
  `search_memory` — which reach the running graph's store through
  `langgraph.config.get_store()`. They therefore work bound to any agent in any
  workflow with zero per-workflow code. `NodeRuntime.store` being set is the
  capability flag that turns them on.

## Episodic — checkpointer threads

- In-memory by default; a document opts into durability with
  `settings.checkpointer: "sqlite"`, resolved by `checkpointer_for()` into a
  `SqliteSaver` at `.dev/checkpoints-<slug>.sqlite`.
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
