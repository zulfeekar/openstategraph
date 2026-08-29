import type { SpawnedChild } from '@core/model/contracts/node';
import { spawnedByOwner, type SpawnedTaskRow } from './spawnedTasks';

/**
 * Put what the run spawned onto the cards that spawned it.
 *
 * The canvas half of `canvas-feels-right/07`, and the whole of its write
 * path. Kept here as a pure function over `read`/`write` rather than inlined
 * into `AskPanel`'s frame handler for the reason this repository has had to
 * learn six times in one week: a rule living inside a fold is a rule no test
 * can reach on its own, and this surface has fooled a green suite seven
 * times.
 *
 * ## What it writes, and why that is not "writing to the graph"
 *
 * `setNodeRuntime` is not a command. It is not undoable, it does not go
 * through `ICommand`, and `WorkflowSerializer` never sees it — which is
 * exactly the channel `launch-readiness/140` already uses for `narration`.
 * The ticket's boundary is *nothing writes to the graph*, and the graph is
 * the saved document: nodes, edges, positions, data. None of those move
 * here, and no chip can ever be saved.
 *
 * ## Why it re-reads before it writes
 *
 * The fold is over every row the turn holds, so it runs again on every
 * frame and returns a fresh array each time. Writing that array
 * unconditionally would emit `node:runtime` on every frame for every card
 * that has ever spawned anything, re-rendering cards whose chips did not
 * change — and a `NodeCard` re-render is a self-measurement that reports
 * geometry back to the canvas. `unchanged` is what keeps a projection from
 * becoming a load.
 *
 * ## What it does not do
 *
 * It never clears. A run that has spawned nothing writes nothing at all, so
 * a card keeps last run's chips exactly as it keeps last run's narration —
 * and `AskPanel.resetRunState` wipes both with `IDLE_RUNTIME` at the start
 * of the next run, which is the one moment "this is not this run's" becomes
 * true. Clearing here instead would make a chip vanish mid-run the moment a
 * reconnect replayed fewer rows than the last frame did.
 */
export function projectSpawned(
  rows: readonly SpawnedTaskRow[],
  hasNode: (id: string) => boolean,
  read: (id: string) => readonly SpawnedChild[],
  write: (id: string, spawned: readonly SpawnedChild[]) => void,
): void {
  for (const [owner, children] of spawnedByOwner(rows, hasNode)) {
    if (unchanged(read(owner), children)) continue;
    write(owner, children);
  }
}

/**
 * Whether a card's chips would look identical after this write.
 *
 * Compares the fields a chip is drawn from and the account it opens. `key`
 * alone is not enough — a fan-out child's lines arrive *after* its chip
 * does, and a popover that never gained them would be the blank box
 * `taskAccountNote` exists to avoid.
 */
function unchanged(before: readonly SpawnedChild[], after: readonly SpawnedChild[]): boolean {
  if (before.length !== after.length) return false;
  return before.every((was, index) => {
    const now = after[index];
    if (!now) return false;
    return (
      was.key === now.key &&
      was.kind === now.kind &&
      was.label === now.label &&
      was.instruction === now.instruction &&
      was.reported === now.reported &&
      was.detached === now.detached &&
      was.lines.length === now.lines.length &&
      was.lines.every((line, at) => line === now.lines[at])
    );
  });
}
