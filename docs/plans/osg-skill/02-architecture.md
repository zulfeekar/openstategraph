# Architecture: the OpenStateGraph skill

## Fit
- **`backend/openstategraph/bundled_skills.py`** — installs single
  `SKILL.md` files into both skill roots today. Grows to install a skill
  *directory* (`SKILL.md` + `references/*.md`), same three-state report.
  The new skill ships as package data `backend/openstategraph/skills/
  openstategraph/` beside the two existing sheets, which move into the same
  package-data folder in the same commit (one home, one installer).
- **`backend/openstategraph/agent_config.py`** (new) — `ServerDescriptor`
  (name, command, args, env, description) is the one source, and four
  renderers write the per-agent files from it: root `.mcp.json` (Claude
  Code, `mcpServers`), `.vscode/mcp.json` (Copilot, key `servers`),
  `.cursor/mcp.json` (Cursor), `.codex/config.toml` (Codex). Each renderer
  **merges**: parse, insert our one entry, write back preserving everything
  else; refuse and report `kept` only when an `openstategraph` entry exists
  with different settings. Report states per file: `created` / `merged` /
  `current` / `kept`. (Decided by the owner on 2026-09-04 after the
  agent-plugins research, ticket 27; the earlier root-only never-rewrite
  draft reached one agent of four.)
- **`backend/openstategraph/scaffold.py`** — `init` calls the four
  renderers and prints their four lines plus the one sentence to type next.
- **Agent Plugin** — shipped later from the same descriptor through
  `plugin_interop` (ticket 28); distribution, not bootstrap.
- **`backend/openstategraph/mcp_server.py`** — three new tools join
  `EXPOSED_TOOLS` (the trust boundary; the census test grows with them):
  `get_engineering_rules`, `kanban_file_card`, `kanban_triage`. Actor on
  the two writers comes through `_actor_on_the_card` (ticket 29).
- **`backend/openstategraph/kanban_store.py`** — a card that has no run
  behind it: `task_id = f"{project_id}:idea-{slug}"` minted by
  `file_idea_card`; new columns `story`, `done_when`, `blocked_by`,
  `agent_model`, `agent_effort` added through the store's own migration
  path (`kanban-patrol/26`: `ensure_schema` cannot add a column to an
  existing store, the migration function can). `triage(cards)` is a pure
  ordering: unblocked-and-blocking first, then priority, reason carried.
- **`backend/openstategraph/cli.py`** — `kanban file` and `kanban triage`,
  thin over the store, so the sheet's CLI door has the same verbs as MCP.
- **`backend/openstategraph/engineering_rules.md`** — package data served
  by `get_engineering_rules`: the non-negotiables a generated tool, node or
  workflow must obey (the ladder, registries, port cardinality, one field
  schema, TDD, no invented types). This repository's `CLAUDE.md` stays the
  long form; a test pins that every heading in the rules file names a
  section of `CLAUDE.md`, so the two cannot drift silently.
- **`docs/`** — `docs/the-openstategraph-skill.md` (new), `docs/mcp.md` §1
  (the hand-pasted block becomes "written by init"), `docs/cli.md` §kanban.

## Endpoints
None new over HTTP. MCP tools (stdio, local):
- `get_engineering_rules()` → the rules text, versioned with the package.
- `kanban_file_card(kind, title, story, done_when, priority, priority_reason, area?, blocked_by?, agent_model?, agent_effort?)` → `{task_id, column}`; refuses an empty story or done-when; kind ∈ task/bug/grilling.
- `kanban_triage(board?)` → ordered cards with `why_here` per row.

## Data
`kanban.sqlite` `cards` gains five nullable columns (above). Patrol cards
leave them null. `task_id` for an idea card is `project_id:idea-<slug>`,
slug from the title, unique per project by the existing PK. No second
store; no markdown tickets in a developer's project.

The descriptor, rendered four ways (Claude Code shown):
```json
{"mcpServers": {"openstategraph": {"command": "openstategraph", "args": ["mcp"],
  "env": {"OPENSTATEGRAPH_MCP_ALLOW_RUNS": "0"}}}}
```
`command` is the console script from the tool env, so no `PYTHONPATH`.
VS Code's file uses `servers`; Codex's is TOML `[mcp_servers.openstategraph]`.

## Flow
**Install:** `uv tool install …[server,ollama]` (server now implies mcp,
osg-agent-experience/19) → `openstategraph init .` → writes config,
`AGENTS.md`, the four agent files, three skills into both roots → report ends
*"next: tell your coding agent: use OpenStateGraph and describe your
workflow"*.

**Use, MCP door:** agent reads `SKILL.md` → calls `get_engineering_rules`
and `get_node_vocabulary` → interviews (one question per turn, the sheet's
dimensions) → `kanban_file_card` per decision or task → `kanban_triage` →
for each card: `kanban_attend_card` → red test → `kanban_set_stage red` →
green → `kanban_set_stage green` → commit → `kanban_set_stage finished`;
subagent spawn only when the card passes the four gates, with the card's
model and effort; `compile_workflow`/`validate_workflow` before any
`save_workflow_draft`; `run_workflow` only when the developer enabled runs.

**Use, CLI door:** same steps through `openstategraph kanban file|triage|
attend|stage`, `openstategraph validate|compile`, reading the rules from
the sheet's `references/engineering-rules.md` (a generated copy of the
package file, regenerated by the install, never hand-edited).

**Routing:** the sheet's first check: is the ask about the developer's
project or about the platform? Platform → say so and stop unless the
current directory is an OpenStateGraph checkout.

## External
None. Environment names only: `OPENSTATEGRAPH_MCP_ALLOW_RUNS`.
