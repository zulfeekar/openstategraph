# An agent that reaches CPL through MCP

## What this proves

A separate, small OpenStateGraph package — `~/osg-cpl-mcp/`, not a second
`cpl-nl2sql` — showing an agent reach CPL's own MCP server and come back with
something real, with no lens files, validator, or router copied across.

## Getting CPL's MCP server up

The employer repo's own runner, `scripts/stack.sh up`, not a hand-rolled
uvicorn invocation — its README documents `dev.py` for data-prep, not for
serving. Docker Desktop was not running; started it, then `stack.sh up` built
and started the backend, frontend, and auth containers.

MCP URL: `http://localhost:8080/mcp/`. An `initialize` handshake and a
`tools/list` call confirmed it, rather than trusting the README. It actually
advertises 13 tools, not the four the README names: `mcp_resolve_lens`,
`mcp_list_lenses`, `mcp_skill_read`, `mcp_skill_list`, `mcp_skill_grep`,
`mcp_execute_sql`, `mcp_fetch_result_page`, `mcp_describe_lens_tables`,
`mcp_describe_table`, `mcp_search_tables`, `mcp_lookup_canonical_value`,
`mcp_lookup_few_shot`, `mcp_prepare`.

## The workflow

Five nodes, not four — `in1` (input.text) → `agent1` (agent.llm) →
`grader1` (route.grader) → `out1` (output.formatted), with `mcp1` (tool.mcp)
wired to `agent1.tools`. The grader was added mid-session on explicit
instruction; see below.

`mcp1.data.servers[0].url` points at `http://localhost:8080/mcp/`; the
`server` field is left blank (setting it triggers a project-registry lookup
that ignores the URL).

`agent1.model = "openai/gpt-5-mini"`, `agent1.tier = "deep"`. The deep tier
resolves through `create_deep_agent` (`deepagents`), installed into the
shared `~/osg-demo/venv` alongside the `mcp` extra — neither was present
before this session. Per LangChain's own docs (`FilesystemBackend` page,
`docs.langchain.com/oss/*/deepagents/backends`), a deep agent's filesystem
defaults to `StateBackend` — thread-scoped, stored in LangGraph state, no
disk access — unless a backend is explicitly overridden. Nothing in this
repo's `node_runtime.py` overrides it, so the write tool the system prompt
tells `agent1` to use (`write findings to /findings/*.json instead of
pasting them back into the conversation`) is inherently sandboxed by the
runtime, not by anything this package configured.

`grader1.criteria` judges two things against the question and the agent's
own recorded findings, explicitly stated as *"pass means this answers what
was asked, never that it is true"*: intent match (right window, right
entity/grouping, right metric — not a nearby question answered instead) and
groundedness (traceable to real tool output, not filled in from the model's
prior knowledge). `maxAttempts: 2`. `pass → out1`, `revise → agent1.feedback`.

No extra skill file was needed — the server's own `instructions` field,
returned at `initialize`, already tells the agent which tool to call first
(`mcp_resolve_lens`, falling back to `mcp_list_lenses`), so the bare wiring
was enough.

## Proof run

Question: *"Which lenses are available?"*

Verbatim answer (deep tier, passed the grader on the first attempt):

> Available lenses (15):
>
> - area_activity — Area activity (domain: sm) — primary tables: sm.area_counts_latest, sm.geofences_latest, sm.master_vessel_type_latest
> - balances — Global balances (domain: gb) — primary tables: gb.country_v1r0, gb.flow_v1r0, gb.geo_area_v1r0, gb.location_mapping_v1r0, gb.product_v1r0, gb.region_grouping_v1r0, gb.region_v1r0, gb.source_v1r0, gb.ts_data_v1r0, gb.ts_metadata_v1r0, gb.unit_v1r0, sm.cargoflow_latest
> - cargoflow — Cargo flows (domain: sm) — primary tables: gb.ts_metadata_v1r0, sm.area_counts_dark_v1r0, sm.cargoflow_latest, sm.dim_vessel_latest, sm.geofence_events_latest
> - current — Current prices (domain: pricing) — primary tables: pricing.forward_curves_metadata_v1, pricing.forward_curves_ts_v1
> - dark_fleet — Dark fleet (domain: sm) — primary tables: sm.area_counts_dark_v1r0, sm.cargoflow_latest, sm.dim_vessel_latest, sm.geofences_latest
> - geofence — Vessel transits (domain: sm) — primary tables: sm.cargoflow_latest, sm.current_vessel_positions_latest, sm.geofence_events_latest, sm.geofences_latest, sm.master_vessel_type_latest
>   - Note: geofence is unavailable on this deployment (sm.geofence_events_latest unreachable). Do NOT route here; pick another lens.
> - geofence_silver — Transits by class (domain: sm) — primary tables: sm.cargoflow_latest, sm.dim_vessel_latest, sm.geofences_latest
> - historical — Price history (domain: pricing) — primary tables: pricing.historical_forward_curves_metadata_v1, pricing.historical_forward_curves_ts_v1
> - idle_events — Idle events (domain: sm) — primary tables: sm.dim_vessel_latest, sm.geofences_idle_v1r0, sm.idle_events_v1r3
> - outage_events — Outage events (domain: pt) — primary tables: pt.Plants_v1r0, pt.events, pt.marketing_company_v1r0
> - outage_product — Outage by product (domain: pt) — primary tables: pt.Plants_v1r0, pt.UnitType, pt.outage_product_timeseries
> - outage_timeseries — Outage capacity (domain: pt) — primary tables: pt.MasterLocationTable, pt.OutageCategory, pt.OutageType, pt.Plants_v1r0, pt.UnitType, pt.outage_full_metadata, pt.outage_full_timeseries
> - trajectories — Vessel trajectories (domain: sm) — primary tables: sm.current_vessel_positions_latest, sm.dim_vessel_latest, sm.trajectories_latest
> - vessel_positions — Vessel positions (domain: sm) — primary tables: sm.current_vessel_positions_latest, sm.dim_vessel_latest, sm.master_vessel_status_latest, sm.master_vessel_type_latest
> - voyage_events — Voyage events (domain: sm) — primary tables: sm.cargoflow_latest, sm.dim_vessel_latest, sm.voyage_events_latest
>
> Findings saved to /findings/lenses.json (list of lenses and primary tables).

Tools called: `mcp_list_lenses` (visible from the answer shape and the
findings-file offload), reached through the MCP tool bus rather than a
direct HTTP call.

## Deferred, not built

A durable cross-session pattern store ("cache the approach, never the
answer") was requested but explicitly deferred to protect the working
MCP+grader wiring under a near-exhausted budget — filed as
`launch-readiness/99`.

## The dark-fleet table, measured — 2026-08-27

`launch-readiness/116` reported three runs of one question giving three
dark-vessel answers. The three answers were re-derived from the data rather
than from the prose, and the divergence is fully explained by two facts about
`sm.area_counts_dark_v1r0` that **no lens on this deployment declares**.

Measured directly through `mcp_execute_sql` on 2026-08-27:

| Measure | Value |
| --- | --- |
| rows | 2,208,572 |
| distinct `imo` | 10,096 |
| rows per IMO | **~219** — the grain is geofence × day × IMO |
| rows with `dark = 1` | 1,454,449 |
| distinct IMO ever `dark = 1` | 6,119 |
| `MIN(day)` / `MAX(day)` | **2026-01-01 / 2026-05-12** |

The last row is the expensive one. Its sibling `sm.area_counts_latest`, the
same shape without the dark flag, runs to **2026-08-26** — yesterday. So the
dark table is 3½ months stale in a warehouse whose neighbouring tables are
current, and nothing on the deployment says so: `dark_fleet/SKILL.md` states
its grain as "daily" and declares no coverage window, and `cargoflow/SKILL.md`
line 93 declares the join as `acd.imo = cf.vessel_imo; always filter dark = 1`
— a key and a predicate, with no grain, no cardinality and no dedup.

### Why one question gives two answers

The question asks about **last month** (July 2026), which is outside the dark
table's data entirely. Both joins an agent can reasonably write are then
*correct SQL for different questions*, and neither answers the one asked:

```sql
-- 58 distinct vessels loaded at Mongstad in July 2026
dark ever      (no day predicate)          -> 1 vessel   -- LYRIC CAMELLIA, IMO 9730933
dark in window (day within the question's) -> 0 vessels  -- necessarily: no rows exist after 2026-05-12
```

LYRIC CAMELLIA's only two dark days are **2026-01-05 and 2026-02-21** — five
and seven months before the voyages it is reported against. So the "1 dark
vessel" answer is a vessel that was dark at some point in the table's window,
not last month; and the "0 dark vessels" answer is an absence the filter
guaranteed, reported as a finding.

Re-run live three times on 2026-08-27 against `cpl-mcp` (wheel `0.3.0rc7`,
`openai/gpt-5-mini`): **2 dark / 0 dark / 0 dark** — the same one-in-three
split the ticket recorded, with the same 55 rows and 22,765,104 barrels
underneath the two zeros.

The `dark ever` run also inflated the population it reported: **48,557,027
barrels against the same 55 rows' 22,765,104**, a 2.13× fan-out, because a
per-IMO/day table joined without a `SELECT DISTINCT imo` dedup multiplies the
cargo rows it decorates. That is `launch-readiness/98`'s defect exactly, one
table over, and the same fix applies — the join is only safe through a
deduplicated subquery. The deployment's own
`_cross_cutting/JOINS.yaml` already carries that canonical shape
(`WITH dark_vessels AS (SELECT DISTINCT imo ... WHERE dark = 1 AND day >= ...)`,
`INNER JOIN`); the lens the agent actually reads does not repeat it.

**Neither join is the right one, and the correct answer is a refusal**: for a
window after 2026-05-12 this warehouse cannot establish whether a vessel was
dark. Nothing in this repository can enforce that — the lens layer for this
deployment lives in the CPL intelligence service, not here — so the finding is
filed for that lens's owner as `launch-readiness/118`, and the general form
(coverage as a declared, checkable fact) as `launch-readiness/119`.
