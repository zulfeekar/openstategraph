# Changelog

## 0.1.0 — 2026-08-08

First coherent release: a visual workflow builder that compiles to LangGraph.

- **Editor**: JointJS-core canvas (registry-driven palette, undo/redo,
  snaplines, minimap, auto-arrange in both flow directions), schema-driven
  inspector with locked prompt sections, compiled-graph Mermaid overlay,
  execution trace tree with JSON export.
- **Runtime**: `workflow.json` → LangGraph `StateGraph` compiler (routers,
  graders with rubric rows, supervisor fan-out with worker archetypes, HITL
  approval, subgraph + Team nodes, per-node retry/timeout), agent tiers
  (ReAct / deep / custom) over a middleware slot table.
- **Memory**: long-term Store namespaced per user with prebuilt save/search
  tools, durable sqlite checkpointing opt-in, procedural skills per package.
- **Customer surface**: `/chat` with workflow selector, an Auto concierge
  gateway (read-only platform introspection + keyless web search), and a
  Workflow Architect that composes compile-validated workflows from a
  description — saving stays a human click.
- **Workflows shipped**: Chinook NL-to-SQL, video-game analytics, open-API
  explorer, code workshop (+review), research team, data-analyst team.
- **Quality**: 505 pytest + 339 Vitest, strict tsc, ruff + ESLint + Prettier,
  CI, supervised dev stack (`scripts/dev.sh`).
