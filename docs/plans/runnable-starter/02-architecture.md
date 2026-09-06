# Architecture: runnable starter

## Fit
- **`src/app/firstRunStarter.ts`** — owns the first-visit placement today
  (`firstRunFragment`, `placeFirstRunStarter`, `shouldPlaceStarter`,
  `STARTER_PLACED_KEY`, `FIRST_RUN_NOTE`). Everything here changes in that
  file and the assembly it composes; nothing new decides *whether* to place.
- **`src/nodes/assemblies/starter.ts`** — `starterAssembly`: Input
  (`data.prompt: ''`) → Agent → Output. The question is a value in that
  fragment. Keep one definition: the assembly stays empty (it is also the
  palette's "starter" a user drags in), and `firstRunFragment` fills
  `prompt` for the first visit only — the note-and-geometry layer it already
  is.
- **`workbench.engine.on('run:finish', { ok, usage, error, reason })`**
  (`src/view/AppShell.tsx` ~548) — the one signal a run ended. The note's
  "what just happened" text is written from it, by id, through the
  controller (`controller.nodes.setField(noteId, 'body', text)` —
  `SetFieldCommand`, so it is undoable and the model stays the truth).
- **`/api/health` → `runReadiness`** (`RuntimeClient.health()`, mirrored at
  ~1872) — the sentence the default provider prints about itself
  (`ProviderCatalogue.elected_default().reason`, one function, three
  surfaces). The no-model variant of the note quotes it; nothing here
  invents a second wording.
- **`src/view/canvas/emptyStateCopy.ts`** and the arrival dialog are
  untouched: the first visit already bypasses the arrival offer
  (`placedStarter` gates `useArrivalOffer`).

## Endpoints
None new. `GET /api/health` (exists) supplies `run_readiness` and
`model_configured`.

## Data
No store change. The starter document gains: `Input.data.prompt` = the
canned question; the note's `body` = pre-run text, rewritten after the first
run. `localStorage[STARTER_PLACED_KEY]` unchanged. A new
`sessionStorage` flag is **not** needed: "has this starter run yet" is read
off the note's own body (a marker line), so a refresh mid-way keeps the
right note.

## Flow
1. First visit → `shouldPlaceStarter` (unchanged) → `placeFirstRunStarter`
   → `firstRunFragment()` now carries `prompt: STARTER_QUESTION` and
   `FIRST_RUN_NOTE` (before-run wording: press Run).
2. If `health.modelConfigured === false` at placement time, the note is the
   **no-model** wording, quoting `runReadiness` — decided at placement, and
   re-decided on the next health poll if the flag flips (the top bar's
   `RuntimeHealthDot` already polls; subscribe to the same value).
3. User presses Run → existing path → `run:finish` fires → if the document
   still holds the starter note (found by its id `first-run-note`) and its
   body carries the before-run marker → `setField(noteId, 'body',
   afterRunNote({ ok, usage, error }))`. On `ok: false`, the note names the
   error's readiness sentence rather than a generic failure.
4. Delete the note → nothing more happens; the flow stays. Save → unchanged
   (asks for a name).

## External
None. The default provider's key name comes from the catalogue via
`runReadiness`; no variable name is hardcoded in the frontend.
