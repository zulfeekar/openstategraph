# A fan-out's revision loop: feedback follows the branch

`workflow-gallery` 48. A router's branches are unlimited going out; each
agent's `feedback` port is `maxConnections: 1` coming in. So a graph that
fans out — a classifier dispatching to several desk agents, one grader
downstream of all of them — could not close a revision loop at all: a
`revise` verdict would have to pick exactly one of the branch agents to send
it to, and a technical failure redrafted by the billing desk is worse than no
loop. `workflows/support-triage` (gallery example 19) is the worked case, and
it shipped `pass` only, documenting the gap, until this ticket.

## The decision

**A `revise` edge lands on the *router*, not on a branch agent.** The router
gains one new `feedback` input port. On a trusted `revise`, it does not
reclassify — it re-dispatches to whichever branch its own last decision
named, replaying rather than re-deciding.

**Why the router and not a branch agent**: the router made the dispatch
choice, so it is the one node that can take the correction and act on it
correctly. A grader behind a fan-out knows the answer is wrong; it does not
know *who wrote it*. The router does. Sending the correction anywhere else
requires guessing, and a technical failure redrafted by the billing desk —
this ticket's own example — is exactly the cost of guessing wrong.

## Two sketches priced and declined

**`agent.feedback` becomes a bus** (`maxConnections: null`): cheap to draw —
one `revise` edge fans out to every branch agent's `feedback` port, each
agent reading only the feedback addressed to it. Declined because it
contradicts CLAUDE.md's "cardinality belongs to the port, not the node" rule
directly: this would be an existing port's cardinality toggled from 1 to
unlimited, exactly the move that rule warns against, in favour of varying the
*number* of ports (which the router's branch outputs already do). It would
also change what `feedback` means for every document that already wires one
— a semantic break immediately before a public release.

**Nothing** — state on the card that a grader behind a fan-out is a recorder,
not a gate, and let `Finding.UNWIRED_REVISE` be the whole answer. Declined by
the owner, knowingly: cheaper and beta-safe, but it leaves the fan-out shape
permanently unable to correct itself, which is the defect the ticket exists
to fix rather than to document away.

## The mechanism, briefly

- **The port.** `RouterNode.ts` declares a `feedback` input port, type
  `PORT.feedback`, default cardinality (`maxConnections: 1`, same as every
  other `in` port — not widened). `acyclicRule` needed no change: it already
  gates purely on `sourcePort.type === 'feedback'`, so a family gaining a
  `feedback` input is a node-family change, not a validation-rule change
  (`src/core/validation/reviseMayTargetTheQuestion.test.ts` pins this).
- **The compiler.** A grader's `revise` edge already compiles to an ordinary
  conditional-edge entry keyed off the grader's own `revise` port type — the
  destination's type was never inspected — so `grader.revise → router.feedback`
  needed no change to `workflow_compiler.py`'s edge classification.
- **The replay.** `NodeRuntime._router`'s `run()` now checks, before
  classifying, whether a grader whose `revise`/`rejected` edge targets this
  router has a still-standing revise decision. If so, it skips
  `router.classify()` entirely and re-emits `decisions[node_id]` — its own
  prior branch — rather than asking the model again. This is not merely an
  optimisation: a fresh classification could legally choose a *different*
  branch than the one that wrote the rejected draft (a classifying model is
  not deterministic), which would hand the grader's correction to a desk that
  never saw the question.
- **The relay.** Because only the router's chosen branch is ever invoked by
  LangGraph's conditional dispatch, the branch agent that runs on a revise
  lap is always the one whose feedback should be trusted. So
  `NodeRuntime._feedback_sources` (shared by `_agent` and the orchestrator's
  worker planner) was widened: a grader counts as a feedback source for a
  node not only when its `revise`/`rejected` edge names that node directly,
  but also when it names a router that can reach that node. The branch
  agent's own `feedback` port needs no new edge — the correction reaches it
  because the router re-dispatched to it, exactly as an ordinary branch edge
  already would on any lap.
- **The state.** `decisions` is keyed by node id and MERGE-reduced, reset
  once per turn by `_input`; no new reducer was needed; a node type
  (`route.classifier`) writing its own key was already legal.

`backend/tests/test_a_router_re_dispatches_a_revision.py` drives a real
compiled fan-out graph — a router scripted to answer a *different* branch on
a second classification, to prove the replay is a genuine replay and not a
reclassification that happened to agree — and asserts the same desk is
re-invoked, the other desk is never touched, and the desk receives the
grader's actual rejection text addressed to it as the author.

## Where it ships

`workflows/support-triage` (gallery example 19) wires `grader1.revise` onto
`router1.feedback`. `Finding.UNWIRED_REVISE` no longer fires for that
document; the grader is a gate again, not merely a recorder.

That sentence named the dev workspace copy, and it is the **packaged** copy
(`backend/openstategraph/examples/support-triage`) that `pip install` actually
ships — the one this decision's own worked example needs to demonstrate the
feature to an adopter. The two had drifted: `workflow-gallery` 48 built this
decision into the dev copy only, so the packaged copy still shipped `pass`
only, still fired `Finding.UNWIRED_REVISE`, and `examples/index.json` still
called that deliberate — false once this decision landed.
`workflow-gallery` 78 wired the packaged copy the same way and retired the
stale `_comment`. Both copies now demonstrate the router relay.

## What this does not change

- The `_router_for` fallback (an unwired `revise` verdict routes to the first
  declared destination) is untouched, and still a real hazard elsewhere —
  `workflow-gallery` 31.
- A branch agent that is neither the desk which wrote the answer nor
  reachable from the router at all still receives no feedback; the widened
  trust check only ever *adds* sources, never removes the existing direct
  check.
- `workflow-gallery/31`'s fix 3 — a card/schema statement that an unwired
  grader "records a verdict, it does not gate" — was unblocked by this
  decision but is not built here; it remains open.
