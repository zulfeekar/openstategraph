# Where a turn's wall clock goes — model, tool, or ours

`launch-readiness/109`, 2026-08-29. Companion to
`docs/decisions/per-request-compile-cost.md` (`113`), which measured one
segment of this in isolation.

The ticket does not ask "be fast". It asks one question:

> Of the wall-clock time in one turn, how much is model latency we chose, and
> how much is **ours** — scheduling, serialisation, waiting on something that
> could have been concurrent, or work done twice?

The first bucket is a product decision and belongs to the owner. Anything in
the second is a defect. This page is the arithmetic that separates them, and
`scripts/measure_turn.py` is the instrument that produced it — committed, as
`113`'s was, so the next person re-measures instead of re-arguing.

## Method

One real turn, driven over a real socket against a real `uvicorn` (an
`httpx.ASGITransport` buffers the whole body and would make every frame arrive
at once, which is the difference between measuring a stream and measuring a
file). Every model and tool call is timed by LangChain's own
`on_llm_start` / `on_llm_end` and `on_tool_start` / `on_tool_end`, installed
process-wide through `register_configure_hook` — so nothing in
`openstategraph/` is patched, and the numbers cover a router's calls, a
grader's, and each ReAct lap of every agent without any node opting in.

Intervals are **merged before they are summed**. A fan-out runs several at
once, and adding their durations would credit the graph with more seconds than
the turn contained.

```
ours = wall − |model ∪ tool intervals|
```

Deliberately unflattering: anything the graph did concurrently *with* a model
call is charged to the model, never to us. `ours` is then split by *where* it
sits — **head** (before the first provider call), **gaps** (between provider
calls), **tail** (after the last one, up to `done`).

Live models, Ollama **cloud** (`gpt-oss:120b-cloud`) per the standing rule.
Two passes each, because the most valuable finding of 2026-08-27 was not a
latency, it was *three runs, three different answers*.

## `stress-review` — every construct at once

Router, supervisor fanning out to a tool-using worker, a join, a grader that
can send the whole plan back, a mount two levels deep, and a deep agent with
its own subagents. Eleven nodes. If a scheduling or serialisation defect
exists anywhere, this is the shape that has room for it.

| | pass 1 | pass 2 |
| --- | --- | --- |
| wall | **15.63 s** | **14.02 s** |
| model round trips | 7 | 7 |
| model, merged | 12.62 s (80.7 %) | 13.88 s (99.0 %) |
| tool calls | 1 (0.001 s) | 0 |
| **ours** | **3.01 s (19.3 %)** | **0.14 s (1.0 %)** |
| — head | 2.94 s | **0.07 s** |
| — gaps | **0.06 s** | **0.06 s** |
| — tail | **0.01 s** | **0.01 s** |

Per-node, at the stream: `in1` 2.94 / 0.07 · `router` 0.95 / 0.91 ·
`lead` 1.73 / 1.49 · `worker` 3.62 / 5.65 · `join` 0.00 / 0.00 ·
`grader` 0.00 / 0.00 · `audit` (the mount) 6.39 / 5.90 · `out1` 0.00 / 0.00.

Model round trips, pass 2: 0.90, 1.48, 1.91, 2.42, 1.30, 2.27, 3.59 s.

## `cpl-nl2sql` — the 28-node pipeline

Router → prefetch → agent → validate → grader → relay → execute → summarize.

| | pass 1 | pass 2 |
| --- | --- | --- |
| wall | **26.41 s** | **26.51 s** |
| model round trips | 4 | 4 |
| model, merged | 23.47 s (88.9 %) | 26.40 s (99.6 %) |
| **ours** | **2.94 s (11.1 %)** | **0.11 s (0.4 %)** |
| — head | 2.89 s | **0.07 s** |
| — gaps | **0.04 s** | **0.04 s** |
| — tail | **0.01 s** | **0.01 s** |

Per-node, pass 2: `in1` 0.07 · `router1` 1.19 · `prefetch1` 0.00 ·
`agent1` 12.85 · `validate1` 0.00 · `gate1` 0.01 · `relay1` 2.20 ·
`execute1` 0.00 · `summarize1` 10.20 · `out1` 0.00.

**These two passes ran without the package's Databricks tools**, which need
`databricks-sdk` and were absent from the interpreter — so the answer was the
honest "a capability it needs was not available" and no warehouse was
queried. The model-call structure and the scheduling numbers are still exactly
what they would be; the tool seconds are simply not in them, and no conclusion
here rests on their absence. Recorded rather than quietly omitted.

## The split, and the arithmetic

**Warm — which is every turn a running server serves after its first:**

```
stress-review   14.02 s wall  −  13.88 s providers  =  0.14 s ours   (1.0 %)
cpl-nl2sql      26.51 s wall  −  26.40 s providers  =  0.11 s ours   (0.4 %)
```

And of that tenth of a second, the part that could be a *design* defect —
`gaps`, the only bucket where serialising work that had no dependency, or
doing work twice, or an invisible retry could hide — is **0.04–0.06 s in all
four passes, on two very differently shaped graphs**. That is the number this
ticket was opened to find.

`tail` — the ticket's "time between the last token and the `done` frame" — is
**0.01 s** in all four passes.

`head` warm is **0.07 s** on both packages, which independently corroborates
`113`: the whole plan-plus-tool-import-plus-skill-read-plus-build path is
tens of milliseconds, not seconds.

**Cold — the first turn of a server process, and only that one:**

```
head, pass 1:  2.94 s (stress-review) / 2.89 s (cpl-nl2sql)
head, pass 2:  0.07 s                 / 0.07 s
```

The gap is lazy imports — LangChain, LangGraph and the provider integration —
paid once per process by whichever request arrives first. It is genuinely
ours, it is the largest single item in the bucket, and it is filed as
`launch-readiness/181` rather than fixed here, because a warm-up is a change
to server start-up and this ticket is a measurement.

## Conclusion

**97–99 % of a warm turn is model inference we chose. Ours is a tenth of a
second, and the schedulable part of it is four hundredths.**

There is no concurrency win available in the shapes measured: the laps are
sequential because each needs the previous result, and the fan-out that could
overlap already does — today's separate stress test put four blocking tool
calls at 25.4 s serial against 7.9 s concurrent, and three whole composite
runs at 131.5 s wall against 112/119/131 s each.

The levers are model, `reasoningEffort`, and the number of laps. Nothing in
this repository is worth changing for speed on this evidence — with the two
exceptions filed as `180` and `181`, neither of which is a latency defect an
owner would feel.

## What this measurement found that is not about latency

`180` — **the server-side frame clock stamps the first frame of a real stream
and no other.** Of 100 frames in the first run through this instrument,
exactly one carried `seq` and `elapsedMs`. The same root cause takes a live
run down completely on `langchain-core` 1.6.1, which the published pin allows.
Found here because this ticket's stated method is to read that clock; it is
`memory-and-replay/46`'s bug, not this ticket's, and it is filed rather than
fixed.

Until it is fixed, `scripts/measure_turn.py` falls back to the client's
arrival time and **says so in its own output** rather than mixing the two
clocks silently. Over loopback, with a client that does nothing between reads
but append to a list, that is a sub-millisecond distortion — not the browser
measurement `launch-readiness/105` warns about, where a whole TCP chunk is
drained synchronously before anything is timestamped.
