# Budget Exhaustion

Gallery example 7 of twenty — **the only example whose grader never passes**.
It exists to show that a loop which cannot succeed still *finishes*.

| Node | One line |
| --- | --- |
| `in1` **Question** | where the question enters |
| `draft1` **Answer** | answers in exactly seven words |
| `grader1` **Impossible rubric** | demands seven words *and* forty words of reasoning |
| `out1` **Last candidate** | renders whatever the loop had when it ran out |

The rubric is self-contradictory on purpose. No candidate can satisfy it, so
the exit is never the grader's verdict — it is the attempt counter.

## How it stops

`_grader` checks the budget **before** it routes:

```python
exhausted = state.get("attempts", 0) >= cap
branch = "pass" if verdict.passed or exhausted else "revise"
```

So at the cap the grader forces `pass` and the last candidate ships. The run
completes normally. **No `GraphRecursionError`** — that exception belongs to the
*superstep* budget (`recursion_limit`, default 50), which this loop never
approaches: two laps here cost four supersteps.

Revisions are not supersteps. This example is where the difference is cheap to
see; example 9 is where it bites.

## `maxAttempts: 2`, not the catalogue's 1

The catalogue row specifies `maxAttempts: 1`. At 1 the grader force-passes the
*first* draft, so the `revise` edge is drawn and never traversed — an example of
a loop that never loops. At 2 the edge is taken exactly once and the run still
ends with `attempts == maxAttempts`, which is the property the row is actually
asserting. Deliberate deviation, recorded here and in the ticket resolution.

## What the run does *not* tell you

`decisions` reads `{"grader1": "pass"}` and `warnings` is empty — a forced pass
is indistinguishable from a real one in `RunResult`. The catalogue expected "a
warning-shaped record that the grader never passed"; there is none. Gallery
ticket 22.

The only trace left in the result is the stale `feedback` string, and only
because `LATEST_NONEMPTY` refuses to overwrite it with the `""` a pass writes.
That is an accident, not a report.

## Smoke run

```
# it ships in the wheel; copy it into ./workflows once, then run it
openstategraph examples copy budget-exhaustion
openstategraph run workflows/budget-exhaustion \
  "Answer in exactly seven words: why is version control useful?"
```

Recorded 2026-08-15 on `ollama:gpt-oss:120b-cloud`, ~15s, `attempts: 2`:

> Tracks changes, enables collaboration, prevents data loss.

Seven words. The grader's rejection on lap one was *"Add a reasoning
explanation of at least forty words."* — which cannot be done in seven words,
which is the point. Lap two produced the shipped answer and the counter ran out.
