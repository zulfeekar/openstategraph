# NL2SQL rule-contract sweep — 2026-08-25

Full audit of `agent1`'s six-group rule contract (A grounding, B filtering, C
time, D shape, E dialect, F honesty — 22 rules total) against what
`tools/sql_validator.py` / `functions/validate_sql.py` mechanically enforce,
plus a live run of all ten questions after closing the cheap gaps.

## Audit — classification of all 22 rules

| Class | Before | After |
|---|---|---|
| MECHANICAL | 4 (A1, B1, B3, C1) | **9** (+D1, D2, D3, E1, E3) |
| CLOSEABLE | 7 (D1,D2,D3,E1,E3,F1,F3) | **2** (F1, F3) |
| PROMPT-ONLY | 9 (A2,A3,B2,B4,C2,C3,C4,D4,D5) | 9 (unchanged) |
| UNENFORCEABLE | 2 (E2, F2) | 2 (unchanged) |

**13 of 22 rules (59%) are still not machine-guaranteed** — 9 prompt-only
(pure judgement: which date column matches the verb, whether a literal was
genuinely resolved, whether "top-N" was implied) and 2 unenforceable (E2's
positive "use the right function" can't be checked exhaustively; F2's
refusal is only correct relative to ground truth this validator doesn't
have). F1 (an Assumption line exists) and F3 (every number in the prose
appears in a result row) are CLOSEABLE but not implemented — see below.

## Checks added to `tools/sql_validator.py` (`shape_and_dialect_checks`,
shared by the tool and by `functions/validate_sql.py`'s duplicate gate logic)

- **D1** one statement, SELECT/WITH only — **hard fail**. A DML verb or a
  second statement is unambiguously wrong; no false-reject risk (parity-
  checked semicolons so a `;` inside a string literal doesn't trip it).
- **D2** no `SELECT *` — **hard fail**. Unambiguous.
- **D3** non-aggregate SELECT items not in GROUP BY — **soft warning**. Text
  heuristic (can't see CTEs/window functions/aliasing perfectly), so kept
  soft per the "never false-reject" instruction. It still caught a real bug
  live (see Q8).
- **E1** reserved word double-quoted or used bare after `.` — **hard fail**.
  Unambiguous Databricks-SQL-dialect fact.
- **E3** forbidden T-SQL/Postgres tokens (`TOP `, `GETDATE(`, `ISNULL(`,
  `[brackets]`, `::`, `SELECT INTO`) — **hard fail**. Unambiguous.
- **F3** number-in-prose-must-be-in-results — implemented as a standalone
  `check_numbers_in_prose()` but **not wired into the graph**: it needs both
  the executed rows and the summarized prose, both downstream of the only
  node this package gives a mechanical check a seat at (`validate1`, which
  runs before execution). Wiring it needs a new node after `summarize1` — a
  `workflow.json` graph-shape change, out of scope for "close the cheap
  ones" the day before the demo.

  **Correction, 2026-08-28 (`launch-readiness/151`).** The sentence above says
  the check was "implemented as a standalone `check_numbers_in_prose()`". It
  was not. Nothing of that name existed in this repository, in
  `~/osg-demo/workflows/cpl-nl2sql`, or in any of the seven backups of that
  package — only this paragraph claiming it, and `git log -S` finds the claim
  and no code. That is the same defect the rule itself is about: an assertion
  with no way to fail.

  It is written now, in `backend/openstategraph/grounded_numbers.py`, and
  wired — but **not as a package function**, which is why it could not have
  been one. `guard.check` calls `fn(text: str) -> str`, and that signature sees
  the candidate prose and nothing else; F3 needs the **evidence** as well. So
  core supplies it as a built-in check named `numbers_in_prose`, reading tool
  results out of `messages` and deterministic step outputs out of `outputs`. A
  package function of the same name still wins, so an adopter can override it.

All new checks verified against both a known-good query (no false positives)
and deliberately-bad ones (SELECT *, DELETE, TOP 10, ungrouped column,
double-quoted `"group"`) before wiring in. `pytest tests/` still shows the
pre-existing, unrelated `test_document_shape` failure (stale node-type list);
nothing I touched regressed it.

## Ten questions — live run (2026-08-25, real warehouse execution)

| # | Question (topic) | Seconds | Attempts | Numbers? | Rule violated |
|---|---|--:|--:|---|---|
| 1 | VLCC west of Hormuz → NE Asia, 60d | 44 | 4 | No | **Rule 9 (output contract)**: agent emitted the SQL with no ` ```sql ` fence at all — `validate1` found nothing to extract, 4 attempts never fixed it, final answer was a bare failure message |
| 2 | Brent-Dubai spread, latest curve | 58 | 4 | No (0 rows) | B3: unresolved curve-name literals (`'ICE Brent Fut London'`, `'Dubai Sing'`) never confirmed against known values |
| 3 | Fuel oil imports by country, Jul 2026 | 42 | 3 | **Yes** | none found |
| 4 | Refinery capacity expansions, Asia, hydrocracker | 58 | 4 | No (0 rows) | B3: `country_area = 'Asia'` never confirmed as the literal spelling |
| 5 | Vessels transiting Suez+Gibraltar, clean products, 30d | 53 | 3 | **Yes** (42 vessels) | none found — correctly backticked `` `group` `` |
| 6 | TFS Naphtha MOPJ vs Naphtha-Dubai, latest date | 64 | 4 | Partial (one side NULL) | B3: `'Naptha vs Dubai'` curve name guessed, returned no match |
| 7 | Unplanned shutdowns >14d, Q2 2026 | 64 | 4 | No | **Validator false-reject**: SQL correctly filtered `CAST(start_date AS DATE) BETWEEN ...`, but `start_date` is UC-typed STRING (dates stored as strings in this table), so C1's type-gated date-predicate scan never saw it as a date column |
| 8 | Saudi crude to Europe, MoM, Cape vs Suez | 85 | 4 | No | Genuine defect, correctly rejected: SELECT referenced a bare `route` column that was **never defined** — the CASE expression computing it only appears in GROUP BY, not SELECT. D3 flagged this as a symptom; the real issue is A1 (grounding) — bare unqualified columns bypass the existing unknown-column check entirely (only `alias.col` refs are checked) |
| 9 | LR2 naphtha ME → South Korea transit time | 36 | 3 | **Yes** (2,594 voyages, 27.8d avg) | B3 risk only: `'Aframax/LR2'` literal is an assumption, not confirmed |
| 10 | Indian ports, diesel/gasoil → East Africa, grades | 42 | 3 | **Yes**, matches the earlier genie-parity run | none found |

**Warehouse calls: 7 of 12** (Q1, Q7, Q8 never reached `execute1`). Well
under the cap; all ten questions ran.

## What was actually broken in practice

1. **Rule 9 (fenced ```sql block) failed outright on Q1** — not a schema or
   dialect issue, a literal formatting miss that made a plausible, well-formed
   query unusable. This is the same class of defect CLAUDE.md's "read
   tolerantly" section warns about, in the opposite direction: the *agent*
   didn't follow the format the *parser* requires.
2. **The mechanical C1 date-window check has a live gap**: it trusts Unity
   Catalog's column *type* to know a column is a date, but this schema stores
   real dates as STRING in at least two columns (`start_date`,
   `load_start_of_month` is suspected too) — causing two false rejections
   (Q7, Q8) of otherwise-correct, well-formed date filters. Not fixed this
   session (recurring pattern, needs a design decision — value-shape
   sniffing vs. a column allowlist — rather than a quick patch); recorded
   here rather than silently patched.
3. **A1 has a real hole**: unknown-column checking only covers `alias.col`
   references; a bare, undefined identifier like Q8's `route` sails through.
   Caught this run only because D3 happened to also flag it.
4. B3 (unresolved-literal) risk showed up in half the questions (2, 4, 6, 9)
   — every one a *warning*, never a hard block, exactly as designed; each
   one produced a wrong or empty answer instead of an honest refusal (F2 is
   unenforceable and it showed — no refusal was ever emitted, consistent
   with the prior `launch-readiness/44` finding).

## Not verified

- Whether `load_start_of_month` (used in Q8) is also STRING-typed in UC —
  inferred from the failure pattern, not directly queried, to stay under the
  warehouse cap.
- C2/C3/C4/D4/D5/A2/A3/B4 (all PROMPT-ONLY) were not scored per-question
  against the contract beyond what's in the table above — that would need a
  human or grader read of every SQL statement, out of scope for a mechanical
  sweep.

Ticket: launch-readiness/12
