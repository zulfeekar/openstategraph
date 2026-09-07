# Two Stage Double Loop

Gallery example 6 of twenty — **two independent revision cycles in series**,
each with its own rubric.

| Node | One line |
| --- | --- |
| `in1` **Request** | where the change description enters |
| `draft1` **Changelog** | writes the engineer-facing line |
| `grader1` **Accuracy review** | passes it on, or sends it back |
| `polish1` **Customer rewrite** | turns that line into two customer sentences |
| `grader2` **Readability review** | passes it on, or sends it back |
| `out1` **Release note** | renders whatever passed the *second* rubric |

```
in1 ─▶ draft1 ──▶ grader1 ──pass──▶ polish1 ──▶ grader2 ──pass──▶ out1
        ▲            │                 ▲            │
        └── feedback ┘ revise          └─ feedback ─┘ revise
```

## Why serial, and not parallel

`agent.feedback` is `maxConnections: 1`. Two `revise` edges onto one agent do
not stack — the capacity rule *swaps* the existing edge for the new one — so
two rubrics over one drafter is not a drawable shape. Two graders means two
drafters, in series. That is not a workaround; it is the honest form of "these
are two different judgements about two different artefacts".

## Two graders, two budgets

Both cards say `3`, and both mean it: `maxAttempts` is **this grader's own**
budget, counted per grader by the grader itself (`RunState.revisions`, keyed by
node id). Stage two starts with three looks however hard stage one worked.

It has not always been so, and this package is where it was found. Until gallery
ticket 21 the check was against `attempts` — one graph-wide `int` that every
model-driven node increments once per invocation — so these were two ceilings on
one shared count, the second grader's real budget was `maxAttempts` minus
everything stage one had already spent, and the natural `2` on both cards gave
`grader2` **zero** revisions: it force-passed the first draft it ever saw,
silently, against a card promising two attempts. `grader1: 3` and `grader2: 6`
was the arithmetic that bought each stage three looks. Now `3` and `3` buy the
same three looks each and say so.

## Smoke run

```
# it ships in the wheel; copy it into ./workflows once, then run it
openstategraph examples copy two-stage-double-loop
openstategraph run workflows/two-stage-double-loop \
  "Draft a changelog entry, then make it customer-readable. The change: the export button silently produced an empty CSV when a filter matched no rows."
```

Recorded 2026-08-15 on `ollama:gpt-oss:120b-cloud`, ~26s, `attempts: 4`:

> When you try to export data and the selected filter returns no rows, you'll
> now see a clear notice instead of receiving an empty CSV file. No action is
> required on your part.

Two sentences, no component name, no "bug", second sentence tells the reader
they need do nothing. `decisions` is `{"grader1": "pass", "grader2": "pass"}`.

**Both loops ran, once each** — and `RunResult` cannot show you that. The
checkpoint recording can:

```
openstategraph threads show <thread-id> --workflow two-stage-double-loop
```

```
attempts 1  grader1 revise  "Provide exactly one line starting with '- ' in past tense;
                             remove the extra customer-readable sentence."
attempts 2  grader1 pass
attempts 3  grader2 revise  "Reduce the answer to exactly two sentences."
attempts 4  grader2 pass
```

`attempts` is still what it always was — a true count of model-node
invocations across the whole run, which is why it reaches 4 for two laps in two
stages. What each grader spent of *its own* budget is `RunState.revisions`, keyed by
grader node id — run state the checkpointer records, deliberately not a
`RunResult` field, because `attempts` is a cost and a budget is not something a
caller should gate on.

`outputs` and `decisions` are keyed by node id and merged, so each holds only
the *last* value that node produced. The per-lap history lives in the
checkpointer, and `threads show` is a recording — it re-runs nothing and calls
no model.
