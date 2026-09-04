# Status: runnable starter

- Gate 1 — Product: APPROVED 2026-09-04
- Gate 2 — Architecture: APPROVED 2026-09-04
- Gate 3 — Program Design: APPROVED 2026-09-04
- Gate 4 — Slice plan: APPROVED 2026-09-04 (owner delegated: "as you recommend")

## Slices
- [x] Slice 1 — tracer: the question is typed into the Input on first visit; the note says "press Run" and ends with the marker
- [x] Slice 2 — after the first run, the note rewrites itself once (model, tokens); undoable; second run leaves it
- [ ] Slice 3 — no-model wording from `serverReadiness`; failed run names the reason; flip listener
- [ ] Slice 4 — docs paragraph, lexicon and length tests, ceilings, closing commit `Ticket: stable-beta-public/06`

## Notes for a fresh session
- 2026-09-04: the owner delegated the remaining gate and slice approvals ("as you recommend the best way to go"); stop only for a real fork.
- Owner decision, 2026-09-04: the first visit opens a runnable example with
  a prompt already typed, a note saying "press Run", and the answer explained.
- Today's starter: `src/app/firstRunStarter.ts` places a Note + the
  `starterAssembly` (Input → Agent → Output), unsaved, once per browser
  (`STARTER_PLACED_KEY` in `localStorage`). Pinned by
  `src/app/aFirstVisitIsHandedAStarterNotAWorkflow.test.ts` — the first visit
  is a starter, never a named package. Keep that promise.
- Ticket: `.scratch/stable-beta-public/tickets/06`.
- **Slice 1 landed.** `STARTER_QUESTION`, `NOTE_ID`, `BEFORE_RUN_MARKER`,
  `beforeRunNote(readiness)` (null-case wording only; `modelConfigured:
  false` is slice 3) and `firstRunFragment(readiness)` are in
  `src/app/firstRunStarter.ts`. `FIRST_RUN_NOTE` stays exported as
  `beforeRunNote(null)` for `placeFirstRunStarter`, which still calls
  `firstRunFragment(null)` — the readiness wiring through
  `WorkbenchContext`/`serverReadiness` is slice 3, not this one.
- **The marker is not an HTML comment.** The program design's "least
  confident decisions" #2 named this risk and it turned out real: checked
  live against the built app (`RichText`, react-markdown, no raw-HTML
  plugin), a standalone `<!-- ... -->` line is not recognised as an HTML
  block in that position — it renders as ordinary paragraph text, so a
  reader would see the literal comment syntax at the bottom of every note.
  `BEFORE_RUN_MARKER` is a single zero-width space (`U+200B`) on its own
  line instead: a real character, so markdown does not trim the line away,
  but it renders at zero width. Verified in the browser: the Input holds
  `STARTER_QUESTION` verbatim, the note reads "press Run" with the marker's
  paragraph empty to the eye.

- **Slice 2 landed.** `StarterRunOutcome`, `afterRunNote`,
  `starterNoteAwaitingRun` and `explainFirstRun` are in
  `src/app/firstRunStarter.ts`; `src/app/aStarterExplainsItsFirstRun.test.ts`
  pins them. Two things the plan had wrong, both found by looking rather than
  by reasoning:
  - **`NOTE_ID` is not in the placed document.** `insertFragment` routes
    through `pasteCommand`, which mints a fresh id for every node, so the
    placed note is `node:annotate.note-1`. The marker is what finds it — which
    is what the marker was always for; only slice 1's docstring claimed
    otherwise, and it is corrected.
  - **`workbench.engine`'s `run:finish` never fires in the shipped app.**
    Nothing calls `engine.run()` any more: the toolbar's Run opens the chat and
    streams a backend run. Verified in the browser before rewiring — pressing
    Run finished a 2,455-token run and the note did not move. So the rewrite
    reads the `runView` snapshot the run dock is already drawn from (a reader
    on the existing subscription, not a second one), and its `usage` is
    `RunUsage[]` — **one row per model**, which is exactly the "usage's first
    model key" the program design meant. `AppShell.tsx`'s `run:finish` handler
    is left alone.
  - Wiring the **failed** run (`ok: false`) is slice 3: `runView` carries no
    error, and the wording it should quote is the readiness sentence slice 3
    introduces. `afterRunNote({ok:false})` exists and is tested, including that
    a 2,000-character reason still lands under the 400-character ceiling.
  - Browser proof, port 8124: cleared `localStorage`, reloaded, the starter
    appeared with the question; Run produced *"**gpt-oss:120b** answered —
    2,409 tokens"* in the note; Undo put the before-run note back and it was
    not immediately rewritten again.
