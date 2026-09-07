# grill-the-app

Break the product on purpose, as a real person would, and turn what breaks into
tickets.

Agent-agnostic. Plain markdown, no Claude-specific tooling — the same rule
`skills/atom-forge/` follows.

## When to run this

After a change that a user could notice, or before believing the product is
ready. **Not** as a substitute for tests: every defect this skill was built from
was found while 3379 backend and 2311 frontend tests were green. Tests check
what someone thought to assert. This checks what the product actually says.

## The one rule

**Run it and read the output.** Not the tests, not the code, not a screenshot —
the words a person would read, and the trace beside them.

A screenshot does not show two answers when the second is below the fold. That
is how a workflow was recorded green with a duplicate-answer bug live in it.

## Ask like a person, not like a test

A test asks the documented question once. A person does not. Work through these,
in order, in **one thread**, because most of what breaks lives between turns:

1. **The lazy question.** Half a sentence, no context. *"hey, quick one — whats
   our biggest seller?"* Watch what it assumes.
2. **The correction.** Contradict yourself the way people do. *"no i meant by
   number sold not money."* Did it carry the thread, or start over?
3. **The vague follow-up.** *"how do we usually handle this kind of thing?"* —
   "this" is only defined by the previous turns. A workflow that answers this
   well is genuinely holding a conversation.
4. **The thing it cannot do.** Ask for live data, a tool it has not got, a fact
   it cannot know. It must **say so**. If it narrates its attempts, or invents,
   that is a defect (`every-workflow-green` 19).
5. **The gate.** Make it draft something for a person to approve. Approve one,
   **reject one with a note**, and **reject one saying nothing at all**. The
   silent rejection is where the product invented a reviewer's words
   (`every-workflow-green` 11).
6. **The rude input.** Empty string. One character. A paragraph with no
   question in it. Something in another language.

## What to look for, and it is rarely the crash

Every defect on the `every-workflow-green` map but one was the machinery
**knowing something and not saying it**, or **saying something it did not
know**. Crashes announce themselves. These do not. So after each turn ask:

- **What would NOT have been reported?** A step that produced nothing, a grader
  that gave up, a tool that never bound, a mounted step that failed.
- **Is every sentence on screen true?** Count the ones that name a thing —
  "the grader passed it", "the reviewer said", "every workflow" — and check each
  against the graph. A workflow with no grader said *"2 attempts before the
  grader passed it"* (21).
- **Is the answer buried?** Working-out before the answer is a defect of order,
  not of content.
- **Does the same run say the same thing two ways?** Compare `/api/runs` with
  `/api/runs/stream`. They disagreed twice (16, 14).

## Read the structure, never the text

`document.body.innerText` flattens a page and has produced **three** false
findings on this map. Read children one at a time:

    .ask__turn        one turn
      .ask__steps       the trace   (.ask__trace-step / .ask__activity-node)
      .ask__tools       tool results
      .ask__answer-block  the answer
      .ask__approval    the gate
      .ask__warning     what it is telling you

## Before you call anything a bug

- **Three data points** before calling it systematic. Two nearly produced a
  ticket that the third contradicted.
- **Tap the live wire.** Driving the object directly — `load_workflow(...)
  .graph.invoke(...)` — found two root causes in one call each, and killed one
  scare in one call.
- **Check which build answered.** uvicorn does not auto-reload here. A "the fix
  failed" reading was a server two hours older than the edit.
- **Check the browser is not lying to you.** The editor restores a cached draft
  per slug from `localStorage`; a file corrected on disk can be masked by it for
  a whole session (22).
- **Green unit tests are not verification.** A fix passed its tests with the bug
  still live, because a model summarises a tool's *output*, not its description
  (12).

## Then

Ticket it with `/wayfinder`: what a user saw, the chain back to the cause, what
was ruled out, and the reproduction. **Fix one at a time**, and verify each by
trying to break it again — twice on this map a fix was incomplete and only a
live re-run showed it.

An honest *"reproduced, not diagnosed"* is a finished ticket. A guessed fix is
not.
