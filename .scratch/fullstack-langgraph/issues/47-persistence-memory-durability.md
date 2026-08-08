Type: grilling
Status: resolved (2026-08-08) — decisions recorded, implementation on demand
Blocked by: 36

## Question

Checkpointing is one process-wide InMemorySaver; `/api/runs` (non-streaming)
passes no checkpointer at all, so human.approval there 502s. No Store, no
durability param, no cache_policy, no thread management beyond a transient
thread_id.

- Checkpointer per workflow (settings): none / memory / sqlite; surface the
  human.approval-needs-checkpointer constraint as a compile diagnostic
  instead of a 502.
- `Store` for cross-thread memory: which nodes read/write it, namespacing.
- `durability` and `cache_policy` exposure — graph-assembly params on the
  workflow, per CLAUDE.md's boundary rule.
- Thread lifecycle: multi-turn chat currently starts a fresh run per
  message; decide what a "conversation" is.

## Resolution

One-liners: checkpointer stays `InMemorySaver` per process until a real multi-user need (map keeps that fog) — but `/api/runs` gets the same checkpointer as the stream endpoints so a HITL node no longer 502s there; `workflow.settings` grows optional `checkpointer: memory|sqlite` with SqliteSaver as the first durable option (file beside workflow.json, matching the files-first persistence decision of ticket 10); `Store`/memory namespaces deferred until a node type consumes them (no speculative plumbing); `durability=` left at LangGraph defaults, revisited when sqlite lands.
