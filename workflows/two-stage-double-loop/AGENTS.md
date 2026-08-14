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

## Two graders, one counter

**`maxAttempts` is not a per-loop revision budget.** `attempts` is a single
`int` on the run state (`RunState.attempts`, reducer `MAX`) and *every*
model-driven node increments it once per invocation. A grader's check is
`state["attempts"] >= maxAttempts`, so:

- the two numbers on these two cards are **two ceilings on one shared count**,
  not two budgets;
- the second grader's real revision budget is `maxAttempts` minus everything
  the first stage already spent;
- setting both to the natural `2` would give stage two **zero** revisions —
  the first stage alone reaches 2, so `grader2` force-passes the first draft it
  ever sees, silently.

Hence `grader1: 3` and `grader2: 6` here. Gallery ticket 21 is the fix.

## Smoke run

```
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

`outputs` and `decisions` are keyed by node id and merged, so each holds only
the *last* value that node produced. The per-lap history lives in the
checkpointer, and `threads show` is a recording — it re-runs nothing and calls
no model.
