# Approval In The Loop

Gallery example 10 of twenty — the only cycle **a person** closes, and the only
example that interrupts mid-run.

| Node | One line |
| --- | --- |
| `in1` **Request** | where the request enters |
| `draft1` **Draft** | writes the customer message; treats a rejection as the spec |
| `gate1` **Send it?** | pauses the run and waits for a person |
| `out1` **Approved message** | renders only what a person approved |

```
in1 ─▶ draft1 ──▶ gate1 ──approved──▶ out1
        ▲            │
        └── feedback ┘ rejected
```

## A rejection is the same kind of edge a grader's revise is

`human.approval.rejected` is typed `feedback`, and `route.grader.revise` is
typed `feedback`. Those two are the only feedback *outputs* in the catalogue;
`agent.feedback` and `orchestrate.supervisor.feedback` are the only feedback
*inputs*. So swapping the gate here for a grader would change one node and no
edges — the ports do not know, and do not need to know, that this verdict came
from a human. That symmetry is the example's claim.

## How to run it: not from the CLI

`openstategraph run` calls `workflow.ask(...)`, which has no resume flag, so the
CLI can observe the *pause* and nothing after it. The blocking API endpoint is
honest about the same limit:

```
$ POST /api/runs   → 409
This workflow paused for a human decision, which this endpoint cannot carry.
Run it through POST /api/runs/stream, which reports the pause and resumes
through POST /api/runs/resume. Thread: smoke-approval-blocking-2
```

The full cycle is `POST /api/runs/stream` → `POST /api/runs/resume`, twice.
Gallery ticket 24 asks for a CLI equivalent.

## Smoke run

Recorded 2026-08-15 against a local `openstategraph serve` on
`ollama:gpt-oss:120b-cloud`, thread `smoke-approval-1`, question *"Draft a
one-line apology to a customer whose order was late."*

**1 — `POST /api/runs/stream`.** The run pauses, and the pause is a frame:

```json
event: interrupt
{"threadId": "smoke-approval-1", "node": "gate1",
 "message": "This message goes to a customer under your name. Approve to send it, or reject with a note saying what to change.",
 "candidate": "We're sorry your order arrived late and we're taking steps to improve our delivery speed."}
```

The payload is `{message, candidate}` — the node's own field and the text a
person is being asked to stand behind. Nothing has been sent.

**2 — `POST /api/runs/resume`, `{"decision": "reject", "feedback": "Too formal,
and it does not say when the order will arrive. One sentence, warmer, and name
the next step."}`.** The drafter redrafts and the run pauses again:

> We're sorry your order arrived late; it's now set to arrive by [date] and
> we'll send you a tracking update shortly.

**3 — `POST /api/runs/resume`, `{"decision": "approve"}`.** `done`, with
`decisions: {"gate1": "approved"}` and that message as the answer.

There is no `edit` outcome — a person may approve or reject with words, never
hand back corrected text. That is organisms-first-class 27.

## The terminal frame of a resumed run under-reports

The `done` frame above carried `attempts: 0` and an `outputs` map holding only
`gate1` and `out1`. The checkpointer, asked the same question, says `attempts:
2` and holds every node's output:

```
openstategraph threads show smoke-approval-1 --workflows-root workflows
```

The resumed stream accumulates its terminal frame from the frames of *that
segment*, so everything before the pause is missing from it. Gallery ticket 25.

## It resists both fixture formats, and the reason is the interrupt

`tests/` here asserts the **document** — the cycle, the ports, the pin — the
same as every other package, through `openstategraph.package_testing`. What it
does not do, and must not, is assert the **answer**.

This example has no answer until a person supplies one. The run pauses at
`human.approval` and what ships depends on what the reviewer typed, so an
`evals/*.eval.json` has nothing to hold a reference output *of* — the gold
column would be a decision, not a result — and a shape assertion over a
completed run would have to script the person first, at which point it grades
the script. Both formats measure the stub.

The approve and reject paths are therefore driven through the HTTP API by hand
and **recorded in the smoke run above**, which is the honest place for a fact
that needs a human in it. See `docs/evaluation.md` §"Grading during a run vs
grading a dataset" for why that is a third category rather than a gap.
