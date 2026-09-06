# Program Design: the OpenStateGraph skill

## Files
- `backend/openstategraph/skills/openstategraph/SKILL.md` — **new**, the entry sheet (frontmatter `name: openstategraph`, `description`), ≤ 250 lines: routing check, the two doors, the interview, sizing, filing, triage, the build loop, the subagent gates, show-me rule, credits by shape.
- `backend/openstategraph/skills/openstategraph/references/{interview.md,build-loop.md,engineering-rules.md,subagents.md,environments.md}` — **new**; `engineering-rules.md` is a generated copy of the package rules file (below), never hand-edited.
- `backend/openstategraph/skills/{atom-forge → ticket sheet per osg-agent-experience/21, kanban-patrol}/SKILL.md` — **moved** from the two flat `*_skill.md` files into the same package-data folder; `BUNDLED_SKILLS` becomes a map of name → directory.
- `backend/openstategraph/bundled_skills.py` — **changed**: installs a directory tree per skill (`SKILL.md` + `references/`), same `created/refreshed/current` report, per file.
- `backend/openstategraph/engineering_rules.md` — **new** package data: the non-negotiables a generated artefact must obey, each section titled exactly as its `CLAUDE.md` counterpart. **Owner's clarification, 2026-09-04:** the rule is *never invent a type the registry does not know* — not *never make a new one*. When nothing registered fits, the sheet routes to the extension path: implement the family's base (`I*` → `Abstract*` → `Base*` → concrete), which is where a new module gets state and context, register it, and only then use it — `docs/building-an-atom.md`'s pipeline, driven by the atom-forge interview. `CLAUDE.md` itself is **not** shipped; this file is the short form the package carries.
- `backend/openstategraph/agent_config.py` — **new**: `ServerDescriptor` and four renderers with merge semantics.
- `backend/openstategraph/scaffold.py` — **changed**: `init` calls the renderers, `InitResult` gains `agent_files: tuple[AgentFileAction, ...]`, the report prints them and the next-sentence line.
- `backend/openstategraph/kanban_store.py` — **changed**: five columns via `ensure_schema`'s per-column add (`kanban-patrol/26` — additive, no migration list), `file_idea_card`, `triage`.
- `backend/openstategraph/mcp_server.py` — **changed**: `get_engineering_rules`, `kanban_file_card`, `kanban_triage`; `EXPOSED_TOOLS` +3.
- `backend/openstategraph/cli.py` — **changed**: `kanban file`, `kanban triage`.
- `backend/openstategraph/api/schemas.py`, `api/routes/kanban.py` — **changed** only so `card_row` carries the five new fields (the board reads them; no new route).
- `src/core/runtime/RuntimeClient.ts`, `src/view/board/kanbanCardMapping.ts`, `PatrolCard.tsx`, `cardInstruction.ts` — **changed**: story/done-when/blocked-by/model/effort rendered on a card and in the pasted instruction; `column_for` unchanged.
- Tests (all new unless noted): `backend/tests/test_bundled_skill_tree.py`, `test_agent_config.py`, `test_scaffold_writes_agent_files.py`, `test_kanban_idea_cards.py`, `test_kanban_triage.py`, `test_mcp_skill_tools.py`, `test_engineering_rules_match_claude_md.py`, `test_documented_skill_surface.py`; `test_documented_mcp_tool_surface.py` and `test_mcp_kanban.py` (changed); `src/view/board/anIdeaCardCarriesItsBrief.test.ts`.
- Docs: `docs/the-openstategraph-skill.md` (new), `docs/mcp.md` §1 + §5a, `docs/cli.md` §init + §kanban, `docs/adding-openstategraph-to-your-project.md` §0.1, `README.md` one paragraph, `CHANGELOG.md`.

## Types & signatures

```python
# agent_config.py
@dataclass(frozen=True)
class ServerDescriptor:
    name: str = "openstategraph"
    command: str = "openstategraph"
    args: tuple[str, ...] = ("mcp",)
    env: Mapping[str, str] = MappingProxyType({"OPENSTATEGRAPH_MCP_ALLOW_RUNS": "0"})
    description: str = "OpenStateGraph — local workflow compiler, validator and board"

class AgentFileState(Enum): CREATED, MERGED, CURRENT, KEPT

@dataclass(frozen=True)
class AgentFileAction:
    agent: str            # "claude-code" | "vscode" | "cursor" | "codex"
    path: Path
    state: AgentFileState
    note: str             # for KEPT: what differed

def render_all(project: Path, server: ServerDescriptor = ServerDescriptor()) -> tuple[AgentFileAction, ...]
def merge_json_servers(existing: dict, key: str, entry: dict, *, servers_key: str) -> tuple[dict, AgentFileState]
def merge_codex_toml(existing_text: str, server: ServerDescriptor) -> tuple[str, AgentFileState]
```

```python
# kanban_store.py
IDEA_PREFIX = "idea-"
def idea_task_id(project_id: str, title: str) -> str          # f"{project_id}:idea-{slug}"
def file_idea_card(db_path, *, project_id, kind, title, story, done_when, priority, priority_reason,
                   area="backend", blocked_by=(), agent_model="", agent_effort="") -> str   # task_id
    # refuses: kind not in {task,bug,grilling}; empty story/done_when/priority_reason; duplicate task_id
@dataclass(frozen=True)
class TriageRow: card: Card; rank: int; why_here: str
def triage(cards: Sequence[Card]) -> tuple[TriageRow, ...]
    # order: unblocked cards that block others (by count) → unblocked by priority → blocked last; why_here names the rule
```

```python
# mcp_server.py
def get_engineering_rules() -> dict          # {"version": <package version>, "rules": <markdown>}
def kanban_file_card(kind, title, story, done_when, priority, priority_reason, area="backend",
                     blocked_by: list[str] | None = None, agent_model="", agent_effort="",
                     ctx: Context = None) -> dict   # {"ok", "task_id", "column"} | {"ok": False, "reason"}
def kanban_triage(board: str = "workflows") -> dict  # {"ok", "cards": [card_row + rank + why_here]}
```

```python
# scaffold.py
class InitResult: ...; agent_files: tuple[AgentFileAction, ...]
NEXT_SENTENCE = 'next: open your coding agent here and say "use OpenStateGraph" and describe the workflow you want.'
```

```ts
// board
interface BoardCard { ...; readonly story?: string; readonly doneWhen?: string; readonly blockedBy?: readonly string[]; readonly agentModel?: string; readonly agentEffort?: string }
```

## Call stack
**Install:** `cmd_init` → `init_project` → `install_bundled_skills` (walks each skill dir, both roots) → `agent_config.render_all` → report.

**File a card (MCP):** agent → `kanban_file_card` → `_actor_on_the_card` → `kanban_store.file_idea_card` → `ensure_schema` (adds the five columns to an older store) → `INSERT` → `column_for` → reply.

**Triage:** `kanban_triage` → `list_cards` → `triage` → rows with `why_here`.

**Rules:** `get_engineering_rules` → `importlib.resources` read of `engineering_rules.md` → text + version.

**Build loop (from the sheet):** attend → red → `set_stage red` → green → `set_stage green` → commit → `set_stage finished`; unchanged machinery.

## Test plan
- `test_agent_config.py`: each renderer creates its file when absent (4); merges into an existing file preserving foreign keys (4); `CURRENT` when ours is identical; `KEPT` with a note when `openstategraph` differs (`ALLOW_RUNS=1`); Codex TOML round-trips a comment. Red first: no module.
- `test_scaffold_writes_agent_files.py`: `init` on an empty dir writes the four; on a dir with a `.vscode/mcp.json` holding another server, merges; the report names each path and state and ends with `NEXT_SENTENCE`.
- `test_bundled_skill_tree.py`: three skills installed into both roots with `references/`; `engineering-rules.md` inside equals the package rules file byte-for-byte; the sheet parses (`SkillDocument.parse`) with name and description.
- `test_engineering_rules_match_claude_md.py`: every `##` heading in the rules file names a section heading in `CLAUDE.md`'s non-negotiables (case-insensitive substring), and the rules file names the ladder, registries, TDD, port cardinality, "never invent a node type".
- `test_kanban_idea_cards.py`: id shape; refusals; a store created before the columns gains them on first write; `column_for` places an idea `task` in Detected and `grilling` in Needs You.
- `test_kanban_triage.py`: blocker-with-most-dependents first; ties by priority; blocked cards last; `why_here` non-empty and names the rule; pure, no store.
- `test_mcp_skill_tools.py`: the three tools registered in `EXPOSED_TOOLS`; `kanban_file_card` writes the actor through the principal (ticket 29 shape); a refusal is `{"ok": False, "reason"}`, never a stack trace.
- `test_documented_skill_surface.py`: every MCP tool and CLI verb the sheet names exists (both directions), like `test_documented_mcp_tool_surface.py`.
- `anIdeaCardCarriesItsBrief.test.ts`: story/done-when rendered; the pasted instruction carries done-when and the model/effort line; a patrol card (nulls) renders as before.
- **Tested as a user** (ticket 25's done-when): fresh temp dir, wheel from the checkout, a real coding agent given the sentence and a concept; transcript pasted into ticket 25.

## Least confident decisions
1. **Slug ids for idea cards** (`project_id:idea-<slug>`) collide on two ideas with one title; refused as duplicate rather than suffixed, so the agent has to name things distinctly. Cheap to change to a suffix if it bites.
2. **Triage as a pure ordering, no stored rank.** Recomputed on every call; nothing to drift, nothing to persist. Costs O(n log n) per call on a board of tens.
3. **The rules file is a curated copy, pinned to `CLAUDE.md` by headings only**, not by body text. Bodies are meant to differ (the package version is shorter). If bodies drift in meaning nothing catches it except review.
4. **The sheet instructs subagent spawning; it cannot spawn.** Agents that have no subagent facility follow the same loop inline. The sheet says so.
5. **Codex TOML merge is text-level** (append a table if absent) rather than a full TOML rewrite, to keep comments; a malformed existing file is `KEPT` with the note.
