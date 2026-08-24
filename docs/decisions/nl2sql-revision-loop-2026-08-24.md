# NL2SQL revision loop — workaround, measured (2026-08-24)

Ticket: launch-readiness/12. Product gap this works around: launch-readiness/65
(`function.*` nodes emit `result`, not `feedback`, so a plain validator cannot
route `revise` back to an agent).

## What shipped, in `/tmp/nl2sql/workflows/cpl-nl2sql/workflow.json`

```
in1 → prefetch1 → agent1 → validate1 → gate1 → relay1 → execute1 → summarize1 → out1
                    ▲                    │
                    └──── revise ────────┘
```

`gate1` (`route.grader`, `openai/gpt-5-mini`, `reasoningEffort: low`,
`maxAttempts: 2`) transcribes `validate1`'s own deterministic verdict —
criteria explicitly forbid re-judging the SQL, only reading the `VALIDATION:
PASS` / `VALIDATION FAILED` header on the candidate's first line. `gate1.revise
→ agent1.feedback` closes the loop.

## A second, undocumented product gap, found by running it

`gate1.pass → execute1.text` looked right and validated clean, but every run
failed with `EXECUTION FAILED: no fenced sql block found`, even though the
text sitting in `outputs["gate1"]` plainly contained one. Traced into
`openstategraph/compile/node_runtime.py`: `_discovered_function` (the handler
behind every `function.*` node, including `execute1`) resolves its input as

```python
upstream = [src for src, dst in plan.edges if dst == node_id]
...
text = _upstream_text(state, upstream) or state.get("question", "")
```

— static edges only. A grader's `pass`/`revise` ports dispatch over
`plan.conditional`, not `plan.edges`, so `upstream` is empty for any
`function.*` node placed downstream of them, and the node silently falls back
to the original user question. `_agent`, `_output`, `_guardrail` and
`_memory_segment` all already compute a `conditional_upstream` list and OR it
in; `_discovered_function` (and `_router`'s and `_grader`'s own candidate
resolution) never got that fix. Not something this repo can patch — it is
inside the installed `openstategraph` package.

**Workaround**: `relay1`, a plain `agent.llm` node with no tools, sits between
`gate1.pass` and `execute1.text`. Its only instruction is to reproduce the
input byte-for-byte; because it is an `agent.llm` node it *does* resolve
`conditional_upstream`, so it receives gate1's routed text correctly, and its
own `result` port is an ordinary static edge into `execute1`, which
`_discovered_function` reads the normal way. Confirmed by running it: the SQL
survived the relay unchanged in every run below.

An earlier attempt — restore the static `validate1 → execute1` edge and leave
`gate1.pass` unwired, relying on the existing `VALIDATION FAILED` short-circuit
inside `execute1` — caused a genuine infinite loop instead: `_router_for`
falls back to the first *wired* destination for an unmapped verdict label, so
a wired-only-`revise` grader routed every `pass` back into `agent1.feedback`
too. Reverted; both `pass` and `revise` must be wired.

## Measurements

**1. The failing month-over-month question** (`What is the month-over-month
trend in crude exports from Saudi Arabia to Europe via the Cape of Good Hope
versus Suez?`) — **self-corrected on the first pass, zero revision laps.**
`agent1`'s first draft already used `via_geofence IN (...)`, grouped by
`load_start_of_month` (a real date predicate), and dropped the LIKE-on-Crude
predicate entirely rather than emitting the wrong literal — so `validate1`
never raised any of the three original violations and `gate1` passed on
attempt one. 49s wall-clock. This is a **negative result on the specific
three-violation reproduction**: the loop is wired and (per the exhaustion test
below) does fire when needed, but this run did not exercise it, so "fixed all
three" cannot be claimed from this run — the agent avoided them, it did not
visibly repair them. Final answer (verbatim, truncated to the table):

> Summary — only the Suez route returned results; Cape of Good Hope returned
> no rows in the raw output, so a direct comparison is not possible. The Suez
> route shows these month-level volumes and month-over-month percent changes:
> [table: 2024-01-01 631839 —, 2025-08-01 529400 -16.21%, 2026-08-01 23746
> -95.51%] — SQL used: `SELECT load_start_of_month AS month, via_geofence AS
> route_geofence, SUM(quantity)... FROM ms_cpl_app_prod.shipping.cargoflow_latest
> WHERE load_country = 'Saudi Arabia' AND (unload_shipping_region_v2 = 'Europe'
> OR unload_region = 'Europe') AND via_geofence IN ('cape_of_good_hope',
> 'suez_canal_complete') AND load_start_of_month IS NOT NULL ...`

**2. Fujairah, unchanged** — passed first try, 27–30s wall-clock across two
runs (27.4s, 30s), well inside the "+5-10s over 38s baseline" budget (came in
*faster*, likely prompt-cache warmth). Daily average dwell hours: 23.90,
19.04, 19.68, 14.32, 14.78, 14.69, 20.55, 19.88, 16.84, 16.81, 19.71, 20.57 —
matches the 14.32–23.90h range and ≈18.4h mean.

**3. Exhaustion test** — `functions/validate_sql.py` temporarily patched to
always return a synthetic `VALIDATION FAILED` (reverted immediately after,
diffed clean against the pre-patch copy). Result: two revise laps, then
`gate1` force-passed the still-failing text through `relay1` → `execute1`
(which refuses to run anything starting `VALIDATION FAILED`) → `summarize1`.
What the user saw, verbatim:

> I could not complete the query: validation failed with 1 violation —
> "forced_test: synthetic violation injected to test the revision loop
> exhaustion path."

No SQL was executed, no invented numbers — exactly the required behavior.

**Prefetch search health**: the Databricks CLI token needed a fresh
`databricks auth login --profile adb-7405605452558986` at the start of this
session (confirmed working after that). Despite that, `prefetch_context`'s
concurrent phrase searches still logged intermittent `cannot get access
token: ... forced token refresh: cache update: exit status 45` on 3-4 of 5
phrases per run in two of the three runs above — a token-cache race between
the concurrent lookups, not an expired token. Every run still produced a
usable answer because enough phrases succeeded and the glossary/entity-dictionary
matches (which don't hit the CLI token path the same way) filled the gaps, but
prefetch did **not** all-succeed in any of the three runs measured.

**Warehouse calls** (`statement_execution.execute_statement`, the 8-call cap):
2 total across all measured runs — 1 for Fujairah, 1 for the month-over-month
question. The exhaustion test never reached `execute1`'s real query path.

**Model turns**: agent1, gate1, relay1, summarize1 — 4 model-bearing nodes,
matching the CLI's reported `attempts: 3-4` per run (the counter includes the
grader's own judging turn).
