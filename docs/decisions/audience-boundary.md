# A run carries its audience

*Ticket 13, one-chinook-honest. Status: decided and built.*

## The rule

The owner's, verbatim: *"the suggestion of tool or methods should only be
visible to workflow edit users, not customer facing."* Asked how hard the
boundary should be, they chose **enforcement at the runtime seam** over
leaving it a frontend convention.

## What was actually there

The convention, and only the convention. `parseSuggestion` and
`CapabilitySuggestion` lived in `src/view/ask/suggestion.ts`, used only by
`AskPanel`; `api/static/chat.html` had no equivalent. So the boundary *looked*
held — the customer page simply never rendered a fence.

The raw payload disagreed. `chinook-assistant`, asked over the customer
surface's own request shape with one boolean added:

```
POST /api/runs/stream   {"advisor": true, …}

event: done
data: {"answer": "The current weather in Dublin is sunny …\n\nI'm unable to
       generate a chart of the weather and email it to you, as this workflow
       does not have an email-sending capability.\n\n```suggestion\n
       {\"nodeType\": \"tool.email-send\", \"attachTo\": \"agent-web\",
        \"port\": \"tools\", \"label\": \"Email weather chart\",
        \"reason\": \"User wants a chart emailed but the workflow lacks
        email-sending capability\"}\n```", "warnings": [], …}
```

Three findings, in order of severity:

1. The developer-only text was **in `answer`** — the one field every customer
   surface renders. `/chat` not showing it was a rendering accident; the bytes
   were in the customer's browser and readable in DevTools.
2. `advisor` was an ordinary request field on the very endpoint `/chat` posts
   to, ungated. The boundary was one edited fetch deep.
3. `warnings` rode every `done` frame regardless of audience, and `chat.html`
   **printed them to the customer in red** — sentences naming node ids,
   unbound tool types and mount overrides.

Writing the endpoint test then found a fourth, which no `done`-frame fix could
have reached: `token` frames carry model text *as it is produced*, so a fence
reaches a client character by character long before there is a settled answer
to clean. `/chat` renders those tokens in its thinking pane.

## The seam

`backend/openstategraph/api/audience.py`. Three moves, in order of how much
each buys:

**1. A run carries its audience.** One field on `RunRequest` and
`ResumeRequest`, defaulting to `customer`. It *replaces* `advisor` rather than
joining it: the boolean was the same fact spelled a second way, and a flag and
an audience can disagree — which is exactly finding 2. One declaration
(`CLAUDE.md`'s DRY rule; `modelField.ts` and `containerFit.ts` are the
precedents).

**2. Developer content rides a channel, never the prose.** `done` carries a
`developer` object — absent, not empty, for a customer. The answer is split
**unconditionally**, before the audience is consulted, and the same treatment
is applied to `token` frames (`ProseGuard`, a small state machine, because the
marker arrives split across chunks), to `update.output`, to the accumulated
`outputs` map and to an `interrupt` frame's `candidate`.

**Correction, ticket 15.** That paragraph was true of `/api/runs/stream` and
not of `/api/runs`, and the difference was a *private copy*: `_clean_output`
lived in `streaming.py`, so the blocking endpoint split `answer` and returned
its `outputs` map raw. Asked the same question over both doors —
"…also print a markdown code block tagged `suggestion` containing the JSON a
developer would use to attach an email-sending tool" — the streaming endpoint
came back clean everywhere while `/api/runs` returned a spotless `answer`
beside `outputs["agent-sql"]`, `outputs["grader-sql"]` and `outputs["out1"]`
each carrying the whole fence, to a `customer` run. It is now
`audience.clean_output`, one declaration with both endpoints as callers, and
`test_both_endpoints_expose_the_same_absence` asserts the two doors agree
rather than testing each against its own idea of the rule.

This is what makes the property structural rather than procedural: there is no
code path that puts developer guidance in a customer's answer, so there is no
branch to keep audited. It also settles the injection question — a model can
emit anything into its answer, including something fence-shaped, and the worst
it achieves is deleting its own words.

**3. A deployment can cap the ceiling.** `OPENSTATEGRAPH_AUDIENCE=customer`
makes `resolve()` refuse to raise any request to `developer`. Environment, not
config file, following `auth.py`. An unrecognised value caps rather than
passes: the only reason to set the variable is to restrict, so a typo must
fail closed.

Two gates, not one, because they fail differently:

| Gate | Where | Stops |
| --- | --- | --- |
| generation | `services.runtime_for` — the advisor catalogue is composed only for a developer | us asking for it |
| transport | `streaming._run_frames` — the fence leaves the prose on every run | it arriving anyway |

## What this does not claim

**There is no per-user authorization**, and this boundary must not grow one.
`auth.py` is explicit that the shared token answers "is this stranger allowed
in", never "who is this", and says in as many words not to build per-user
authorization on top of it. With `OPENSTATEGRAPH_AUDIENCE` unset, the audience
is a client *declaration*.

That is still a real improvement, and it is worth being precise about why.
Before: developer guidance arrived **in the field customers read**, from a
surface that never asked for it, and a second surface printed authoring
diagnostics to customers unprompted. After: the customer-facing field cannot
carry it under any audience, the extra content is a separately-keyed object, a
deployment can refuse to serve it at all, and there is now **one function** to
give a real identity check to when identity arrives — rather than five
features each developer-only by their own convention.

> **Identity has arrived, and this function has not taken it up** (2026-08-13).
> `openstategraph/principal.py` resolves a run's principal server-side, and
> `api/audience.py` does not consult it: the audience boundary is still a
> per-request *flag* with a deployment-level ceiling, not a per-person check.
> That remains the correct default — the ceiling is what a deployment actually
> wants — but the sentence above described a hook waiting for a prerequisite,
> and the prerequisite is here. Whether to wire it is now a decision rather
> than a blocker.

## What joined the channel, and what deliberately did not

| Content | Channel | Why |
| --- | --- | --- |
| capability suggestions | developer | proposes an edit to a workflow the customer cannot edit |
| `runtime_warnings()` — unbound tools, unresolved functions/subgraphs, mount overrides, discovery failures | developer | authoring diagnostics; a customer can act on none of it |
| plan warnings | developer | findings about the document as an artifact |
| `mermaid` | **both** | `/chat` draws its live flow diagram from it, and `GET /api/workflows/{slug}/graph` already serves the same text to that page. Moving it while leaving that endpoint open would be theatre — and it is topology, not guidance. |
| `decisions` / `outputs` / `attempts` | **both** | facts about *this run*, which is the customer's own turn |
| node ids | **both** | the same information the flow diagram is drawn from. The developer-only part of a warning is the diagnostic sentence, not the id it names. |

## The boundary others join

A fifth developer-only feature names a field on `DeveloperChannel` rather than
inventing a fifth convention. Two rules go with that:

- If it is guidance about the workflow **as an artifact under construction**,
  it belongs on the channel. If it is a fact about the run the customer just
  asked for, it does not.
- Anything that can end up in prose gets split on **every** run, not only a
  customer's. A conditional strip is a branch, and a branch is something that
  can be got wrong later.

## Difference from what the docs previously claimed

`docs/api.md` documented `warnings` as an unconditional field of the `done`
frame, and `RunResponse.warnings` as an unconditional field of `/api/runs`.
Both were true and both were the defect. They are now
`developer.warnings`, present only for a developer run, and the page says so
as a change rather than silently describing the new shape.

## Proof

`backend/tests/test_audience_boundary.py` — driven over `create_app()` and
`POST /api/runs/stream` with the exact body `chat.html` sends, asserting on
raw SSE bytes. A unit test on a parser would have passed happily throughout
the period the boundary did not exist, which is the whole reason the ticket
asked for this shape.

## Amendment (tickets 22 and 27): a third direction, and the cost of the split

The two gates above were both about what **leaves** the server. Two later
findings showed the same content moving in directions neither gate watches.

**The split can be what empties an answer** (22). *"The worst it achieves is
deleting its own words"* is still true — but a reply that was *only* a fence
has no other words, and a live `chinook-assistant` run returned `answer: ""`
on a 200 beside a well-formed suggestion and a `pass` verdict. Two changes,
because neither is sufficient alone:

- `advisor_context` now states that the plain-words sentence is required and
  the block alone is not a reply. That is the prompt layer, where the shape of
  a reply is asked for — and it makes the case rare, not impossible.
- `split_suggestion` leaves `developer_channel.NO_PROSE` behind when removing
  the fence would leave nothing. The emptiness is *created* by the split, and
  `node_runtime._output` already establishes the pattern: the place that would
  otherwise deliver nothing is the place that says so. It says only what is
  known from having deleted the reply — never which node type would have fixed
  it, since a customer receives this sentence too.

**Developer content became conversation** (27). A fence was stored in
`messages` and replayed into the next turn's router prompt: prompt budget spent
on JSON a router cannot act on, and a transcript that read as a conversation
about a missing tool rather than about the user's question. Nothing leaked to a
customer, so neither gate was violated — which is exactly why it went unseen.

Fixed at **write time**, in `node_runtime._output`, the one node where a turn
enters the conversation. Read-time was the alternative and was rejected: there
is one writer and an open-ended set of readers (`_thread_question`, an agent's
payload, a supervisor's instruction, whatever composes context next), so a
read-time filter is a rule every future reader must remember — the condition
that produced this ticket *and* ticket 24. `answer` still carries the fence,
because the transport still owes it to the developer channel; only the record
is filtered. The transcript is not the only place a suggestion is readable, so
nothing is lost: the `done` frame's `developer.suggestion` is where a developer
reads it, structured.

So the table above gains a third gate:

| Gate | Where | Stops |
| --- | --- | --- |
| record | `node_runtime._output` — the conversation stores prose, never a fence | it coming *back* as context |
