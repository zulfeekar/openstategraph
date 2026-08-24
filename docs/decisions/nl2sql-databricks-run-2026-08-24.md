# Fifth stranger run: NL2SQL against real Databricks (2026-08-24)

Isolation: `/tmp/nl2sql`, venv at `/tmp/nl2sql/venv`, `openstategraph[server,anthropic]==0.3.0rc7`
from Test PyPI plus `databricks-sdk` (package-local). Profile
`adb-7405605452558986`, warehouse `Serverless Starter Warehouse`.

**Billing cap: 2 SQL statements for the whole session. Both spent, both
failed on hallucinated column names — see "Two executions" below.**

## Setup

- `pip install` of `openstategraph[server,anthropic]==0.3.0rc7` and
  `databricks-sdk`: clean, no errors.
- `openstategraph init . --force` then `openstategraph new cpl-nl2sql
  "CPL NL2SQL" --template minimal`. Copied the `sql-qa` example for
  reference (it uses the generic prebuilt `tool.sql-*` SQLite atoms, not
  Databricks — no reusable code, only shape).
- Package-local tool file: `tools/databricks_nl2sql.py`, two `BaseTool`
  subclasses:
  - `DatabricksMetadataSearchTool` — wraps `vector_search_indexes.query_index`
    (HYBRID, `nl2sql_metadata_index`). Free, read-only.
  - `DatabricksSqlQueryTool` — wraps `statement_execution.execute_statement`
    on the Serverless Starter Warehouse. Refuses non-`SELECT` statements and
    statements that reference no known `ms_cpl_app_prod` table before they
    reach the warehouse. Respects `NL2SQL_DISABLE_EXECUTION=1` for dry runs
    (used for every one of the 10 questions below — no warehouse wake from
    the agent loop itself).
  - `requirements.txt` with `databricks-sdk`, kept out of the installed
    `openstategraph` package per the isolation instructions.

### The package-local tool channel did not work on the first try

`openstategraph validate` and `openstategraph run` both reported "No
implementation for tool" for both classes, even though calling
`capability_discovery.discover_tool_instances()` directly found them fine.
Root cause, found by reading `openstategraph/api/capability_discovery.py`:
`discover_tool_registry()` keys its registry by **`instance.node_type`**,
not by the qualified id (`<slug>/tools.ClassName`) that
`discover_tool_instances()` returns. `BaseTool.node_type` defaults to `""`,
and my first draft never set it — a tool with an empty `node_type` is
"listable but not placeable" by design (the docstring says so). Setting
`node_type = "cpl-nl2sql/tools.DatabricksMetadataSearchTool"` (and the query
tool's counterpart) explicitly on each class — matching the id already used
in `workflow.json`'s node `"type"` — fixed it; `wf.warnings` went from two
entries to none.

This is a real gap worth a ticket: nothing in `AGENTS.md`'s scaffold text or
the `tools/` convention table says a package-local tool must set its own
`node_type` to the qualified id, and the failure mode (silent "ran without
it", not a hard error) is easy to miss in a longer agent transcript. Filed as
`launch-readiness/42`.

Also worth noting: `openstategraph validate`'s underlying tool
(`ValidateWorkflowTool` in `prebuilt_architect.py`) checks node types against
`known_node_types()` and a fixed `KNOWN_PREFIXES = ("tool.", "function.")` —
it has no notion of the `<slug>/tools.*` prefix at all, so it reports
"unknown node type" for a *correctly wired* package-local tool even after the
`node_type` fix above (confirmed separately from the `run`-path fix, which
uses a different code path — `discover_tool_registry` — that does resolve it
correctly). `validate` is therefore a false-negative surface for this
channel. Filed as `launch-readiness/43`.

## The ten questions

All ten were run via `openstategraph run workflows/cpl-nl2sql "<question>"`
with `NL2SQL_DISABLE_EXECUTION=1` (metadata search live, SQL execution
tool refuses to hit the warehouse and reports the validated statement
instead). Full SQL for two is under "Two executions"; the rest are
summarized — full transcripts are reproducible with the command above.

| # | Question | Table(s) right? | Columns confirmed by retrieval? | Verdict |
|---|---|---|---|---|
| 1 | VLCC, West of Hormuz → NE Asia, 60d | `cargoflow_latest` — right | Mostly (`vessel_class_alternative`, `load_alternative_region`, `unload_shipping_region_v2`) but used bare `imo`/`vessel_name`, never confirmed against retrieval | Plausible, unverified column risk |
| 2 | Brent-Dubai spread, latest curve | `silver_forward_curves_metadata_v1` + `_ts_v1` — right, correct join key (`metadata_id`) | Yes | Plausible |
| 3 | Fuel oil imports by country, Jul 2026 | `cargoflow_latest` — right | Yes (`unload_country`, `group_product`, `unload_date`); `quantity` not explicitly confirmed | Pass |
| 4 | Refinery capacity expansions, Asia, hydrocracker | `plant_tracker_capacity` — right | `unit_type LIKE '%HYDROCRACK%'` matches the documented `HYDROCRACKING-DISTILLATE` value; `change_type='EXPANSION'` and the capacity/date columns were never returned by any search shown to the agent | Plausible but partly unconfirmed |
| 5 | Vessels transiting Suez AND Gibraltar, clean products, 30d | `geofence_events_latest` + `cargoflow_latest` — right tables, **but** joined in a third table, `dim_vessel_latest`, that no search ever surfaced, and used `event_timestamp`, a column that does not exist | **Confidently wrong** — executed, see below |
| 6 | TFS Naphtha MOPJ vs Naphtha-Dubai, latest date | `silver_forward_curves_metadata_v1`/`_ts_v1`, correct curve-name spelling ("Naptha") from the glossary hit | Yes | Pass |
| 7 | Unplanned shutdowns >14 days, Q2 2026 | `plant_tracker_events` — right, `outage_type='UNPLANNED'` correct per glossary | `capacity_offline_mbd` never confirmed by any search result shown | Plausible but partly unconfirmed |
| 8 | Saudi crude to Europe, MoM, Cape vs Suez | `cargoflow_latest` + `geofence_events_latest` — right tables, plausible route-inference design (join geofence crossing to voyage window) | **Wrong**: used `cf.imo` (real column is `vessel_imo`) and `ge.event_datetime` (not confirmed) | **Confidently wrong** — executed, see below |
| 9 | LR2 naphtha ME → South Korea transit time | `cargoflow_latest` — right | `vessel_class_alternative = 'Aframax/LR2'` is a guess never confirmed as the literal value; rest confirmed | Plausible, one unverified literal |
| 10 | Indian ports, diesel/gasoil → East Africa, grades | `cargoflow_latest` — right | `grade`, `load_port`, `unload_country`, `group_product` confirmed; `unload_region='Africa'` value never confirmed as the literal used by the column | Plausible, one unverified literal |

**No honest refusal was observed across all ten.** The system prompt
explicitly told the agent to refuse when metadata doesn't support the
question, and it never did — even for #5 and #8, where it had clear cause
(a joined table and two columns the search never returned). This is itself
a finding: the "read tolerantly, trust strictly" tolerance was too loose in
practice — the agent trusted its own guesses at column/table names that its
own retrieval never confirmed, rather than treating an unconfirmed name as
grounds to search again or say so. Filed as `launch-readiness/44`.

## Two executions (the billing cap)

Spent on the two multi-hop joins judged most likely to be wrong: **#5**
(Suez+Gibraltar, three-table join) and **#8** (Saudi Cape-vs-Suez MoM,
temporal join between cargo and geofence events). Both were run essentially
as the agent generated them, with only a `LIMIT 20` added.

**#5** — failed:
```
[UNRESOLVED_COLUMN.WITH_SUGGESTION] A column, variable, or function parameter
with name `event_timestamp` cannot be resolved. Did you mean one of the
following? [`updated_at`, `EXIT_HEADING`, `EXIT_TIME`, `DRAUGHT`, `ENTRY_TIME`].
SQLSTATE: 42703
```
Confirms the hallucination: no `event_timestamp` column exists on
`geofence_events_latest`; the real timestamp columns are `ENTRY_TIME`/
`EXIT_TIME`. (The query also joins `dim_vessel_latest`, a table search never
surfaced — never reached because the first error was earlier in the plan.)

**#8** — failed:
```
[UNRESOLVED_COLUMN.WITH_SUGGESTION] A column, variable, or function parameter
with name `cf`.`imo` cannot be resolved. Did you mean one of the following?
[`cf`.`group`, `cf`.`grade`, `cf`.`category`, `cf`.`quantity`, `cf`.`vessel_imo`].
SQLSTATE: 42703
```
`cargoflow_latest` has no `imo` column — it is `vessel_imo`, which the agent
used correctly in question #1's answer but not here. The inconsistency
across runs (same table, two different guesses for the same column) shows
the failure is a guess, not a stable (even if wrong) belief about the
schema.

## The three worst things

1. **Column-name hallucination is real and not rare.** Two for two on the
   executions I spent, and visible by inspection in at least two more
   (`imo` vs `vessel_imo` drift, `capacity_offline_mbd` and
   `quantity_bbls`/`event_timestamp`/`event_datetime` never confirmed by any
   retrieval result the agent saw). The system prompt's rule 1 ("never
   reference a table or column name it did not return") was not enough on
   its own — nothing in the loop enforces it.
2. **No honest refusal, ever**, including on the two questions where the
   agent's own retrieval evidence should have triggered one. The refusal
   path in the prompt is unexercised.
3. **The package-local tool channel silently no-ops without an explicit,
   undocumented `node_type` declaration**, and `openstategraph validate`
   independently misreports a correctly-wired package-local tool as an
   "unknown node type" — two related but distinct gaps in the one channel
   this run existed to prove out.

## Tickets filed

- `launch-readiness/42` — package-local tool silently unbound without an
  explicit `node_type`; `AGENTS.md`'s scaffold doesn't say so.
- `launch-readiness/43` — `openstategraph validate`'s node-type check doesn't
  know the `<slug>/tools.*` prefix, so it false-negatives a correctly wired
  package-local tool.
- `launch-readiness/44` — the NL2SQL agent never refuses even when its own
  retrieval evidence doesn't cover the table/columns it uses; two
  multi-hop joins hallucinated a table and column names, confirmed by
  running the generated SQL against the real warehouse.

## Not done

Per instructions, no OSG code was fixed during this run — findings only,
filed as tickets above.
