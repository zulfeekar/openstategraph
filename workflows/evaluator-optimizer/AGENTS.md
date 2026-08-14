# Evaluator Optimizer

Gallery example 4 of twenty — the **revision loop**, and the gallery's
reference for the sentence *a loop is two edges*.

| Node | One line |
| --- | --- |
| `in1` **Request** | where the request enters |
| `draft1` **Draft** | writes the release note; treats any feedback as the spec |
| `grader1` **Review** | passes it on, or sends it back with a reason |
| `out1` **Release note** | renders whatever passed |

## The two edges

```
draft1 ──result──▶ grader1 ──pass───▶ out1
   ▲                   │
   └────── feedback ───┘ revise
```

`grader1.pass → out1.result` is the exit. `grader1.revise → draft1.feedback`
is the loop — and it is the *only* kind of edge that can be one. The `acyclic`
connection rule returns early for exactly one condition: the source port's type
is `feedback`. `route.grader.revise` and `human.approval.rejected` are the only
two ports in the whole catalogue that emit it; `agent.feedback` and
`orchestrate.supervisor.feedback` are the only two that receive it. An
accidental cycle stays inexpressible; the evaluator-optimizer pattern is two
clicks.

A cycle also needs a **conditional** edge or it can never terminate. The grader
is it: the node decides, the edge dispatches.

## Two budgets, and they are not the same number

- **`maxAttempts: 2`** on the grader is the *revision* budget — how many times
  this loop may go round. When it runs out the last candidate ships anyway;
  the run completes rather than raising. Gallery example 7 is the one that
  demonstrates exhausting it.
- **`recursion_limit`** is the *superstep* budget, graph-wide, defaulting to 50.
  One lap is not one superstep, and with fan-out a lap can cost several. Never
  call it "max iterations".

## Rules are the author's; the contract is not

`rulesMode: "extend"`. The grader's preamble and its verdict output contract are
the base's and are not editable; `criteria` is the author's layer, and it is
composed *before* the contract so it can shape the decision without
countermanding the shape of the answer. `rulesMode: "replace"` drops the
default rules layer — on a grader that is how a rubric quietly loses the verdict
format it is parsed by.

## Smoke run

```
openstategraph run workflows/evaluator-optimizer \
  "Write a two-sentence release note for a bug fix."
```

Recorded 2026-08-14 on `ollama:gpt-oss:120b-cloud`, ~9s:

> The application crashed when users attempted to upload a profile picture. It
> now uploads profile pictures correctly without errors.

Two sentences; defect first, fixed behaviour second; no marketing language.
`decisions` is `{"grader1": "pass"}` — the grader's final verdict — and
`attempts` is 1: the first draft satisfied the rubric, so the `revise` edge was
never taken. The loop being *available* and not *needed* is a pass, not a
missing demonstration.
