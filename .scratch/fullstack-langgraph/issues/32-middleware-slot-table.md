Type: grilling
Status: mostly resolved (2026-08-07) — extension model now decided; prebuilt selection + discovery still to build
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

## User decision (2026-08-07, during ticket 37)

**Prebuilt-by-default, file-extended.** Every agent-tier node ships a
working default middleware stack drawn from LangChain's own prebuilts —
prompt-injection guard, PII redaction, and whatever else earns a default
slot — overridable or extendable the same way tools and functions already
are: a developer adds `workflows/<slug>/middlewares/<name>.py` and discovery
registers it into the slot table by name (local fills-or-replaces a slot;
the base keeps the canonical order). Middlewares are expected to *rarely*
need custom code — the prebuilts cover most needs — which is exactly why
the default stack must be good.

Left to build: pick the concrete default slots per tier (deep agents also
carry their own built-ins: sandbox/filesystem read/write/grep via
deepagents), `discover_middlewares` mirroring `discover_function_callables`,
and the per-node UI for enabling/replacing slots.
