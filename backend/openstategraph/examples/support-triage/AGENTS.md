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

### 1. The grader sends it back — through the router

`agent.feedback` is `maxConnections: 1`. Three desk agents, one grader, and a
`revise` edge landing on a desk directly would have to pick **one** of them —
so a technical failure could be redrafted by the billing desk. Until
`workflow-gallery` 48 there was no fan-out feedback port and no
router-with-a-feedback-input, so the loop was undrawable and `grader1` shipped
`pass` only, advisory: recorded in `decisions`, with the draft going to the
person either way regardless of the verdict.

**That has changed.** The router gained a `feedback` input, and the decision
(`docs/decisions/router-feedback-input.md`) was "feedback follows the branch":
`grader1.revise` now lands on `router1.feedback`, never on a desk. `router1`
does not reclassify on that edge — it re-dispatches to whichever branch its
own last decision named, so the correction always reaches the desk that
actually wrote the rejected draft, never an arbitrary one and never the wrong
one. The desk's own `feedback` port then receives the grader's rejection text
through the same trust rule every feedback-consuming node already applies
(only a source whose revise edge reaches it, directly or via this relay, and
whose latest decision still stands) — no new plumbing on the desk side.

`grader1` now has both `pass` and `revise` wired
(`plan.conditional["grader1"] == {"pass": "gate1", "revise": "router1"}`), so
`_router_for`'s missing-destination fallback no longer applies to this
grader's verdict — `Finding.UNWIRED_REVISE` does not fire for it. That
fallback is still real and still worth knowing (gallery ticket 31; the
fallback itself, and the general hazard of an unwired `revise`, are unchanged
by this ticket):

```python
default = next(iter(destinations))     # falls back to the first destination
return chosen if chosen in destinations else default
```

`tests/` pins the new shape: the revise edge names `router1.feedback`, and no
desk carries a direct `feedback` edge — the correction reaches a desk by
re-dispatch, never by choosing one desk to wire to. The re-dispatch mechanism
itself — replay instead of reclassify, and the widened feedback-trust check —
is pinned once, generically, in
`backend/tests/test_a_router_re_dispatches_a_revision.py`, against a minimal
two-branch document driven through a real compiled graph.

The two copies now carry the same ten nodes. Until `launch-readiness` 122 the
dev workspace copy carried three more — `tool.email-send` bound to
`a-account` — and `workflow-gallery` 78 recorded that difference as
deliberate-and-unsynced while declining to decide it either way. It is decided:
they were an authoring accident, and they are gone.

The argument, because a deletion should say why it was safe. All three had an
empty recipient; all three sat on `a-account` alone, while `a-billing` and
`a-technical` answer the same kind of ticket with no send at all; their ids
were the editor's own drag-minted `node:tool.email-send-1/2/3` where every
other node here is named by hand; and `gate1.approved` goes to an
`output.formatted`, so nothing on the approved path ever sent anything. What
they did do was sit **above** the gate, inside the revision cycle, in a
document whose entire promise is that nothing reaches a customer without a
person saying so — which is what `121`'s two findings said, correctly, on every
compile.

**Nothing in this example sends mail, and that is the design**, not a
limitation of a packaged copy. Adding a send means adding it *below* `gate1`,
on its own node, outside the cycle, with `maxRetries` set to 1 — otherwise
`REPEATED_SIDE_EFFECT` fires again and will be right to.

### 2. The person at the gate is told what the machine thought

The interrupt payload used to be `{message, candidate}` — the gate's own field,
and the text — so `grader1` judged that text against five criteria, wrote a
reason, and none of it reached the person deciding. Gallery ticket 32 closed
that: the frame now carries `verdict` and `reason` when a grader produced the
candidate, which here it always does, because `gate1`'s only way in is
`grader1`'s `pass` branch.

Three things it deliberately does **not** do:

- **It does not report the branch.** `decisions["grader1"]` is `pass` for an
  answer the grader rejected once the attempt cap is reached; the frame says
  `revise` in that case, because what a reviewer needs is the judgement, not
  the route.
- **It does not walk further back.** The grader reported is the candidate's
  *immediate* producer. A judgement of some earlier text captioning this text
  would be a confident wrong statement rather than a missing one.
- **It does not grow.** The verdict and its reason, and nothing else. The
  payload's small size is a feature — a gate is not a trace viewer, and a
  mount's isolation rule still applies.

That is why the grader's rubric ends with *"Your verdict is read by the person
deciding whether to send it"* — a sentence that is now true.

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
gate, that the grader's `revise` edge lands on the router's `feedback` port
rather than on any desk, and that the rejected sink is an agent reached by a
`feedback` edge. No model is called.
