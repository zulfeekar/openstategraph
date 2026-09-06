# Product: runnable starter

## Problem
"I opened it, there were three boxes and a note telling me to type
something. I didn't know what to type or what would happen." A first visit
lands on an empty question. The person has to invent a question, find Run,
and then read a dock they have never seen. Most stop at the first step.

## Success metric
A stranger reaches a first answer without typing anything: open the editor,
press Run, read an answer. Measured as *clicks to first answer* = 1 on a
fresh browser with a provider configured (a UI test drives it), and *when no
provider is configured, the screen names the variable to set* rather than
failing silently (a second test).

## Announcement — the blog post before the feature
The first thing you see in OpenStateGraph now runs. Open the editor for the
first time and there is a small working flow on the canvas with a question
already typed into it. Press Run. The agent answers, the answer appears in
the Output, and a short note beside the flow tells you what just happened
and what to change next: the question, the agent's instructions, or the
model. If you have not set up a model yet, the same note tells you which
key to set, by name, so the first run is never a mystery. Delete the note
when you are done reading; the flow is yours.

## Screens
- `mockups/first-visit.html` — the canvas on first visit: the note, the
  three nodes with the question typed, before Run.
- `mockups/after-run.html` — the same canvas after Run: the answer in Output,
  the note's "what just happened" text, and the no-provider variant below it.
