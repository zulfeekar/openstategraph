Type: grilling
Status: open
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
