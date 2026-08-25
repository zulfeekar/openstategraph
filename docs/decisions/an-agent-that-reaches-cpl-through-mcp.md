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
