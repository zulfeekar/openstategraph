# One tolerant, strict SQL extractor for the NL2SQL demo (2026-08-25)

Work done in `~/osg-demo/` (`workflows/cpl-nl2sql/`), the live demo package.
Backed up to `~/osg-demo-backup/` before and after.

## The defect

The last remaining common failure per `nl2sql-false-reject-fixes-2026-08-25.md`:
the model sometimes omits the ```sql fence, so nothing downstream can extract
the SQL. It cost Q7 and Q8 their first attempt each on the 2026-08-25 re-run,
burning a revision lap each — 0 warehouse calls spent, but a wasted round trip.
Per CLAUDE.md's "read a model's answer tolerantly; trust it strictly", the fix
is a more tolerant parser, not a stronger prompt.

## The fix: one extractor, three consumers

New file: `tools/sql_extraction.py` — `extract_sql(text) -> str`, raising
`SqlExtractionError` naming what was searched for when nothing trustworthy is
found. No model call, no Databricks call.

Consumers, all previously carrying their own copy of a ```sql-only regex
(duplication CLAUDE.md forbids):

- `functions/validate_sql.py` — removed its own `_SQL_FENCE`/`_extract_sql`;
  now calls `extract_sql`, catching `SqlExtractionError` to produce the same
  `VALIDATION FAILED` message shape as before.
- `functions/execute_sql.py` — same swap for `EXECUTION FAILED`. Also dropped
  the now-unused `import re`.
- `tools/sql_validator.py` (`SqlValidatorTool._execute`) — did **not**
  previously extract at all; it trusted `args.sql` (a structured tool
  argument) verbatim. Now runs it through `extract_sql` too, defensively: a
  model that doesn't reliably respect the fence contract on its final answer
  has no stronger reason to respect a "give me raw SQL only" tool-arg
  contract — it can still hand back a fenced or prose-prefixed value.

`tools/sql_validator.py` is loaded two different ways in this package: as
`tools.sql_validator` by consumers that already put the package root on
`sys.path` (the `functions/*.py` files), and directly via `exec()` by
openstategraph's `capability_discovery`, which does **not** put the package
root on `sys.path`. A plain `from tools.sql_extraction import ...` failed
live under the second loader (`ModuleNotFoundError: No module named 'tools'`
— confirmed by running Q7 before this was caught, which silently dropped
`SqlValidatorTool` from the agent's tool list with only a console warning).
Fixed by loading the sibling file directly via `importlib.util.spec_from_file_location`
relative to `__file__`, which works under both loaders.

## Shapes accepted (tolerant) / rejected (strict)

Accepted, last-qualifying-block-wins where more than one exists (a revision
lap restates the corrected query after the wrong one):
- ```sql ... ``` (happy path), ``` ... ``` untagged, ```SQL/```Sql/```postgresql/```spark-sql
- an unclosed fence (opened, never closed) — takes everything after it
- no fence at all — prose followed by a SELECT/WITH statement. Unfenced text
  gets one extra gate fenced code does not: the FROM clause must name a
  dotted (`catalog.schema.table`) reference immediately after FROM. Every
  real table in this warehouse is three-part, so this is a domain fact, not
  an arbitrary tightening — and it's exactly what separates
  `SELECT vessel_name FROM ms_cpl_app_prod.shipping.cargoflow_latest` from
  prose like "you can select any vessel from the list", which also matches
  `SELECT...FROM` lexically but never has a dotted identifier there.

Rejected, always, regardless of source: more than one statement (an internal
`;`), any DML/DDL verb anywhere in the extracted text (`INSERT`, `UPDATE`,
`DELETE`, `DROP`, `ALTER`, `CREATE`, `TRUNCATE`, `MERGE`, `GRANT`, `REVOKE`),
and — when nothing extractable is found at all — a loud `SqlExtractionError`
naming every source tried, never a silent pass-through of the prose as SQL.

## Ordinary-content test

`tests/test_sql_extraction.py::test_ordinary_prose_mentioning_select_is_not_sql`:
"You can select any vessel from the list, and I'd recommend filtering by IMO
number for accuracy." must raise, not extract a bogus statement — it matches
`SELECT...FROM` lexically but fails the qualified-FROM gate. Also covered: a
refusal with no SQL in it, an empty string, a JSON-only fence, multi-statement
and DML/DDL rejection. 23 tests total, all pass (`python3 -m pytest
tests/test_sql_extraction.py -q`).

## Live re-run: Q7, Q8, Q10 (control)

`openstategraph run ./workflows/cpl-nl2sql "<question>"`, live warehouse
(`NL2SQL_DISABLE_EXECUTION` unset).

| Q | Question | Seconds | Laps | Numbers? |
|---|---|--:|--:|---|
| 7 | Unplanned shutdowns > 14 days, Q2 2026 | 42 | 1 | **Yes** — Geelong ALKYLATION-HYDROFLUORIC #1, 625-day outage |
| 8 | Saudi crude to Europe MoM, Cape vs Suez | 102 | 1 | **Yes** — monthly Cape/Suez volumes and % change table returned |
| 10 (control) | Indian ports, diesel/gasoil grades to East Africa | 36 | 1 | **Yes** — 6 distinct grades returned |

All three completed in a single lap this run — the fence was present on the
first attempt each time, so the tolerant-extraction fallback paths were not
exercised live (they are covered by the unit tests above). No
`VALIDATION FAILED` or `EXECUTION FAILED` text appeared in any of the three
runs. This is consistent with the standing finding that the omission is
intermittent model non-compliance, not a deterministic trigger — the fix
makes the pipeline correct either way, whether or not this particular re-run
happened to reproduce it.

Warehouse (SQL execution) calls used: 3 (Q7, Q8, Q10), well under the 6-call
cap for this session.

## Restart

Two stale `openstategraph serve` processes were found running on ports 57674
and 59250 before this session's restart (leftover from earlier sessions);
both killed, lock file cleared, server restarted fresh. `/api/health` →
`{"ok":true,"editor_stale":null,"model_configured":true}`. Live at
`http://127.0.0.1:61013/?w=cpl-nl2sql`.

Ticket: launch-readiness/12
