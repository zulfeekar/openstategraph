---
name: atom-forge
description: Turn a raw finding (a title, evidence, a reason) into a well-formed, atomic ticket — a label line, a short story, done-when criteria. Use when authoring a ticket from an error, a code smell, or a patrol finding, so every ticket in a project reads the same way regardless of who or what filed it.
---

# atom-forge

OpenStateGraph's own, independent answer to "what makes one ticket well
-formed" — written in the spirit of gated, ticket-driven engineering practice
(staged planning, atomic scope, evidence over assertion), not a copy of any
specific author's skill or template.

## What a well-formed ticket has, always

1. **A title that names the symptom, not the fix.** "A tool call with no
   timeout" — what a reader would actually see — never "add a timeout
   parameter," which presumes the remedy before anyone reasoned about it.

2. **One label line, machine-parseable**: kind (`task`/`bug`/`research`/
   `grilling`/`decision`/`prototype` — this decides whether an agent may
   attend it or a human must), area (which discipline owns it), priority
   (`high`/`med`/`low`), and status (`open`/`partially`/`resolved` — never
   two words standing in for "half done").

   **Priority carries its own one-sentence reason, every time — never left
   to a generic "what High means" sentence.** "High priority" alone tells a
   reader nothing about *this* finding; "asked the same question 4 times in
   one thread" does. Write the reason from the finding's own evidence — the
   call count, the checkpoint, the actual failure text — never a plausible
   -sounding elaboration on top of it. If a card is filed with no reason, a
   reader has no way to tell a considered `high` from a guessed one.

3. **A short story: one concrete scenario, an actor, a moment.** "A finding
   names one workflow, and a mount put two on the thread" is checkable and
   specific. "Workflow attribution can be ambiguous" is neither — it could
   describe a hundred different bugs, which means it describes none of them
   precisely enough to act on.

4. **Done-when, as assertions a test could pin — never a task list.**
   "Patrolling the same thread twice produces one card, not two" is
   something a reader can check is true or false. "Handle duplicates" is an
   instruction with no way to know when it's satisfied.

## The rule that matters most: never invent evidence

A ticket built from a finding cites the finding's own fields — the thread id,
the checkpoint ids, the failure reason exactly as recorded — and never a
plausible-sounding elaboration on top of them. If the finding is thin, the
ticket is thin and says so plainly. A ticket that looks more finished than
its evidence supports is a ticket that will mislead whoever picks it up.

## Input and output

**Input**: whatever produced the finding hands over its raw shape — a title,
a category, evidence (thread id, checkpoint ids, a reason string), and
whether a remedy is already implied (a deterministic detector fired) or is
still a judgement call (a human or model's read of something ambiguous).

**Output**: the four-part ticket above, as plain text. This skill decides
*what a ticket says*; it does not decide where the ticket goes — a kanban
card's instruction field, a markdown file on disk, or read aloud to a
person. That is the caller's job, not this one.
