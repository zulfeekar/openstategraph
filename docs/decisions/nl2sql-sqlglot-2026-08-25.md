# NL2SQL validator moves from regex to sqlglot AST parsing (2026-08-25)

Work done in `~/osg-demo/` (`workflows/cpl-nl2sql/`), the live demo package.
Backed up to `~/osg-demo-backup/` before and after.

## Directive change mid-task

The task began as "sqlglot primary, regex fallback for parse failures." The
owner corrected this mid-session: **sqlglot only, no dormant second
implementation.** The surviving safety rule is a *policy*, not code: if
`sqlglot.parse_one(sql, dialect="databricks")` cannot parse the statement (or
resolves it to something other than a single SELECT/WITH/set-op), the
validator returns a `parse_warning` string and skips every check rather than
rejecting — the warehouse remains the authority of last resort. Everything
below reflects that final directive; no regex validation logic survives
alongside the AST checks.

## What moved to the AST

`tools/sql_validator.py` — every check now reads `sqlglot.parse_one` plus
`sqlglot.optimizer.scope.build_scope`, not the SQL text:

- **A1 (the real prize) — column existence**, walking every `exp.Column` per
  scope. `scope.sources` distinguishes a real `exp.Table` (checked against
  Unity Catalog) from a CTE/subquery/derived-table source (never checked —
  its own output columns are out of scope for this pass, so it is never
  false-rejected). A bare column is resolved against every base-table source
  visible in its scope, or accepted silently if it matches a same-scope
  `SELECT ... AS` alias. Closes the hole the regex validator had: only
  `alias.col` was checked before; a bare undefined identifier like
  `nl2sql-rule-sweep-2026-08-25.md`'s Q8 `route` bug sailed through. See
  `tests/test_sql_validator.py::test_bare_undefined_column_is_flagged` (must
  fail) and `test_bare_column_that_is_a_cte_output_is_not_flagged` /
  `test_bare_column_that_is_a_select_alias_in_same_scope_is_not_flagged`
  (must pass) — the exact three shapes the old regex code could not tell
  apart.
- **C1 — date predicate**, found structurally: `exp.Between`/`In`/comparison
  nodes whose operand resolved to a date-typed column, plus `exp.Cast` to
  DATE/TIMESTAMP and `date_trunc`/`to_date`/`to_timestamp`/`date_sub`/
  `date_add` calls wrapping a column. The STRING-typed-date-column widening
  from the previous session (`ais_sampled.YEAR*`, `plant_tracker_events.
  {start_date,end_date,last_updated}`) is preserved verbatim in
  `_is_date_typed` — it is a UC-type-recognition fact, not a text pattern,
  and removing it would reopen the exact false-reject class that cost Q7/Q8
  a lap each on 2026-08-24/25.
- **B1/B2 — cardinality**, from `exp.EQ`/`exp.Like` predicate nodes directly,
  resolving the column side through the same scope walk as A1.
- **D1 — one statement, SELECT/WITH only.** `sqlglot.parse` returning other
  than one expression, or a root outside `{Select, Union, Except, Intersect,
  With}`, is now an AST fact in both `sql_extraction.py` (finding the
  candidate) and `sql_validator.py` (defensive re-check).
- **D2 — `SELECT *`.** Any `exp.Star` directly in a `Select`'s projection
  list is a hard violation.
- **D3 — GROUP BY completeness.** Kept soft on purpose: Unity Catalog's
  column list carries no key/functional-dependency metadata, so a selected,
  non-aggregated column not textually present in GROUP BY is a **warning**,
  never a violation — a real primary-key-driven GROUP BY would otherwise be
  false-rejected. `test_group_by_completeness_is_a_warning_not_a_violation`
  pins this.
- **E3 — dialect.** Judged **not reliable enough to be hard**: by the time
  SQL reaches the validator it already parsed under the `databricks`
  dialect (extraction requires it), so a genuinely un-parseable T-SQL query
  never arrives here — it already became a parse-failure warning upstream.
  What can still arrive is Databricks-parseable SQL carrying T-SQL-flavoured
  spelling sqlglot's permissive grammar accepts anyway (`GETDATE()`,
  `ISNULL(...)`, `[bracketed]` identifiers, `TOP n` in the rare case it
  parses). This stays a text-pattern **warning**, never a violation —
  `test_tsql_flavoured_syntax_is_caught_as_warning_not_violation` covers the
  `GETDATE()` case that does parse; `TOP 10` in practice fails to parse under
  `databricks` and is covered by the parse-failure test instead.

`tools/sql_extraction.py` — candidate *location* (fence-finding, statement
spans) is still regex/string work, since that's a text-position problem, not
a SQL-grammar one. But whether a located candidate *is* SQL is now decided
entirely by `sqlglot.parse`: the dotted `catalog.schema.table`-after-FROM
heuristic for unfenced text is gone, replaced by "does it parse as one
read-only SELECT/WITH". A real bug surfaced fixing this: `_candidate_from_bare_text`
was being invoked as a fallback on the *raw, fence-marker-included* text
whenever a closed fence's body failed to qualify (e.g. two statements in one
fence), letting a semicolon-split fragment leak out and falsely succeed.
Fixed by gating the bare-text path to run only when no fence marker
(closed or unclosed) is present in the text at all — a fence is the model's
own "this is code" declaration and a disqualified fence body should never be
second-guessed by re-scanning the surrounding raw text.

## Parse-failure behavior (the whole safety net)

`validate(sql, question, w) -> (violations, warnings, parse_warning)`. When
`parse_warning` is not `None`, `violations` and `warnings` are both `[]` —
every check was skipped, not failed. `functions/validate_sql.py` renders this
as `VALIDATION: PASS (parse warning: ...)`, the same header `execute1`
already treats as "let it through to the warehouse." `SqlValidatorTool`
renders it as a plain `WARNING: ...` `ToolResult`, never a `ToolResult.failure`.
`tests/test_sql_validator.py::test_unparseable_sql_warns_and_skips_checks_rather_than_failing`
asserts the contract directly (garbled non-SQL input → empty
violations/warnings, non-`None` parse_warning);
`test_valid_databricks_query_that_is_hard_for_sqlglot_still_warns_not_fails`
asserts the same policy against a LATERAL VIEW/EXPLODE construct, accepting
either outcome (parses cleanly, or warns) but never a crash or a fabricated
violation — this is the "valid Databricks query sqlglot might choke on"
case the task asked to make real rather than notional.

## DRY fix along the way

`functions/validate_sql.py` previously carried its own ~150-line copy of the
same checks, imported by private regex-helper name from `sql_validator.py`.
Those names no longer exist post-rewrite, which forced the duplication to be
resolved rather than silently broken: `tools/sql_validator.py` now exposes
`validate(sql, question, w=...)` as a plain function, and
`functions/validate_sql.py` is reduced to the transport concern (extract,
call `validate`, render the `VALIDATION FAILED`/`VALIDATION: PASS` header
contract `execute1` gates on).

## Tests

`tests/test_sql_extraction.py` (23 tests) — all pass. Two tests changed
meaning rather than assertion direction, both genuine false-reject closures
from moving to AST rather than regressions:
`test_update_disguised_as_cte_name_is_still_rejected` →
`test_bare_column_named_update_is_allowed_by_ast` (a column merely *named*
`update` is not DML — sqlglot's root is still `Select`), and
`test_delete_verb_inside_string_literal_still_rejected_strict_by_design` →
`test_delete_verb_inside_string_literal_is_allowed_by_ast` (a string literal
containing the word "delete" is not a DML statement). Every other existing
test passes unchanged.

`tests/test_sql_validator.py` (new, 14 tests) — all pass, covering: bare
column undefined (fail), bare column that is a CTE output (pass), bare
column that is a same-scope SELECT alias (pass), `BETWEEN` on a date column
(passes the time-window check), `LIKE` on a multi-valued column (pass),
`=` on a multi-valued column (fail), `LIKE` on a single-valued column
(fail), `SELECT *` (fail), GROUP BY completeness (warning only), T-SQL
`GETDATE()` (warning only, not a violation), and the two parse-failure-policy
tests described above.

`python3 -m pytest tests/` in the package: 38 collected, 37 pass. The one
failure, `test_shape.py::test_document_shape`, is a pre-existing,
node-type-list drift against `workflow.json` — unrelated to this change
(neither `sql_extraction.py` nor `sql_validator.py` nor `workflow.json` node
types were touched by it), confirmed by inspecting the test: it asserts a
fixed scaffolded node-type list that predates work done in earlier sessions
on this same package.

## Live verification: Q7, Q8, Q10

`cd ~/osg-demo && ./venv/bin/openstategraph run ./workflows/cpl-nl2sql "<q>"`,
live warehouse, no `NL2SQL_DISABLE_EXECUTION`.

| Q | Question | Result | Vs. last run (`nl2sql-tolerant-extraction-2026-08-25.md`) |
|---|---|---|---|
| 7 | Unplanned shutdowns > 14 days, Q2 2026 | Geelong ALKYLATION-HYDROFLUORIC #1, start 2026-04-15, 625-day duration | Matches — same event, same duration |
| 8 | Saudi crude to Europe MoM, Cape vs Suez | Monthly Cape/Suez/Other volume table returned (dozens of rows) | Matches — monthly volume table returned as before |
| 10 (control) | Indian ports, diesel/gasoil grades to East Africa | Per-port/grade volume table, several distinct grades | Matches — 6+ distinct grades returned as before |

No regression. No `VALIDATION FAILED` or `EXECUTION FAILED` in any of the
three runs (`grep -c` on `serve.log` for both strings: 0). All three
completed in a single lap. **Warehouse calls used: 3** (Q7, Q8, Q10), well
under the 6-call cap.

## Restart and health

Server killed, lock file removed (`osg-demo-1098f5c4/serve.lock` — the
actual state-dir name; `nl2sql-*` in the original instructions did not
exist), restarted with `--port 0`. Live at
**http://127.0.0.1:62372/** (editor), **http://127.0.0.1:62372/chat**.
`GET /api/health` → `{"ok":true,"editor_stale":null,"model_configured":true}`.

## requirements.txt

`sqlglot` (and `pytest`, needed to run the new test files) added to
`workflows/cpl-nl2sql/requirements.txt` — package-local, never touching the
installed `openstategraph` package.

Ticket: launch-readiness/12
