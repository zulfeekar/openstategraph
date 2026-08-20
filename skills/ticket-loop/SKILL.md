# ticket-loop

**The session shape, written down once so it stops being retyped.** One ticket
per session. Every step below happens; none of them is optional, and the two
that get skipped are the second browser pass and the handoff.

This skill is the *spine*. It calls the others — `skills/test-as-a-user/` for
the browser work, `/wayfinder` for filing, `/grill-me` for ambiguity,
`/graphify` for finding code. It does not repeat what they say.

## 0 — A cleared context, and the owner is the one who clears it

**`/clear` first, then invoke this skill.** In that order — clearing *after*
invoking wipes this file out of context along with everything else, and the
skill has to be invoked again.

A skill cannot run `/clear`; it is a command the app executes, not something an
agent can call. So this step is a **reminder, not a gate**: if the context is
already dirty when you read it, say so out loud and let the owner decide
whether to clear and start over. Do not pretend a stale context is a fresh one
— the specific failure it causes is confident, wrong statements about a ticket
that closed an hour ago.

This is also the last line of the loop. Finish, write the handoff, **then**
clear — the handoff is what survives the clear, which is the whole reason
step 8 is not optional.

**Fingerprint the checkout before you touch it.**

```bash
python3 scripts/session_guard.py snapshot
```

Running the product writes files — disk autosave rewrites
`workflows/<slug>/workflow.json` on every edit the editor makes. That is
correct behaviour, and it is also how a thirteen-node example was replaced by a
blank document twice on 2026-08-20, both times noticed by accident. `verify`
at the end, naming the files you meant to change.

## 1 — Orient before touching anything

1. **Read the newest `.scratch/HANDOFF-<YYYY-MM-DD>.md`.** Newest by *date in
   the filename*, not by mtime. It carries the priority list, and its
   *instrument notes* section is a list of hours already paid — read it before
   you pay them again.
2. **Read `CLAUDE.md`.** The non-negotiables decide the shape of the fix.
3. **`python3 scripts/ticket_ledger.py`.** It reports where git and the ticket
   headers disagree. Run it *before* trusting any statement about what is left,
   including the handoff's own list.
4. **Take ticket #1 from the priority list.** Not the easiest one. If #1 is
   genuinely blocked, say so in the handoff and take #2 — silently skipping is
   how a list stops being a list.

Do not read source to orient. `graphify explain "X"` / `graphify path "A" "B"`.

## 2 — Reproduce as a person

`skills/test-as-a-user/`. Open the browser, use the product, see the defect on
screen. A ticket you cannot reproduce is a ticket to re-scope, not to fix.

## 3 — TDD

Failing test first, **at the layer the defect actually lives**. The trap this
repo has paid for twice: a green test at the wrong layer. Ticket 33's fix was
wired into `_agent` and not `_worker`, and both of its tests stayed green
because neither asks a *node* anything. Before writing the test, ask: *what
would still be green if I fixed the wrong function?*

Then make it pass, and run both suites.

**Then break the fix and watch the test go red.** Comment out the guard you
just added, re-run, confirm the failure, put it back. It costs a minute and it
is the only thing that distinguishes a test of the fix from a test of itself —
`production-ready` 71's first test was green against a completely disabled
fix, because it restated the gate instead of calling it. A test that
reimplements the decision it is checking proves only that the test agrees with
itself.

## 4 — Test as a user again

Same path, same question, in the browser. **If it is not fixed on screen, it is
not fixed.** A green suite is not the verification.

Then try to break it. Three times on these maps a fix was incomplete and only a
live re-run showed it — most recently `production-ready` 71, whose second
browser pass found the other half of the same data loss *and destroyed a file
finding it*.

**Reading the canvas needs a paint.** While the Browser pane is hidden,
`document.visibilityState` is `"hidden"`, `requestAnimationFrame` never fires
and `.joint-cells-layer` is an empty string for a document with thirteen nodes
in it. Take a screenshot first, then assert on the DOM.

## 5 — Commit with a trailer

```
Ticket: <map>/<nn>
```

The map name is part of the id — every map numbers from 01. Several trailers on
one commit is fine. The commit message carries the *account*: what was wrong,
what was ruled out, what was priced and rejected.

**Never push.** Never `git stash` — other sessions edit this repo at the same
time and a stash swallows their work.

## 6 — Close the ticket in both places

`.scratch/` is gitignored, so a resolution written only in the ticket leaves no
diff and a concurrent revert takes it with no trace. So both:

- the **header** — `Status: resolved`, or `Status: partially` when half of it
  genuinely shipped and half did not. Half-open said in prose that
  `is_partial` cannot read is how a ticket reads open for work that landed.
- the **body** — the resolution, and the commit that carries it.

Re-run `python3 scripts/ticket_ledger.py`. It should be quieter than it was in
step 1, not louder.

## 7 — Update the docs

If the behaviour a document describes changed, the document changed in the same
commit. Regenerate what is generated (`docs/openapi.json` and friends) rather
than hand-editing it.

A number stated in prose has no way to fail — pin it in a test instead, the way
`src/publicSurfaceCeiling.test.ts` pins the class ceilings. That rule is why
`CLAUDE.md` carries three corrections of its own claims.

## 8 — Update `HANDOFF-<latest date>.md` — this is the step that gets dropped

**The handoff is the only thing the next session reads first. A ticket closed
without it is a ticket nobody knows is closed.**

The file is `.scratch/HANDOFF-<YYYY-MM-DD>.md`, dated **today**.

- **If today's file exists**, edit it.
- **If the newest one carries an older date**, write a *new* file for today and
  carry forward only what is still live — the priority list, the open drifts,
  the instrument notes. Do not edit a stale date, and do not delete the old
  file: it is the record of that day.

Write into it, every time:

- **Done this session** — the ticket, its verdict, the commit sha, one or two
  sentences of what was actually learned. Not "fixed the bug".
- **Next, in priority order** — strike the finished item, promote what follows,
  and add anything filed today at the position it deserves. If the item you did
  spawned a second half, it is a *new numbered ticket* in this list, not a
  footnote.
- **Instrument notes** — anything that cost you time and will cost the next
  session the same: a restart that was needed, a selector that lies, a
  suite command, a false signal that looks exactly like a real bug.

Update it **when a ticket closes**, and also whenever any of these happen, even
mid-ticket: a new ticket is filed, the priority order changes, a ledger drift is
resolved, or you learn something about the instruments. When in doubt, write it
— the cost of a redundant line is nothing against the cost of the next session
re-deriving it.

## Anything found on the way

`/wayfinder` triage into a ticket: what the user saw, the chain back, what was
ruled out, the reproduction. **Do not fix it in passing.** One ticket per
session is the rule, and a drive-by fix has no test, no browser pass and no
trailer.

An honest *"reproduced, not diagnosed"* is finished work. A guessed fix is not.

Ambiguity — what the ticket wants is genuinely unclear, or two readings imply
different work — is `/grill-me`, not a coin flip.

## Done means

- [ ] browser before, browser after
- [ ] test written first, at the right layer
- [ ] both suites run
- [ ] commit carries `Ticket: <map>/<nn>`
- [ ] ticket header *and* body say resolved / partially
- [ ] `scripts/ticket_ledger.py` re-run
- [ ] docs updated, generated files regenerated
- [ ] **`.scratch/HANDOFF-<today>.md` updated — done, next, instruments**
- [ ] `python3 scripts/session_guard.py verify <the files you meant to change>`
      is clean
- [ ] nothing pushed
- [ ] the owner told, in one line, that the session is finished and `/clear` is
      theirs to press
