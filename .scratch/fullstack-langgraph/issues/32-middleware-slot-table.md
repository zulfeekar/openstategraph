Type: grilling
Status: mostly resolved (2026-08-07) — no UI yet
Blocked by: 30

## Question

The reverted WIP branch (`wip/middleware-tabular-experiment`) implemented
middleware as monkey-patched `model.invoke` wrappers — a parallel runtime.
Confirmed against docs-langchain: middleware is `create_agent(middleware=[…])`
and `wrap_model_call(request, handler)` is a hook the agent runtime calls,
not a model decorator. The WIP version also stacked wrappers on the shared
cached model (N agents → N layers, inherited silently by workers), wrote
telemetry into a discarded `{}`, and hardcoded the stack for every agent.

Design the real thing, per CLAUDE.md's slot-table rule:

- `resolve_middleware()` returns an ordered, name-keyed slot table; the base
  owns the canonical slot order; a subclass/plugin contributes by *naming* a
  slot; replacement is by slot name; the compiler flattens last and passes
  `create_agent(middleware=[...])`.
- No ordering integer anywhere: `before_*` runs forward, `after_*` reversed,
  `wrap_*` nests — one number cannot express that.
- Which middlewares ship? LangChain's own prebuilts (summarization, model
  call limit, PII…) vs custom (logging, token counting). Token accounting
  must land somewhere readable (RunState or the run response), not a
  throwaway dict.
- Retry/timeout/caching stay on `add_node`/`set_node_defaults` — the WIP
  RetryMiddleware duplicated an existing, correct mechanism. Do not port it.
- UI: how does a developer enable/replace a slot per node? (Blocked on the
  Inspector grouping work, ticket 38.)

## Resolution

`MiddlewareSlotTable` (name-keyed, canonical order, no priority integers) flattens into `create_agent(middleware=[...])` — the library's real seam; presets per tier via `middleware_preset()`. Still open: which prebuilt middlewares ship in default slots, and the per-node UI.
