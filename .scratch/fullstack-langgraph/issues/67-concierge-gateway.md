Type: task
Status: resolved (2026-08-08) — live-verified

## Question

A predefined, HIDDEN top-level workflow sits above the customer chat: every
chat message enters the concierge, whose router classifies intent and
dispatches to the right child workflow (video games → tabular-analytics,
music/SQL → chinook, live-data → open-api-explorer, general → its own
agent), with protective machinery a workflow can offer (router preamble,
grader, middleware slots). Read-only by construction — the concierge binds
no write-capable tools; children keep their own tools. Not shown in the
Workflows list (`hidden: true` in the envelope, filtered by
`WorkflowStore.list`), but loadable by slug so /chat and the editor can
still open it. Requires: child subgraphs resolve tools from the CHILD's own
package (a `tool_registry_loader` on NodeRuntime), or a routed child answers
from parametric knowledge — the exact silent failure this repo names.

## Resolution

Built as pure composition: `workflows/concierge/` (hidden: true, filtered from list but loadable by slug) — router (4 intents) → `workflow.subgraph` children (tabular, chinook, open-api) + tool-less general agent behind a no-fabrication/no-disclosure grader; code-workshop deliberately NOT routed (write-capable stays explicit-selection). Foundation fix that made it safe: `NodeRuntime.registry_loader` — child subgraphs resolve tools/functions from the CHILD's own package instead of inheriting the parent's (closing the silent tool-loss trap). /chat defaults to 'Auto — let Dyflow route'. Live: videogames → b-videogames with the child's HITL interrupt propagating to the customer page; greeting → b-general with a clean grader-passed answer. Known: HITL children require the stream endpoints (checkpointer); /api/runs stays checkpointer-less by design. 448 pytest green.
