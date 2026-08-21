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

## What the run tells you, and what it cannot

`decisions` reads `{"grader1": "pass"}`, because it must: the compiler dispatches
on that exact label and `plan.conditional[grader1]` has the keys `pass` and
`revise` and no third one. So the branch is not where the distinction lives.

It lives beside it. The forced pass writes its own state key, and the run
reports itself on every door — `RunResult.warnings`, both HTTP doors, and the
CLI's stderr:

```
warning: Grader "grader1" ran out of attempts and published an answer it had
rejected. Its last reason: Add a reasoning explanation of at least forty words.
```

**It is a report, not a failure.** `RunResult.failures` stays empty and
`openstategraph run` still exits 0 — the workflow answered. And the sentence
says the grader never satisfied its rubric, which is a weaker claim than the
answer being wrong.

**`attempts` alone could never have carried this**, which is why the counter was
not the answer. `RunResult` publishes no `maxAttempts` to compare it against;
and even holding this document, a grader that *genuinely* passes on lap two —
the last lap this budget allows — ends with `attempts: 2` and
`decisions: {"grader1": "pass"}`, identical to the exhausted run in every field.
Only the warning tells them apart, and a genuine last-lap pass writes none.

The stale `feedback` string is still in the result, and is still an accident:
`LATEST_NONEMPTY` refuses to overwrite it with the `""` a pass writes, so a
genuine pass on lap two would leave lap one's feedback there just the same.
Read the warning, never that.

## Where this example is asserted

The document properties that make exhaustion inevitable are pinned in
`tests/` here. The *run* is pinned in the backend suite, at
`backend/tests/test_an_exhausted_grader_is_not_a_pass.py`, which compiles this
package with a scripted grader and reads `RunResult` — a package's own `tests/`
asserts the document and calls no model, deliberately, so the end-to-end
assertion belongs in the only suite that may drive a graph. Gallery ticket 22.

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
