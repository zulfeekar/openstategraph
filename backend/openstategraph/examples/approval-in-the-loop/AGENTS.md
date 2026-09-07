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

## Smoke run

It ships in the wheel rather than in this project's `workflows/`, so take a
copy first — `openstategraph examples copy approval-in-the-loop` — and everything below
runs against `workflows/approval-in-the-loop`.

Two commands, the same `openstategraph run` every other package in the gallery
documents plus the verb that finishes it (`workflow-gallery` 24). The run stops
at the gate and says so on stderr, exiting **1** — it has not failed and has
not answered, it is waiting:

```
$ openstategraph run workflows/approval-in-the-loop \
    "Draft a one-line apology to a customer whose order was late." \
    --thread-id smoke-approval-1
paused: This message goes to a customer under your name. Approve to send it, or reject with a note saying what to change.
  candidate: We're sorry your order arrived late and we're taking steps to improve our delivery speed.
  thread: smoke-approval-1
  finish it: openstategraph resume workflows/approval-in-the-loop smoke-approval-1 --approve | --reject --feedback '…'
```

Reject it, and the drafter treats the note as the specification and stops at
the same gate again:

```
$ openstategraph resume workflows/approval-in-the-loop smoke-approval-1 --reject \
    --feedback "Too formal, and it does not say when the order will arrive. One sentence, warmer, and name the next step."
```

> We're sorry your order arrived late; it's now set to arrive by [date] and
> we'll send you a tracking update shortly.

Approve it, and the run finishes with `decisions: {"gate1": "approved"}` and
that message as the answer:

```
$ openstategraph resume workflows/approval-in-the-loop smoke-approval-1 --approve
```

There is no `edit` outcome — a person may approve or reject with words, never
hand back corrected text. That is organisms-first-class 27. `--feedback` on an
approval is refused (exit **2**) rather than dropped, and a thread that is not
stored, is not paused, or belongs to another package is refused with a sentence
and exit **1**.

**Provenance, because the two halves were measured on different days.** The
model's drafts above are the transcript recorded 2026-08-15 against a local
`openstategraph serve` on `ollama:gpt-oss:120b-cloud`, thread
`smoke-approval-1`. The CLI commands and their exit codes were verified on
2026-08-22 in an environment with no provider credential, against a gate
reached without a model — so the pause, both decisions and all four refusals
are measured, and the drafter's wording is quoted from the earlier run rather
than re-run.

## The API is the second way, and it is what the editor uses

```
$ POST /api/runs   → 409
This workflow paused for a human decision, which this endpoint cannot carry.
Run it through POST /api/runs/stream, which reports the pause and resumes
through POST /api/runs/resume. Thread: smoke-approval-blocking-2
```

`POST /api/runs/stream` reports the pause as a frame, and the payload is the
same `{message, candidate}` the CLI prints — the node's own field and the text
a person is being asked to stand behind:

```json
event: interrupt
{"threadId": "smoke-approval-1", "node": "gate1",
 "message": "This message goes to a customer under your name. Approve to send it, or reject with a note saying what to change.",
 "candidate": "We're sorry your order arrived late and we're taking steps to improve our delivery speed."}
```

`POST /api/runs/resume` then carries `{"decision": "reject", "feedback": "…"}`
and `{"decision": "approve"}`, which is exactly what `--reject --feedback` and
`--approve` send. Nothing is sent to the customer until a person has decided.

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
