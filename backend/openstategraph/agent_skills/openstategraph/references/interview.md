# The interview — long form

Read this when step 5 of `SKILL.md` is the step you are on, and only for a
feature or a slice — step 3 decides how much of it you run.

## The rule that makes it work

**One question per turn.** Not two, not a numbered list of six. A developer
answering six questions at once answers the easy ones and leaves the expensive
one for later, and the expensive one is the reason you asked.

**The questions come from the concept, not from this page.** The dimensions
below are what must be *settled*, not a script to read out. If the developer
says "a support triage bot", your first question is about support tickets, not
about "inputs".

**Facts are your job; decisions are theirs.** Never ask something the
installation can answer. Which node types exist, whether a provider is
configured, what the current step budget is, whether a package of that name
already exists — go and look, then ask the question the fact raises. Every
question carries your recommended answer so they can agree in one word.

**Stop when the dimensions are settled, not when you run out of ideas.** An
explicitly accepted gap is a settled dimension: *"we do not know the volume
yet, we will find out in production, and the design must not depend on it"* is
an answer. A dimension nobody mentioned is not.

## The dimensions, and what a real answer looks like

### Input — what goes in, from whom, in what shape

A real answer names the caller and the shape. "A question from a user in
`/chat`" is real. "Text" is not — it does not say whether it arrives with a
thread id, whether the same person asks twice, or whether an empty one is
possible.

Ask about the empty case and the hostile case. Both are cheap now.

### Output — what comes out, and who reads it

Two different readers need two different answers, and the platform already
knows the difference: a **customer** answer and a **developer** answer are
distinct audiences. Ask which one this workflow's output is for. A workflow
whose answer is read by a person needs prose; one whose answer is consumed by
another step needs a shape somebody has to parse.

### Steps — which node type carries each step

**Name the types, from the vocabulary you read in step 4.** This is the
dimension that goes wrong silently: a plan written as "then it decides which
department" and never mapped onto a real type produces a document naming a
type nothing resolves.

If nothing registered fits a step, that is a finding, not a blockage. Say so,
and file a card for extending the family's base and registering a new type. Do
not invent the type in the document and hope.

### Judgement — where a revision loop belongs, and what ends it

A grader that sends work back is two edges, not a wrapper. Ask:

- What is being judged — the answer's correctness, its format, its tone?
- What does the grader see? It cannot see what nothing gives it.
- **What ends the loop?** Every loop needs a way out that is not the step
  budget. A loop whose only exit is the budget is a loop that fails
  expensively rather than answering.

### Tools — what must be fetched, and from where

For each tool: what it reads, where it lives, and whose credentials it uses.
A tool that needs a secret the developer has not set is a card, filed now,
before it becomes a mysterious empty result later.

Ask whether the tool is allowed to write anything. Most are not, and saying so
is cheaper than finding out.

### Ground truth — what may not be invented

The single most valuable question in this interview. A model asked about data
it cannot see will answer anyway, fluently and wrongly.

- What are the facts this workflow must never guess?
- Where do they come from?
- What should happen when they are missing — refuse, say so, or fall back?

"Refuse and say why" is almost always the right default, and it needs to be
in the prompt rules rather than assumed.

### Budget — steps and tokens

Two separate numbers, and they are often confused.

- **Step budget** — the graph's recursion limit, counted in supersteps. One
  lap of a loop with fan-out costs several. Never call it "iterations".
- **Token budget for the build** — what the developer is willing to spend on
  *you* building this, including any helper you spawn. Ask for it, record it
  on the cards, and stop when you reach it rather than after.

### Done — what "done" looks like

Must be something you can run. "It works well" is not a criterion. "It answers
these three questions from the sample data, and refuses the fourth" is.

This becomes the done-when on the cards, so ask for it in the form the card
needs.

## Ending the interview

Say, in a few lines:

1. What you understood, in the developer's own words where you have them.
2. Every accepted gap, listed, so none of them is silent.
3. The size you judged it (step 3) and why, if it has changed since.
4. The cards you are about to file.

Then wait. The interview is not finished until they have seen that summary.
