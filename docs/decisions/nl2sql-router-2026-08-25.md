# NL2SQL router in front of cpl-nl2sql (launch-readiness/12)

`~/osg-demo/workflows/cpl-nl2sql/` gained a `route.classifier` (`router1`)
between `in1` and the existing SQL pipeline, so greetings and off-topic
messages stop paying the ~40s SQL path.

## Graph

```
in1 → router1 ─┬─ data_query → prefetch1 → (existing pipeline unchanged) → out1
               ├─ followup   → prefetch1 (same entry point as data_query)
               ├─ greeting   → greet1   → out1
               └─ offtopic   → decline1 → out1
```

`router1` is `route.classifier` on `openai/gpt-5-mini`, `reasoningEffort: low`,
`matchMode: best`, `fallback: data_query`. `greet1`/`decline1` are `agent.llm`,
low effort, no tools wired, small `tokenBudget` (300).

## "Unsure → data_query"

The owner's rule was written directly into `router1.rules`: the branch
descriptions state the default is `data_query`, and a closing paragraph says
explicitly that an ambiguous or borderline question about ports, cargo,
prices, vessels, volumes, dates or comparisons is **always** `data_query`,
never `greeting`/`offtopic`, even when short or vague — because the costs are
asymmetric (a wrongly-routed data question costs ~40s; a wrongly-routed
greeting costs a useless reply). The `fallback` field is also set to
`data_query` as a second enforcement layer.

## `followup`

Wired to the same `prefetch1` entry point as `data_query` — this worked
cleanly on the first try and needed no extra plumbing: `agent1` already reads
the thread's message history via the checkpointer (`thread_id`), so "and for
June?" against a thread that had just asked about July resolved to the right
month without any deliberate SQL-carrying step. No fallback was needed.

## Live test results

| # | Input | Branch | Seconds |
|---|---|---|---|
| 1 | "hello" | greeting | 3s |
| 2 | "what's the weather in Oslo?" | offtopic | 4s |
| 3 | "Which countries received the most fuel oil imports by volume in July 2026?" | data_query | 47s |
| 4 | "and for June?" (same thread) | followup | 32s |
| 5 | "hi, can you check crude flows from Saudi to Europe?" | data_query | 51s |
| 6 | Fujairah dwell-time control | data_query | 28s |

Warehouse (`execute1`) calls: 4, within the 6-call cap.

Note on test 6: the answer (39.67h) fell outside the expected 14.3-23.9h /
mean ~18.4h control range. This is the pre-existing schema/bounding-box
accuracy issue tracked separately (see the Equinor CPL ground-truth note) —
`agent1`, `prefetch1` and every downstream data_query node were left
byte-identical by this change; the router only forwards the question
unmodified to the same entry point. Not a regression introduced by the
router, but flagged rather than silently accepted.

Editor validation: `port_specs.json`'s `route.classifier` entry was read
before wiring (dynamic `branch:<id>` output ports, `question` input port,
`fallback`/`matchMode`/`rules` fields) rather than guessed. The Python
compiler does not enforce port `max_connections` — it is an editor/canvas
concern — so three static edges into `out1.result` (from `summarize1`,
`greet1`, `decline1`, mutually exclusive per run) compiled and ran cleanly.
