# Support Triage

Gallery example 19 of twenty — **the long control chain**. Every control
molecule the vocabulary has, in one graph: classify the ticket, answer it on
the matching desk, grade the reply, and let a person decide whether it is sent.

| Node | One line |
| --- | --- |
| `in1` **Ticket** | the customer's message |
| `router1` **Which desk** | three exclusive branches — billing, technical, account |
| `a-billing` / `a-technical` / `a-account` | one reply-writing agent per desk |
| `grader1` **Is this sendable** | judges the draft against a sendability rubric |
| `gate1` **Send to the customer?** | pauses the run; a person approves or rejects |
| `out-sent` **Approved reply** | the reply, once someone stood behind it |
| `hold1` **Held ticket note** | turns a rejection into an internal record |
| `out-held` **Held for review** | that record |

Two exits, because "sent" and "held" are different outcomes and a run should
end at the one that happened.

## The two things the long chain reveals

Both are about what the current vocabulary cannot express, and both are the
reason this document is shaped as it is.

### 1. The grader cannot send it back

`agent.feedback` is `maxConnections: 1`. Three desk agents, one grader, and a
`revise` edge would have to pick **one** of them — so a technical failure would
be redrafted by the billing desk. There is no fan-out feedback port and no
router-with-a-feedback-input, so the loop is not merely awkward here, it is
undrawable.

So `grader1` has a `pass` edge and nothing else, and its verdict is *advisory*:
it is recorded in `decisions` and the draft goes to the person either way. That
works because `_router_for` falls back to the first declared destination when
the recorded decision names no wired branch:

```python
default = next(iter(destinations))     # {"pass": "gate1"}
return chosen if chosen in destinations else default
```

Benign here, and even wanted. **Not benign in general** — the same fallback
means any grader with an unwired `revise` edge ships an answer its own rubric
rejected, with no warning at compile time. Gallery ticket 31; `tests/` pins the
behaviour in both directions.

### 2. The person is not told what the machine thought

The interrupt payload is `{message, candidate}` — the gate's own field, and the
text. `grader1` has just judged that text against five criteria and written a
reason, and **none of it reaches the interrupt**. The reviewer is asked to
stand behind a draft while the one existing machine opinion of it is left in
state. Gallery ticket 32.

That is why the grader's rubric ends with *"Your verdict is read by the person
deciding whether to send it"* — a sentence that is, today, aspirational.

### 3. The rejected sink cannot be an output

`human.approval.rejected` is a **`feedback`** output; `output.formatted.result`
accepts `result`/`text`. So a rejection cannot flow into an output node at all.
The shape that works is `hold1` — an agent whose only incoming edge is the
rejection. With no `prompt` edge it answers the original question, and with the
reviewer's note as its feedback, so what it writes is precisely an internal
record of what the ticket was and why the draft was refused. Then *that*
reaches an output.

## Smoke runs

It ships in the wheel rather than in this project's `workflows/`, so take a
copy first — `openstategraph examples copy support-triage` — and everything below
runs against `workflows/support-triage`.

The catalogue's Boundaries say to drive an approval through the API, and this
is batch B's procedure exactly.

**`openstategraph run` shows the pause and stops** — recorded 2026-08-15 on
`ollama:gpt-oss:120b-cloud`, question *"My invoice is wrong and nobody has
replied for a week."*:

```json
{"answer": "I'm sorry the invoice was incorrect and you haven't received a reply. …",
 "decisions": {"router1": "b-billing", "grader1": "pass"},
 "attempts": 1}
```

`outputs` holds `in1`, `router1`, `a-billing`, `grader1` and stops there — the
other two desks never ran, and nothing reached an output. **Routed to billing,
graded, then paused, which is the catalogue's expected shape.**

**`POST /api/runs` refuses, in words:**

```
409 This workflow paused for a human decision, which this endpoint cannot
    carry. Run it through POST /api/runs/stream, which reports the pause and
    resumes through POST /api/runs/resume. Thread: smoke-triage-1
```

**`POST /api/runs/stream`** pauses with the interrupt frame:

```json
event: interrupt
{"threadId": "smoke-triage-2", "node": "gate1",
 "message": "This reply goes to a customer under your name. …",
 "candidate": "I'm sorry your invoice contains an error. I'll review the invoice
   details and issue a corrected version or a refund if appropriate. …"}
```

**`POST /api/runs/resume`, `{"decision": "reject", "feedback": "It does not
acknowledge that we left them waiting a week. Say that, and drop the 'if
appropriate' hedge."}`** — the held-ticket note, and no reply to anyone:

> The ticket concerns a customer's claim that their invoice is incorrect and
> they have not received a response for a week. The draft was rejected because
> it did not acknowledge the week-long wait and included an "if appropriate"
> hedge.

`decisions {"gate1": "rejected"}`, `outputs` `gate1` → `hold1` → `out-held`.

**`POST /api/runs/resume`, `{"decision": "approve"}`** on a fresh thread ships
the draft to `out-sent`, `decisions {"gate1": "approved"}`.

**Matches the catalogue** — routed to billing, graded, paused for approval,
nothing sent without the gate.

### Re-confirmed live: the resumed run under-reports

Both resume frames dropped what happened before the pause. `decisions` came
back as `{"gate1": "rejected"}` alone — `router1` and `grader1` gone — and the
approve frame reported `attempts: 0` after an `attempts: 1` first half. That is
gallery ticket 25, seen again on a different graph; not re-filed.

## Where this stops, deliberately

There is no peer-to-peer handoff. A router picks a desk and the desk answers;
one desk cannot hand a live conversation to another. That is the catalogue's
substitution 4 and it belongs to organisms-first-class 18. The `edit` outcome a
reviewer obviously wants — hand back corrected text rather than a note — does
not exist either: organisms-first-class 27.

## Tests

`tests/` asserts the four molecules are present, the three branches are
exclusive, both exits exist, that no desk reaches an output without passing the
gate, that the grader has only a `pass` edge and what a `revise` verdict then
does, and that the rejected sink is an agent reached by a `feedback` edge. No
model is called.
