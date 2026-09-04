# Program Design: runnable starter

## Files
- `src/app/firstRunStarter.ts` — **changed**: the fragment carries the
  question; the note has two before-run wordings (model / no model) and one
  after-run wording; the after-run rewrite lives here beside the placement,
  since both are "what the first visit says".
- `src/app/firstRunStarterCopy.ts` — **new**: the three note texts and the
  question, as constants with a marker line, so `userFacingLexicon.test.ts`
  and the length test have one file to read. (Split from the above only if
  the module ceiling asks; otherwise stays inside `firstRunStarter.ts`.)
- `src/app/WorkbenchContext.tsx` — **changed**: placement passes the
  readiness `serverReadiness` already holds, so the note is
  right on first paint; subscribes `run:finish` once for the rewrite.
- `src/app/aFirstVisitIsHandedAStarterNotAWorkflow.test.ts` — **changed**:
  `what is placed` gains the question and the wording cases.
- `src/app/aStarterExplainsItsFirstRun.test.ts` — **new**: the rewrite.
- `docs/getting-started.md` — **changed**: the first-run paragraph.

## Types & signatures

```ts
// firstRunStarter.ts
export const STARTER_QUESTION: string;           // one paragraph question, ≤ 200 chars
export const NOTE_ID = 'first-run-note';
export const BEFORE_RUN_MARKER = '<!-- starter:before-run -->'; // last line of a before-run note

export type StarterReadiness = { readonly modelConfigured: boolean; readonly runReadiness: string };

export function beforeRunNote(readiness: StarterReadiness | null): string;
  // null → the "press Run" wording (readiness unknown, do not scare);
  // modelConfigured false → the no-model wording quoting runReadiness verbatim.
export function afterRunNote(outcome: { ok: true; model: string | null; totalTokens: number } | { ok: false; reason: string }): string;

export function firstRunFragment(readiness: StarterReadiness | null): ClipboardFragment;
  // Input.data.prompt = STARTER_QUESTION; note body = beforeRunNote(readiness)

export function placeFirstRunStarter(workbench: Workbench, store: KeyValueStore, readiness: StarterReadiness | null): void;

export function starterNoteAwaitingRun(workbench: Workbench): NodeId | null;
  // the note node if present AND its body ends with BEFORE_RUN_MARKER, else null

export function explainFirstRun(workbench: Workbench, outcome: Parameters<typeof afterRunNote>[0]): boolean;
  // finds the awaiting note, setField(noteId, 'body', afterRunNote(outcome)); returns whether it wrote
```

```ts
// WorkbenchContext.tsx (inside the existing startup effect)
placeFirstRunStarter(workbench, localStorage, readinessOrNull);
// and once, near where run feedback is wired:
workbench.engine.on('run:finish', (r) => { explainFirstRun(workbench, toOutcome(r)); });
```

The `SetFieldCommand` path: `workbench.controller.nodes.setField(noteId, 'body', text)` — undoable, model-first, projected to the canvas.

## Call stack
**First visit:** startup effect → `shouldPlaceStarter` (unchanged) →
`serverReadiness` (`src/core/providers/serverReadiness.ts`, the shared source the top bar's dot already listens to — read its current `modelConfigured`/`runReadiness`, `null` when it has not answered yet) → `placeFirstRunStarter(wb, ls, readiness)`
→ `firstRunFragment(readiness)` → `clipboard.insertFragment` → note +
Input(prompt) + Agent + Output on the canvas, nothing selected.

**Run:** user presses Run → existing `runWorkflow` → engine → `run:finish`
→ `explainFirstRun(wb, outcome)` → `starterNoteAwaitingRun` → `setField`.
A second run finds no marker and writes nothing. A deleted note: nothing.

**No model:** same as first visit with `modelConfigured: false` → the
no-model note. When a run is attempted anyway and fails, `run:finish`
carries `ok: false` → the after-run note names the readiness sentence.

## Test plan
`aFirstVisitIsHandedAStarterNotAWorkflow.test.ts` (`what is placed`):
- `the input arrives with the question typed` — `prompt === STARTER_QUESTION`.
- `the note ends with the before-run marker` — so the rewrite can find it.
- `a starter placed with no model says which sentence the server gave` —
  `beforeRunNote({modelConfigured:false, runReadiness:'X'})` contains `X`
  and does not contain "press Run".
- `readiness unknown reads as press Run` — `beforeRunNote(null)`.
- `still not a named package` — existing assertions unchanged.

`aStarterExplainsItsFirstRun.test.ts`:
- `a finished run rewrites the note once` — after `explainFirstRun` the
  body names the model and token count and no longer ends with the marker;
  a second call returns `false` and changes nothing.
- `a failed run names the reason` — `ok:false` body contains the reason.
- `a deleted note is left alone` — returns `false`, no command pushed.
- `the rewrite is one undoable step` — `controller.history` length +1.
- `the note stays under the length ceiling` — the existing 400-character
  rule applies to every wording.

`userFacingLexicon.test.ts`: passes (no forbidden words in the new copy).

## Least confident decisions
1. **Readiness is read from `serverReadiness` at placement, `null` if it has not answered.** No wait on first paint; `null` reads as "press Run". A listener on the same source rewrites a still-awaiting note if the flag flips before the first run — one source, never a second poll.
2. **The marker is an HTML comment inside the note body.** Invisible in the
   rendered note, visible to the finder. If the note renderer escapes
   comments, switch to a trailing zero-width line — the test will say.
3. **The after-run note names the model from `usage`'s first key.** A run
   on two models names the first and says "and 1 more".
4. **The question is about the product itself** (what a state graph is), so
   the answer is checkable by the reader with no data source. A data
   question would need a tool and a key.
