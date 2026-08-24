# NL2SQL: deterministic validate/execute nodes replace agent-loop tool calls

`launch-readiness/12`. Package: `/tmp/nl2sql/workflows/cpl-nl2sql/` (external
to this repo; this doc is the record OSG asked to be kept here).

## What changed

Graph before: `in1 → prefetch1 → agent1 → summarize1 → out1`, with
`sql_validator` and `DatabricksSqlQueryTool` bound as **tools** inside
`agent1`'s ReAct loop — every call costs a decide-turn and a read-turn.

Graph after:

```
in1 → prefetch1 → agent1(SQL only) → validate1 → execute1 → summarize1 → out1
        no model        1 model turn   no model    no model    1 model turn
```

- `agent1`'s `tools` bus now carries only the explore/search fallbacks
  (`t-describe`, `t-distinct`, `t-list`, `t-search`); `sql_validator` and
  `DatabricksSqlQueryTool` were removed. Its system prompt was rewritten:
  compose SQL, stop — no execution, no validator call, exactly one ```sql
  fence in the output.
- `validate1` (`functions/validate_sql.py`) and `execute1`
  (`functions/execute_sql.py`) are new `function.*` nodes — plain Python, no
  model, discovered the same way `functions/prefetch_context.py` already was.
  `validate1` reuses the checks `tools/sql_validator.py`'s `SqlValidatorTool`
  already implemented (table/column existence against Unity Catalog, facet
  rules); `execute1` reuses `tools/databricks_nl2sql.py`'s guarded
  SELECT-only / `ms_cpl_app_prod.*`-only execution path.
- The orphaned `t-query` / `t-validate` tool nodes were deleted from
  `workflow.json` rather than left connected to nothing.

## Failure-path decision: fail loud, not a revision edge

Both failure modes (`validate1` rejects, `execute1` errors) **fail loudly and
pass the failure text downstream unchanged** rather than routing back to
`agent1` for a revision. `summarize1`'s prompt was given an explicit rule:
a draft starting `VALIDATION FAILED` or `EXECUTION FAILED` must be relayed
plainly, never turned into invented numbers.

Why not a real revise loop: CLAUDE.md's cycle rule requires a *typed
feedback port* — `GraderNode.revise: feedback → AgentNode.feedback` — which
is core/port-registry surface. Building an equivalent for `validate1`/
`execute1` would mean either (a) touching the installed `openstategraph`
package to add a new typed port, explicitly out of bounds for this task, or
(b) faking control flow through a string convention on plain `function.*`
nodes (`fn(text) -> str`, no branching), which is the "read a model's answer
tolerantly" trap run in reverse — smuggling control flow through string
prefixes instead of a real edge. A hard, visible failure was the honest
option available at this layer with the tools in scope.

## Two real defects found while wiring this, both fixed

1. **`sql_validator`'s time-window check only recognised `col = 'literal'`
   or `col LIKE 'literal'` as a date predicate.** A real date filter is
   almost always `>=`/`<=`/`BETWEEN` against an expression
   (`cast(IDLE_START AS DATE) >= date_sub(current_date(), 14)`), which was
   silently invisible to the check — a correct, date-windowed query was
   rejected as if it had no date predicate at all. Fixed in both
   `functions/validate_sql.py` and (for consistency, though no longer wired
   into the agent's tool bus) `tools/sql_validator.py`: a broadened scan
   checks every date-typed column already known from Unity Catalog against
   the SQL text for a comparison operator or `CAST(...)`/`date_trunc(...)`
   wrapping, no extra warehouse call needed.

2. **`DatabricksSqlQueryTool`'s (and now `execute1`'s) warehouse call did
   not check `resp.status.state`.** The Databricks SDK does not raise on a
   server-side statement failure — `execute_statement` returns normally with
   `status.state == FAILED` and `result`/`manifest` both `None`. The
   un-checked code rendered that as zero columns, zero rows: "0 rows
   returned" became indistinguishable from "the warehouse never answered",
   which is exactly the silent failure `errors.py` forbids. Caught live: a
   first run of question A produced "no VLCC idle events found" — a
   plausible-sounding wrong answer — because the SQL referenced a `LATITUDE`
   column that does not exist on `idle_events_v1r2` (see next item), and the
   failure was swallowed. Fixed in `functions/execute_sql.py` by checking
   `status.state` and raising with the warehouse's own error message when it
   is not `SUCCEEDED`.

3. **`skills/entity-dictionary.md`'s Fujairah entry named `LATITUDE`/
   `LONGITUDE`** for `idle_events_v1r2`; the table has no such columns — only
   `START_LATITUDE`/`START_LONGITUDE`/`END_LATITUDE`/`END_LONGITUDE`
   (confirmed via `w.tables.get(...)`). A false schema claim in a skill file,
   not a prompting problem — same shape as the CPL ground-truth note this
   repo already carries. Corrected to name the real columns and to say so
   was a correction, dated.

## Measured

Both questions run against the live warehouse (`Serverless Starter
Warehouse`, profile `adb-7405605452558986`), model `openai/gpt-5-mini`,
`reasoningEffort=low` on both `agent1` and `summarize1`.

- **A** (Fujairah VLCC dwell, 14-day daily breakdown): **30.5s** wall-clock
  (was 110s). Range 14.32–23.90h across the 12 days returned, mean ≈18.4h —
  matches the prior Genie-parity figures.
- **B** (Indian ports exporting diesel/gasoil to East Africa): **60.5s**
  wall-clock (was 59s — essentially unchanged; B's cost was already mostly
  in `agent1`'s single SQL-composition turn plus schema exploration, not in
  the tool-call round trips this change removed).
- Model turns: before, `agent1`'s ReAct loop paid two tool round trips
  (`sql_validator`, then `databricks_sql_query`) inside its own turns before
  answering, plus `summarize1` — on the order of 4–5 model turns total.
  After: `agent1` writes SQL in one turn (occasionally one extra turn for a
  fallback search), `validate1`/`execute1` cost zero model turns, and
  `summarize1` is one turn — 2–3 model turns total.
- Failure test: fed `validate1`/`execute1` a hand-built draft naming
  `nonexistent_column_xyz` (bare, unaliased, so `validate1`'s alias-scoped
  existence check let it through — a known, recorded gap). `execute1` still
  caught it via the warehouse's own `UNRESOLVED_COLUMN` error (thanks to
  defect #2's fix) and returned `EXECUTION FAILED: warehouse reported
  FAILED: [UNRESOLVED_COLUMN.WITH_SUGGESTION] ...` verbatim rather than
  silently reporting empty results. `summarize1`'s prompt relays an
  `EXECUTION FAILED`-prefixed draft plainly rather than inventing numbers.
- Warehouse calls used across this session: 6, under the 8-call cap.

## What did not get fixed

`validate1`'s column-existence check is alias-scoped (mirrors the original
`SqlValidatorTool`): a bare, unaliased column reference is not checked
against Unity Catalog. It is caught one layer downstream regardless (defect
#2's fix), so no bad SQL result reaches the user, but `validate1` alone is
not a complete gate. Filed as a candidate follow-up; not fixed here because
it is validator-shape work orthogonal to this ticket's ask (moving
deterministic work out of the loop) and the existing two-layer defense
(validate, then execute's own error surfacing) already satisfies "never
silent" for this session's test.
