# Slices: runnable starter

1. **Tracer.** `firstRunFragment` fills `Input.data.prompt` with
   `STARTER_QUESTION`; `FIRST_RUN_NOTE` becomes `beforeRunNote(null)` (press
   Run) ending with `BEFORE_RUN_MARKER`. Proof: a fresh browser profile shows
   the question typed in and the note. Tests: the two `what is placed`
   cases; existing starter tests unchanged.
2. **The note explains the first run.** `starterNoteAwaitingRun`,
   `afterRunNote`, `explainFirstRun`, wired to `run:finish` in
   `WorkbenchContext`. Proof: press Run with a configured model; the note
   changes; Undo restores it; Run again changes nothing. Tests: rewrites
   once, undoable, deleted note left alone, length ceiling.
3. **No model, and failure.** `beforeRunNote` with `modelConfigured:false`
   quotes `runReadiness`; a `serverReadiness` listener rewrites an
   awaiting note when the flag flips; `ok:false` after-run wording. Proof:
   start the server with the provider key unset; the note names the
   sentence. Tests: no-model wording, flip, failed run.
4. **Paper.** `docs/getting-started.md` paragraph; `userFacingLexicon` and
   length tests green; ceilings; closing commit with
   `Ticket: stable-beta-public/06`.
