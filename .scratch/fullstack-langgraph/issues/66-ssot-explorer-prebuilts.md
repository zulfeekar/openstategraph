Type: grilling
Status: resolved v1 (2026-08-08) — three of four prebuilts built
Blocked by: 65

## Question

User scenario: a database of 6+ tables, 10+ columns each, each table with
its own business meaning and JOIN rules; the user wants SKILLS as procedural
memory so the agent explores and reaches the SSOT (a table, or a wiki like
the LangGraph docs). What reusable prebuilt nodes fall out? Candidates to
design: a **Schema Explorer** tool family (generalize chinook's
list/schema/FK tools to any SQL source), a **Skill Library** node (procedural
memory: business + JOIN rules as retrievable skill files, deepagents-style
3-level disclosure), a **Glossary/SSOT** node (wiki or table-backed
definitions with citation), and a prebuilt **Data Analyst Team** composing
them (Team node, ticket 56). Decide after ticket 65 lands the memory
mapping.

## Additions (user, 2026-08-08)

- **Context summarization when bloating**: use LangGraph/LangChain's own
  prebuilts, never hand-rolled — `SummarizationMiddleware` for agents (the
  research confirmed deepagents already carries it in its stack; the slot
  table must expose it for ReAct-tier agents too), `langmem`'s
  `SummarizationNode` only for the narrow node-level case the docs document.
  A long SSOT exploration (6 tables × schemas × rules) is exactly the
  context-bloat case.
- **Rubric grader**: today the Grader takes freeform criteria bullets
  (extend/replace on the locked prompt) — not a structured rubric. Add
  `rubric` mode: rows of {criterion, required} rendered as a scored
  checklist the model must answer per-row; any failed required row =
  revise, with the failing rows as the feedback. Same SystemPrompt
  composition, richer contract.

## Resolution

Built (one-liners):
- **Schema Explorer**: `backend/dyflow/prebuilt_sql.py` — `tool.sql-list-tables` / `tool.sql-get-schema` (FKs rendered as "JOIN rules") / `tool.sql-query`, jailed to workflows/, driver-enforced read-only, per-node `database` + `maxRows` config; in the default registry, so any workflow's N-table sqlite is configuration. 7 tests.
- **Skill Library v1 (procedural)**: `discover_skills` — `workflows/<slug>/skills/*.md` concatenated as prompt context for every agent and worker in that workflow (above rules, below the locked preamble); deepagents-style 3-level disclosure stays the deep-tier follow-up. Verified: join-rules skill discovered for tabular-analytics.
- **Rubric grader** (user addition): `Grader(rubric=[{criterion, required}])` renders a numbered REQUIRED/advisory checklist as machinery context (survives `replace_defaults`; contract still last); TS repeatable-group editor on the Grader card. 4 tests.
- **Context summarization** (user addition): `summarize` toggle on agent.llm → LangChain's own `SummarizationMiddleware` in the slot table — prebuilt, never hand-rolled.

Deferred, recorded: the Glossary/SSOT wiki node (needs a source decision — table vs docs corpus) and the prebuilt Data Analyst Team package composing all of it (a `new_team.py` variant once the glossary exists).

## Correction + build (2026-08-08, user-prompted, docs-verified)

My earlier claim "no prebuilt rubric middleware exists" was **wrong** — the
user pointed at `deepagents.RubricMiddleware` (>=0.6.5, beta) and the docs
MCP confirmed it: an LLM-as-judge grader *sub-agent* inside the agent,
rubric text passed on invocation state, iterating to `max_iterations`.
Wired: `rubric` textarea on agent.llm → RubricMiddleware slot (judge = the
agent's own model, 3 iterations) + rubric on the invoke payload; deepagents
upgraded 0.3.1 → 0.7.5 (un-skipped 7 tests). Live-verified: haiku rubric,
two visible judge iterations in the trace, compliant result. Distinction
kept: RubricMiddleware = agent-internal atom; Grader node (with its own
structured rubric rows) = graph-level organism. Both exist for different
altitudes of the Lego model.

## Follow-up built (2026-08-08)

`data-analyst-team` shipped: Team package whose SQL Analyst member carries the three generic SQL explorer tools against Chinook + a `skills/sql-conventions.md` procedural skill; live-verified through a Team node (correct $523.06 USA revenue figure, table named, grader loop fired). Glossary node remains the one open piece — blocked on the user's source choice (table vs docs corpus).
