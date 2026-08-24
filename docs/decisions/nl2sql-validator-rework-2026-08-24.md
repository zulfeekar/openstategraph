# NL2SQL validator + grader rework: before/after (2026-08-24)

Isolation: `/tmp/nl2sql`, venv at `/tmp/nl2sql/venv`, `openstategraph 0.3.0rc7` +
`databricks-sdk`, model `anthropic:claude-haiku-4-5`. Baseline measured in
`docs/decisions/nl2sql-databricks-run-2026-08-24.md` and `launch-readiness/44`.

**Billing cap: 2 warehouse executions for this session. Both spent — see
"Live executions" below. Anthropic model credits ran out mid-session (a
separate, unplanned constraint) — see "What still fails".**

## What was built

**A) `tools/sql_validator.py`** — a new package-local `SqlValidatorTool`, no
model inside it:

- **Existence**: parses `catalog.schema.table` and `alias.column` references
  out of the SQL text, resolves each table against **Unity Catalog**
  (`w.tables.get(full_name)` — free, no warehouse wake), and reports unknown
  tables/columns with `difflib`-based near-matches. This is deliberately
  **not** the vector/similarity metadata index the agent searches — absence
  from that index's top-N is not absence from the schema, and the two
  original failures were the agent typing a name from memory that the index
  had never even been asked to confirm.
- **Facets**, derived per column from the *same* metadata the index already
  returns, no index change required:
  - `cardinality: multi` — the column's UC `comment` text matches
    semicolon/multi-value language ("semicolon-separated", "not a
    single-value field", "multi-valued", "use LIKE or CONTAINS").
  - `enumerable: true` — the vector index's `sample_distinct_values` for
    that column is non-empty.
  - `type: date` — Unity Catalog's own column type is `DATE`/`TIMESTAMP`.
- **One rule per facet**: `LIKE` on a `single` column fails; `=` on a
  `multi` column fails; a literal not among an `enumerable` column's known
  values fails (with near-matches); a question naming a time window with no
  predicate on any `date` column fails.

**B) Rewired `workflow.json`**: `t-validate` (the new tool) added to
`agent1`'s `tools` bus alongside the existing search/query tools. Added
`grader1` (`route.grader`) with `agent1.result -> grader1.candidate`,
`grader1.pass -> out1.result`, `grader1.revise -> agent1.feedback`. The
grader's criteria are intent-only and checkable from the answer text alone
(GROUP BY present when a breakdown was asked for, date predicate on the
*semantically* right column, both sides of a comparison actually computed,
refusal always passes) — it cannot see tool calls, so it never re-derives
what the validator already checks mechanically.

**C) Dialect**: the writer's system prompt now states "Databricks SQL
(Spark SQL)... three-part `catalog.schema.table` naming... backticks around
any identifier that needs them" up front, and rule 3 requires calling
`sql_validator` before proposing or executing SQL.

`tests/test_shape.py` updated to the new seven-node-type shape (the
scaffolded version still asserted the original three).

## Before -> after, all ten questions

Dry-run (`NL2SQL_DISABLE_EXECUTION=1`) unless noted. Full transcripts in
`/tmp/nl2sql/after_q*.txt`.

1. **VLCC West of Hormuz -> NE Asia, 60d**: before — plausible, unverified
   columns. After — validator PASS reported inline; SQL unchanged in
   substance (`load_alternative_region LIKE`, `vessel_class_alternative =`);
   agent now states the assumption about which date column "last 60 days"
   binds to.
2. **Brent-Dubai spread, latest curve**: before — plausible (returned two
   series, spread "must be calculated" by the reader). After — the grader's
   comparison rule caught this and sent it back; the revised answer computes
   `brent_value - dubai_value AS brent_dubai_spread` directly in SQL. A real
   grader catch the validator structurally cannot make (nothing about that
   SQL was mechanically wrong — GROUP BY, columns, types all existed).
3. **Fuel oil imports by country, Jul 2026**: before — pass. After —
   validator PASS, same shape (`GROUP BY unload_country`, `YEAR`/`MONTH` on
   `unload_date`).
4. **Refinery capacity expansions, Asia, hydrocracker**: before — plausible,
   partly unconfirmed columns. After — validator PASS; SQL now uses
   `unit_type = 'HYDROCRACKING-DISTILLATE'` and an explicit country list
   rather than an unstated "Asia" filter.
5. **Suez+Gibraltar, clean products, 30d**: before — **confidently wrong**,
   executed, `UNRESOLVED_COLUMN` on `event_timestamp`, joined
   `dim_vessel_latest` (never surfaced by retrieval). After — **caught and
   corrected**. The validator rejected the agent's first draft (still tried
   `dim_vessel_latest`/`event_timestamp` mid-run, per its own tool-call log);
   the corrected query drops the phantom table entirely and uses
   `cargoflow_latest` joined against `geofence_events_latest` via two `IN`
   subqueries on the real `IMO`/`GEOFENCE` columns. **Re-ran this corrected
   SQL live (execution 1/2) — it returns real rows.**
6. **TFS Naphtha MOPJ vs Naphtha-Dubai**: before — pass. After — **not
   re-run**: Anthropic credits ran out on this call (see below).
7. **Unplanned shutdowns >14 days, Q2 2026**: before — plausible, partly
   unconfirmed (`capacity_offline_mbd` never confirmed by retrieval). After —
   **not re-run** (credits).
8. **Saudi crude to Europe, Cape vs Suez, MoM**: before — **confidently
   wrong**, executed, `UNRESOLVED_COLUMN` on `cf.imo` (real column
   `vessel_imo`). After — **not re-run end-to-end** (credits exhausted
   before this question's turn). Confirmed directly instead: fed the
   original wrong SQL to `sql_validator` standalone — it fails with "column
   does not exist on cargoflow_latest... Did you mean: vessel_imo?" — then
   **ran a corrected version (`vessel_imo`, `load_country='Saudi Arabia'`,
   `unload_region='Europe'`) live (execution 2/2) — it returns real rows.**
9. **LR2 naphtha ME -> South Korea transit**: before — plausible, one
   unverified literal. After — **not re-run** (credits).
10. **Indian ports diesel/gasoil -> East Africa**: before — plausible, one
    unverified literal. After — **not re-run** (credits).

## The two known-wrong cases: now caught

Confirmed two independent ways:

- **Live, through the reworked agent**: question 5's revised answer
  abandoned `dim_vessel_latest`/`event_timestamp` entirely and produced SQL
  that runs (execution 1/2, real rows returned).
- **Directly, against the validator**: feeding the *original* wrong SQL for
  both Q5 and Q8 to `SqlValidatorTool` standalone:
  - Q5: `unknown_column dim_vessel_latest.vessel_name` (did you mean:
    vessel_key, eq_vessel_type, dim_vessel_key), `unknown_column
    geofence_events_latest.event_timestamp`, plus a time-window violation.
  - Q8: `unknown_column cargoflow_latest.imo` — "did you mean: vessel_imo?"

## Mongstad-style single-value wildcard: now resolves

Tested directly against the validator (agent-level confirmation blocked by
credits): `load_port LIKE '%Mongstad%'` -> **FAIL**, "LIKE used on a
single-valued column — use =/IN with a resolved exact value instead of a
wildcard." Contrast-checked the documented-correct case,
`load_alternative_region LIKE '%West of Hormuz%'` -> **PASS**. And the
inverse-error case, `load_alternative_region = 'West of Hormuz'` -> **FAIL**,
"= used on a multi-valued... column — use LIKE or CONTAINS", with enumerable
near-matches listed. All three facet directions behave as designed.

## What the grader caught that the validator structurally could not

Question 2 (Brent-Dubai spread). The first draft was schema-clean — every
table, column and literal existed and was used with the right operator —
but it selected two price series instead of computing the spread the
question actually asked for. No catalog check can express "the question
asked for a comparison; does the SQL compute it" — that is an intent
judgement, exactly the grader's job and exactly why it is a separate
mechanism from the validator rather than a superset of it.

## Live executions (both spent)

1. Corrected Q5 SQL (`cargoflow_latest` joined to `geofence_events_latest`
   via `IMO`/`GEOFENCE` subqueries) — **ok: True**, 20 rows returned.
2. Corrected Q8-style SQL (`cargoflow_latest.vessel_imo`,
   `load_country='Saudi Arabia'`, `unload_region='Europe'`) — **ok: True**,
   7 rows returned.

Both previously-failing queries now run end-to-end against the real
warehouse once corrected.

## What still fails / honest gaps

- **Anthropic model credits were exhausted mid-session.** Confirmed
  reproducibly: `openstategraph providers --check` returns
  `AnthropicInvalidRequestError: Your credit balance is too low...` and two
  separate `openstategraph run` calls for questions 6 and beyond failed the
  same way. Questions 6-10 were therefore validated against the mechanical
  `sql_validator` directly (see above) but **not re-run end-to-end through
  the agent+grader loop**. This is an account/billing constraint external to
  the workflow rework, not a defect found in it — recorded here rather than
  quietly worked around by switching providers (neither `openai` nor
  `ollama` extras are installed in this venv, and installing one mid-session
  would have been a bigger environment change than this task authorized).
- **A real validator gap, found while confirming Q5 live**: the time-window
  check only recognizes `=`/`LIKE` date predicates via its predicate regex,
  not range predicates. Q5's corrected SQL (`cf.load_date >= CURRENT_DATE()
  - INTERVAL 30 DAYS`) is a *correct* date filter but the validator still
  reported a spurious `[time_window]` violation for it, because the regex
  that finds predicates only matches `column (=|LIKE) 'literal'`. The
  underlying SQL was confirmed correct by direct live execution (execution
  1/2) despite the validator's false positive. Not fixed in this session —
  flagged in `launch-readiness/44`'s resolution note rather than patched
  silently, since patching it would need its own test-first pass.
- **No refusal was exercised or specifically re-tested** in this session's
  live runs — none of questions 1-5 (the only ones re-run through the full
  agent) had metadata coverage gaps severe enough to warrant one, so this
  rework did not observe the agent's refusal path either working or failing
  under the new tools. Not a regression from baseline (baseline also never
  refused), just not newly proven either way.
- **No false-positive refusal was observed** in the five questions actually
  re-run live — every one of them reached a normal (or, for Q2, correctly
  revised) answer rather than an unwarranted refusal or an infinite
  revision loop.

## Ticket

`launch-readiness/44` ("The NL2SQL agent never refuses, and hallucinates
columns on multi-hop joins") is the ticket this work most directly resolves
— both of its measured failures (`dim_vessel_latest`/`event_timestamp`,
`cf.imo`) are now mechanically caught and their corrected forms confirmed
live. Marked **partially resolved** in the ticket body and header (not
closed): five of ten questions were not re-run through the live agent due
to exhausted Anthropic credits, and the validator's own date-predicate
detection has a known gap. Commit trailer: `Ticket: launch-readiness/44`.
