# Changelog

## 0.2.0 — 2026-08-09

The first release under the project's own name, plus the work that made the
conversational surface actually usable across workflow boundaries.

### Changed — breaking

- **Renamed Dyflow → OpenStateGraph.** The Python package is now
  `openstategraph` (import paths, `uvicorn openstategraph.api.main:app`), and
  the backend environment variables are `OPENSTATEGRAPH_OLLAMA_MODEL` and
  `OPENSTATEGRAPH_LOG_LEVEL`. Any existing
  `.env` or shell profile carrying the old names must be updated — the old
  spellings are not read as fallbacks. `workflow.json` is unaffected: the
  serialized format did not change.

### Added

- **Memory.** Conversation memory generalised beyond a single workflow, plus
  three-scope long-term memory (user / workflow / thread) over the LangGraph
  Store, with prebuilt save and search tools.
- **The conversation crosses the subgraph boundary.** A routed child subgraph
  now receives the parent thread's dialogue instead of starting amnesiac, and a
  `PackageAssets` loader gives a child its *full* package rather than a bare
  `workflow.json`.
- **Live flow view in `/chat`.** The compiled graph renders beside the
  conversation with active nodes lit during a run; the layout is a fixed
  420px chat column that stacks under 900px.
- **OpenWiki.** 13 generated concept pages as a single source of truth the
  concierge can read, refreshed by a weekly PR-on-change workflow.
- **Playwright smoke suite** driving real gestures against the canvas, wired
  into CI alongside the unit suites.

### Improved

- **Concierge and Workflow Architect** routing sharpened: build requests and
  how-does-it-work questions no longer collide, and tool-call chatter is never
  presented as the answer.
- **`api/main.py` split** (973 → 570 lines) into `schemas`, `model_resolution`,
  `registries` and `streaming`; runtime collaborators are passed as a
  `RuntimeServices` parameter object rather than threaded individually.
- **Coverage ratchets in CI.** Frontend statements 58% → 73.5% (367 tests);
  backend measured at 91%. Both floors are enforced, so a PR cannot lower them
  to go green.
- Palette level labels, and `scripts/dev.sh stop` now escalates past a
  graceful-shutdown hang instead of waiting forever.

### Removed

- `.scratch/` and `HANDOVER.md` are no longer tracked — internal planning stays
  local and out of the published repository.

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
