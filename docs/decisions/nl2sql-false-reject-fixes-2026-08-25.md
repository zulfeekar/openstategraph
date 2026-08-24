# NL2SQL false-reject fixes and re-run (2026-08-25)

Work done in `~/osg-demo/` (`workflows/cpl-nl2sql/`), the live demo package.
Backed up to `~/osg-demo-backup/` before and after. Server restarted fresh
after editing `tools/`/`functions/`.

## Columns confirmed genuinely STRING-typed via `w.tables.get()`

- `ms_cpl_app_prod.shipping.ais_sampled`: `YEAR`, `YEAR_MONTH`, `YEAR_MONTH_DAY`
- `ms_cpl_app_prod.balances.plant_tracker_events`: `start_date`, `end_date`, `last_updated`

(Every other date-ish column checked — `cargoflow_latest`, `geofence_events_latest`,
`silver_forward_curves_ts_v1`, `plant_tracker_capacity` — is UC DATE/TIMESTAMP.)

## The three fixes

**1. C1 STRING-date false-reject — SOFT (recognition-only, cannot reject).**
Added `_is_date_typed(col_name, uc_type)` to `tools/sql_validator.py` (mirrored
in `functions/validate_sql.py`): true for UC DATE/TIMESTAMP, or STRING whose
name matches `date|year|month|day|_dt$|timestamp`. Used in both the per-column
facet resolver and the broadened time-window scan. This only widens what
counts as "a date predicate was seen" — it can turn a false FAIL into a PASS,
never the reverse, so it cannot introduce a new false-reject.

**2. A1 bare-column existence hole — HARD, narrowly scoped.** Bare (unqualified)
identifiers were never existence-checked at all — only `alias.col` forms were.
Added a check inside the existing predicate loop (facet 3) only: a bare
identifier compared against a literal (`col = '...'` / `col LIKE '...'`) is
flagged only when (a) at least one table was resolved, (b) it matches no
column of any referenced table, and (c) it is not a `... AS name`-defined
alias/CTE output (collected via a new `_AS_ALIAS` regex). Scoped to predicate
context specifically to avoid the false-reject risk of parsing SELECT-list
aliases generally.

**3. B3 literal-guessing warning — kept SOFT, not hardened.** Per the brief's
own warning, hardening enumerable-mismatch into a hard fail would false-reject
a real high-cardinality value merely absent from the sample. Instead fixed a
separate bug found while inspecting the path: `execute_sql.py` discarded
`validate1`'s warning lines entirely when stripping the `VALIDATION: PASS`
header. Now `_run_query` returns `(rendered, row_count)`, warning lines are
preserved, and when a query returns exactly 0 rows and had a live enumerable
warning, an explicit `NOTE: this query returned 0 rows, and validation had
already warned...` is prepended to the raw-results block the summarizer reads.

**Rule 9 (fence) check**: already correct on both sides — the contract's rule
9 explicitly requires exactly one ` ```sql ` fence, and both `execute_sql.py`
and `validate_sql.py` already detect and report its absence plainly
(`VALIDATION FAILED: no \`\`\`sql fenced block found...`). No code gap; this
is model non-compliance, reproduced live below (Q7/Q8 first attempts).

## Re-run: six failures (1, 2, 4, 6, 7, 8) + control (10)

Live warehouse runs (`NL2SQL_DISABLE_EXECUTION` unset), `openstategraph run`.

| Q | Seconds | Laps | Numbers? | Cause if still failing |
|---|--:|--:|---|---|
| 1 | 103 | 3 | **Yes** | — |
| 2 | 39 | 3 | **Yes** | — (previously 0 rows on unresolved curve-name literals; model resolved them this run) |
| 4 | 55 | 3 | **Yes** (1 row, Iraq) | — |
| 6 | 38 | 3 | **Partial** (one series has NULLs before its curve's start) | not a validator issue — genuine partial data coverage |
| 7 | 33 then 51 | 4 then 4 | first attempt: No (Rule 9, no fence); **retry: Yes** | first attempt was model non-compliance (no fence), 0 warehouse calls; retry confirms the C1 STRING-date fix — `CAST(start_date AS DATE) BETWEEN ...` passed validation |
| 8 | 50 then 84 | 4 then 4 | first attempt: No (Rule 9, no fence); **retry: No (0 rows)** | first attempt was model non-compliance (no fence), 0 warehouse calls; retry produced valid, non-bare-column SQL (the A1 bug did not reproduce this run) but returned 0 rows — an unconfirmed `via_geofence`/`unload_alternative_region` literal, a B3-class issue distinct from A1 |
| 10 (control) | 66 | 3 | **Yes** | — |

**9 of 10 original questions now return numbers when the fence requirement is
met** (Q5, Q9, Q10 already passed; Q1, Q2, Q4, Q7 now pass; Q6 partial; only
Q8 still returns 0 rows, for a B3-class reason, not the A1 defect this
session targeted). Both Q7 and Q8 needed one retry each because the model
omitted the SQL fence on the first attempt — a real, reproduced instance of
the Rule 9 gap, costing 0 warehouse calls each time since validation (correctly)
never reaches execution without a fence.

Warehouse (SQL execution) calls used: 7 (Q1, Q2, Q4, Q6, Q7-retry, Q8-retry,
Q10), well under the 12-call cap. UC/`w.tables.get()` metadata calls for the
STRING-type confirmation are free (no warehouse wake) and not counted.

## Honest gaps not closed this session

- Rule 9 fence omission is a real, recurring model-compliance failure (hit
  twice in this seven-question re-run) with no code fix possible without a
  revise-loop wired to a typed feedback port — out of bounds per the
  package's own recorded design choice (fail loudly, not a fake string
  convention).
- Q8 still returns 0 rows on retry, for an unresolved-literal (B3-class)
  reason distinct from the A1 defect this session fixed. Deliberately not
  hardened, per the false-reject constraint.

Ticket: launch-readiness/12
