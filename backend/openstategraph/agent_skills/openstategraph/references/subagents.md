# Helpers — long form

Read this when step 11 of `SKILL.md` is the step you are on.

This sheet tells you when to hand a card to a helper. It cannot spawn one: if
your platform has no subagent facility, run the same loop inline and say so to
the developer. Nothing about the loop changes — only who types it.

## The four gates

A card goes to a helper only when **all four** are true. Three of four is a
card you do yourself.

### 1. Reproducible without a person

There is no question a helper would have to ask. Everything it needs is on the
card: the story, the done-when, the file it lives in, the command that shows
the defect. If you find yourself thinking "it will figure that out", the gate
is failed and the fix is to put the answer on the card.

### 2. The decision is already made

A helper executes; it does not choose. A card that still contains a design
choice — which node type, which of two prompts, whether to refuse or fall back
— goes back to the interview or to the board as a judgement card for the
developer. Handing an open decision to a helper is how a decision gets made by
whoever happened to be running, with nobody recording it.

### 3. Blast radius contained

You can name the files it may touch, and they are few. A card that says "and
update the callers" across a codebase you have not read is not contained. Cut
it into cards that are.

### 4. Cost

No model calls beyond the budget the card states. This is the gate that gets
waved through, and the one the developer feels. A helper that runs workflows,
or that will spawn helpers of its own, spends real money. If the card's budget
does not cover what you are about to ask for, ask the developer first.

## What to hand it

- **The card's own text**, whole — story, done-when, evidence, blocked-by.
- **The engineering rules** (`engineering-rules.md` beside this sheet).
- **The build loop**, so it does the red-then-break-then-green sequence rather
  than a fix and a claim.
- The card's `agent_model` and `agent_effort`. They were chosen at filing time
  from the shape of the work: a small model at low effort for mechanical work,
  a large model at high effort for judgement. If your platform cannot select a
  model, treat them as advice and say that you did.

Nothing else. A helper briefed with the whole conversation inherits the
conversation's assumptions and cannot tell which of them were settled.

## Verify before you believe

**A report is testimony. The filesystem is evidence.** Agents report work they
did not do — not maliciously, and not rarely. After every helper returns, run
the checks yourself:

1. **The commit.** Does the sha it names exist, and does its diff do what the
   report says?
2. **The tree.** `git status` — anything left uncommitted, anything staged
   that should not be, any file touched outside the card's stated radius?
3. **The tests.** Run them. Not the ones the helper says it ran — the suite.

A report that survives all three is true. A report that does not is a card
that is still open, whatever it says.

## Reporting back

Three lines to the developer, no more:

1. What the helper did, in the terms the card was written in.
2. The sha, and the gate numbers from the suite you ran.
3. Anything it did *not* do, or did differently from the card.

The third line is the one worth writing. A helper that solved a different
problem well has still left the card open.
