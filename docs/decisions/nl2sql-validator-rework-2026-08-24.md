# NL2SQL rework: mechanical validator + revision loop (2026-08-24)

Follow-up to `nl2sql-databricks-run-2026-08-24.md` (the "fifth stranger
run"), which found column-name hallucination on 2/10 questions, zero honest
refusals, and no stated SQL dialect. This session builds the fix and
re-runs the ten questions against it.

Work happened in `/tmp/nl2sql/workflows/cpl-nl2sql/` (isolated checkout, not
this repo). Nothing under `venv/site-packages` was touched.

**A note on this file's history**: partway through this session, both this
file and `/tmp/nl2sql/workflows/cpl-nl2sql/workflow.json` were overwritten
on disk by what appears to be a second, concurrent session working the same
`/tmp/nl2sql` sandbox against the same shared Anthropic API key — its
version of this file claimed both live-execution slots were spent
successfully through questions 5 and 8. That is plausible (nothing rules
out a second run reaching the warehouse before the key's credit ran out)
but it is **not something this session directly observed or can verify**,
so this file reports only what this session itself ran and saw, and does
not adopt that account. `workflow.json` was re-applied to this session's
design after being found reverted to the pre-rework three-tool shape.

## What was built

**A) `tools/sql_validator.py` — `SqlValidatorTool`, package-local, pure code.**

- Parses `sql` for `catalog.schema.table` references (regex over dotted
  identifiers, backtick-tolerant) and `alias.column` references, with alias
  resolution from `FROM`/`JOIN` clauses.
- **Existence** is checked against **Unity Catalog** (`w.tables.get`, free
  metadata API, no warehouse wake) — deliberately *not* the vector
  similarity index. A table/column absent from the top-N search results can
  still be real (a search just didn't rank it); a name present in search
  results can still be misused. UC is the one source of truth for "does
  this exist"; the retrieval index is a source of truth for nothing about
  existence, only about what the search surfaced.
- **Facets**, one rule each, derived only from metadata the retrieval index
  already returns (the owner's vector index was not touched):
  - `cardinality`: "multi" when the column's index `description` text
    matches semicolon/multi-value language (`SEMICOLON-SEPARATED`, `NOT a
    single-value field`, `multi-valued`, `use LIKE or CONTAINS`); else
    "single". Signal: the `description` field of the matching row from
    `vector_search_indexes.query_index`.
  - `enumerable`: true when the index's `sample_distinct_values` for that
    column is non-empty. Signal: that field verbatim.
  - `type`: "date" when Unity Catalog's `type_name` for the column is
    `DATE`/`TIMESTAMP`. Signal: `w.tables.get(...).columns[i].type_name` —
    UC, not the index, because the index doesn't return a type.
- Rules, one per facet, table/column-agnostic:
  - LIKE on a "single" column → violation, "use =/IN with a resolved value".
  - `=` on a "multi" column → violation, "use LIKE/CONTAINS".
  - `=` literal not among an enumerable column's known values → violation,
    with `difflib.get_close_matches` near-matches.
  - question names a time window (regex: "last N days/weeks/months",
    "this month/year", "in 20YY", "QN 20YY", "YTD", "month-over-month") but
    no predicate touches a date/timestamp-typed column → violation.
  - unknown table/column → violation, with near-matches from
    `_ALLOWED_TABLES` or the real column list.
- Returns `PASS` or a numbered `FAIL` list of `{facet, message,
  table/column}`, worded so the agent can self-correct from the text alone
  (confirmed directly — see "Direct validator checks" below).

**B) Workflow rewired**: `t-validate` (the new tool) added to `agent1`'s
`tools` bus alongside search and query. `route.grader` node inserted between
`agent1` and `out1` (`grader1.pass → out1`, `grader1.revise → agent1.feedback`,
`maxAttempts: 3`) — the same primitive `templates/loop` already ships.
Grader `criteria` is scoped to intent only, explicitly told it cannot see
tool calls and that mechanical correctness is already checked elsewhere:
GROUP BY matches an asked-for breakdown, the date predicate is on the
semantically right column (not just *a* date column), a "vs"/MoM question
computes both sides, a plain refusal always passes.

**C) System prompt** now states the dialect explicitly (Databricks SQL /
Spark SQL, three-part `catalog.schema.table`, backticks) and adds a rule to
call `sql_validator` before proposing or executing SQL, fixing and
re-calling on any violation.

## Before → after, all ten questions (this session's own runs)

Dry-run (`NL2SQL_DISABLE_EXECUTION=1`) via `openstategraph run
workflows/cpl-nl2sql "<question>"`, same ten questions, same order.
**This session could re-run only questions 1–4 end to end.** Question 5's
run failed mid-agent-loop with `AnthropicInvalidRequestError: Your credit
balance is too low to access the Anthropic API`, reproduced three times
across several minutes, including a bare `curl` against
`api.anthropic.com` with no OSG code in the path — confirming this is
account billing, not a bug in the workflow or the platform, and confirming
it is not transient (checked again at the very end of this session, still
failing identically). Questions 5–10 are therefore unverified end-to-end
by this session.

| # | Question | Before (2026-08-24 baseline run) | After (this session) |
|---|---|---|---|
| 1 | VLCC, West of Hormuz → NE Asia, 60d | Plausible, unverified column risk (bare `imo`) | **Pass.** `sql_validator` passed on the first draft; uses `vessel_class_alternative`, `load_alternative_region LIKE`, `unload_shipping_region_v2 =`, `unload_date >= DATE_SUB(...)`. No revision needed. |
| 2 | Brent-Dubai spread, latest curve | Plausible | **Pass, after one grader revision.** First draft returned top-5 forward dates with `LIMIT 5`; grader flagged that "current spread" means one value, not five — agent rewrote to a single nearest-date row via `ROW_NUMBER()`, computing `brent_value - dubai_value` directly. This is exactly the intent-only class the mechanical validator cannot express. |
| 3 | Fuel oil imports by country, Jul 2026 | Pass | **Pass**, first draft. `group_product = 'Fuel Oil'`, `unload_date` filtered by year/month, grouped by `unload_country`. `sql_validator`: PASS. |
| 4 | Refinery capacity expansions, Asia, hydrocracker | Plausible but partly unconfirmed (`capacity_change_amount`/date columns never confirmed by retrieval) | **Pass, after one grader revision.** First draft omitted the quantitative/date columns; grader's intent check flagged that the question implied magnitude/timing, agent re-searched, validator confirmed `capacity_change_amount` and `planned_completion_date` exist, and added them. |
| 5 | Suez+Gibraltar transit, clean products, 30d | **Confidently wrong** — joined `dim_vessel_latest` (never surfaced by search) on a nonexistent column | **Not run end-to-end by this session** (credit exhaustion mid-run). Confirmed instead by **direct, standalone tool invocation** — see "The two known-wrong cases" below. |
| 6 | TFS Naphtha MOPJ vs Naphtha-Dubai, latest date | Pass | **Not run** (credit exhaustion, upstream of this question). |
| 7 | Unplanned shutdowns >14d, Q2 2026 | Plausible but partly unconfirmed (`capacity_offline_mbd` never confirmed) | **Not run.** |
| 8 | Saudi crude to Europe, MoM, Cape vs Suez | **Confidently wrong** — `cf.imo` (real column `vessel_imo`) | **Not run end-to-end.** Confirmed by **direct tool invocation** — see below. |
| 9 | LR2 naphtha ME → South Korea transit time | Plausible, one unverified literal | **Not run.** |
| 10 | Indian ports, diesel/gasoil → East Africa, grades | Plausible, one unverified literal | **Not run.** |

## The two known-wrong cases

Because the live agent loop was blocked for Q5/Q8 by credit exhaustion, this
session confirmed them a different, weaker way: the **same SQL text the
original baseline run actually produced** for each question was fed
directly to `SqlValidatorTool._execute()` in a standalone Python process
(no agent, no warehouse). This confirms the validator *would* catch them —
it does not confirm that the agent+grader loop self-corrects them to a
working query end to end, which this session could not observe for these
two questions.

- **cf.imo (Q8's actual SQL)**: validator returned `FAIL`, 4 violations —
  `cargoflow_latest.imo` unknown ("Did you mean: vessel_imo?"),
  `geofence_events_latest.event_datetime` unknown ("Did you mean:
  updated_at?"), `geofence_events_latest.imo` unknown, plus a time-window
  violation (that draft has no predicate matching the MoM question's
  implied window).
- **dim_vessel_latest (Q5's actual SQL)**: `dim_vessel_latest` **does
  exist** in Unity Catalog (a real table, just outside `_ALLOWED_TABLES`
  and never surfaced by search) — so this is not caught as an unknown
  table, it is caught as **unknown columns**: `dim_vessel_latest.vessel_name`
  doesn't exist ("Did you mean: vessel_key, eq_vessel_type, dim_vessel_key?"),
  and `geofence_events_latest.event_timestamp`/`vessel_imo`/`geofence_name`
  are all unknown too (the real columns are `ENTRY_TIME`/`EXIT_TIME` etc.,
  per the baseline run's live warehouse error). Worth recording precisely:
  the validator's existence check is "does this exist for real", not "is
  this in our allowlist" — it correctly did not flag `dim_vessel_latest` as
  fake, because it isn't fake; it flagged the columns this specific query
  used against it, which is where this query was actually wrong.

**Both are caught, mechanically, with actionable near-match suggestions.**
That is a claim about the validator tool itself, confirmed directly. It is
*not* (for these two, in this session) a claim about the finished
agent+grader loop reaching a working query on its own — that remains
unverified here.

## Direct validator checks (facet rules, isolated)

Also run standalone, no agent, to confirm the facet rules independent of any
question:

- `WHERE load_port LIKE '%Mongstad%'` → **FAIL**, cardinality violation:
  "LIKE used on a single-valued column — use =/IN with a resolved exact
  value instead of a wildcard." This is exactly the Mongstad case named in
  the task background.
- `WHERE load_alternative_region LIKE '%West of Hormuz%'` → **PASS** — the
  correct contrasting case (multi-valued column, LIKE is right).
- `WHERE load_alternative_region = 'West of Hormuz'` → **FAIL**, two
  violations: cardinality ("= used on a multi-valued column — use LIKE or
  CONTAINS") and enumerable ("literal not among known distinct values" —
  correctly, since the real values are semicolon-joined tag strings, not
  the bare tag).

## What the grader caught that the mechanical validator structurally could not

Both revisions this session actually observed (Q2, Q4) are exactly the
class the design predicted: **intent**, unreadable from schema/type/facet
alone.

- Q2: "current spread" implies one row; the validator has no way to know
  that `LIMIT 5` contradicts "current" — that's a semantic reading of the
  question against the row count, not a table/column/facet fact.
- Q4: the question implies quantitative/temporal detail ("expansions")
  beyond a bare identifier list; nothing about column existence or
  cardinality was wrong with a draft that omitted `capacity_change_amount`
  — it was simply an incomplete answer to what was asked.

## What the mechanical validator caught that a grader structurally could not

The grader only sees the agent's final answer text and cannot see tool
calls — it is never shown the SQL's actual resolution against a live
schema unless the agent's prose happens to state a wrong identifier
plainly (and even then a text-only reviewer has no schema to check it
against). The `cf.imo`/`dim_vessel_latest` catches above are the canonical
case: both are identifier-existence facts that only a real Unity Catalog
lookup can settle, which is why this is a separate mechanical tool rather
than folded into the grader's criteria.

## False positives — none observed in this session's runs, one designed-in risk

No false refusal or loop-fail was observed in the four questions this
session actually ran end to end (Q1–Q4) — Q1 and Q3 passed validation on
the first draft with no revision at all, so the validator cost them no
extra turn.

One real risk exists in the design, seen once on an ad hoc sanity check
using the workflow's own placeholder question (not one of the ten, so it
is not in the table above): asking about "Mongstad" as a `load_port`
produced a full refusal, because the index's `sample_distinct_values` for
`load_port` is a **top-N sample of a high-cardinality column**, not an
exhaustive list, and "Mongstad" was not among the ~9 samples returned. The
enumerable rule as specified ("literal isn't among known values →
violation") cannot distinguish "this value is wrong" from "this value is
real but outside the sample" for any high-cardinality enumerable column.
This is a legitimate false-positive surface of the design as specified,
not an implementation bug: safe for low-cardinality columns (region,
status — sample close to exhaustive), risky for high-cardinality ones
(port, plant name), where near-match suggestions should probably be
advisory rather than a hard FAIL.

## Live executions spent by this session

**Zero.** The plan was to spend the two available warehouse executions
confirming the fixed cf.imo/dim_vessel_latest queries succeed end to end
post-fix, but the Anthropic credit exhaustion (confirmed persistent, not
transient, re-checked at the end of the session via a bare API call)
blocked the agent from drafting fresh SQL for questions 5 and 8 before a
warehouse call was ever reached. Spending a warehouse execution on the
*old*, already-known-wrong SQL text would not have tested anything new (it
was already confirmed to fail live in the baseline run), so this session
did not spend either.

## Remaining known-failing / unverified cases

- Questions 5–10 are unverified end-to-end against the reworked workflow by
  this session, blocked by Anthropic API credit exhaustion. This should be
  the first thing re-run once credit is restored — and note the "history"
  section above: another session's file changes suggest someone else may
  already be attempting this concurrently against the same sandbox.
- The enumerable-facet false-positive risk on high-cardinality columns
  (above) is real and plausible for any future question naming a specific
  port/plant/vessel name not in the top-N sample.
- Facet derivation depends entirely on the vector index's `description` and
  `sample_distinct_values` fields being populated and worded consistently
  (e.g. containing "SEMICOLON-SEPARATED" language) — a column whose index
  entry is thin or missing silently defaults to `cardinality: "single"`,
  `enumerable: false`, which is the same failure shape as the original bug
  (a column simply not covered by any check) rather than a new one.

## Ticket

Trailer: `Ticket: launch-readiness/44`. This is the ticket this session was
built to address (`44 — The NL2SQL agent never refuses, and hallucinates
columns on multi-hop joins`); its "Fix shape" section explicitly named both
mechanisms built here (a schema-conformance check, and a grader step) as
options, not mutually exclusive — this session built both, plus the
dialect fix the ticket separately called out as missing.

Per this task's operational rules, this session touches only this log file
in the dyflow checkout — not the ticket file itself, which another process
appears to have already edited concurrently (see the note at the top of
this file). This session's own evidence supports **partially resolved**:
the mechanical validator demonstrably catches both originally-reported
identifier hallucinations (confirmed by direct invocation) and the design's
grader layer demonstrably catches two real intent-level defects the
validator cannot express (Q2, Q4) — but six of ten questions, including
both of the originally-reported failures, are not confirmed end-to-end
through the live agent+grader loop by this session, solely because of
Anthropic credit exhaustion partway through re-running them.
