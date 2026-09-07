import { useCallback } from 'react';
import type { SpawnedChild } from '@core/model/contracts/node';
import { usePaperController } from '@app/WorkbenchContext';
import { SpawnedTaskPill } from './SpawnedTaskPill';
import './CardSpawnedPills.css';

/**
 * The chips that hang off a node card — the canvas half of
 * `canvas-feels-right/07`.
 *
 * ## The limitation this closes
 *
 * `launch-readiness/140` recorded it and could not fix it: a `Send` fan-out
 * creates **tasks, not canvas nodes**, so three parallel workers all
 * dispatch from one card and the canvas draws one box. A reader cannot see
 * that three things are happening. Three chips above the card is the whole
 * fix, and it is why this ticket is on the beta bar rather than being
 * decoration.
 *
 * ## Why it hangs *off* the card and not inside it
 *
 * This is the ticket's fourth boundary — *the canvas is JointJS and node
 * positions are the user's; an overlay that moves their nodes is worse than
 * no overlay* — and on this card it is mechanical rather than aesthetic.
 * `NodeCard` measures its own `getBoundingClientRect()` and pushes the
 * result to `paper.adapter.applyGeometry`, and then to
 * `controller.nodes.applyMeasuredSize`. Anything added to the card's *flow*
 * would therefore grow the element on the paper and move every port dot on
 * it — a card that got taller because a run happened, with its links
 * re-routed and its neighbours overlapped, none of which the user asked for.
 *
 * It would not corrupt the saved file: `production-ready/69` established
 * that a measured height is not document state, and
 * `measuredHeightIsNotDocument.test.ts` holds that line. But the model still
 * carries the measured size, and the minimap, `Arrange`, grouping and *where
 * does the next node go* all read it. So the size change is real even though
 * the diff is not, which is precisely the ticket's complaint: the layout is
 * the user's.
 *
 * So the rail is `position: absolute`, sitting on the card's outside above
 * its top edge. An absolutely positioned descendant is outside its
 * ancestor's border box, so the card measures exactly what it measured
 * before: `report()` sees the same height, the same fingerprint, and does
 * not write. The chips are drawn where nothing is saved and nothing is
 * measured — which is also the most literal reading of *visibly not
 * savable* that this canvas can offer.
 *
 * The **top** edge specifically, because the bottom is spoken for: the ports
 * footer sits there and `.node__pill` — the tool bus capsule — straddles the
 * bottom edge and *is* measured, as a port anchor. Nothing on this canvas
 * hangs above the header.
 *
 * ## The one thing JointJS wins, and how it is given back
 *
 * A drag-pan closes an open popover on its own: the canvas installs
 * document-level pointer handlers and `Pill` closes on the **capture** phase,
 * so the popover is gone before the pan begins. A **wheel zoom** is not a
 * pointer-down, and it does not scroll or resize anything either — JointJS
 * rewrites an SVG transform — so nothing in the DOM told the popover its chip
 * had moved. Measured live on `parallel-workers-join`: a wheel-zoom moved the
 * chip from y=406 to y=540 and left the popover at y=427.
 *
 * The canvas layer is the only one that can answer *did the anchor move*, so
 * it is the one that says so: `paper.viewport.onChange`, handed to `Pill` as
 * a subscription. `design/` learns nothing about a paper, and the chat panel
 * passes nothing and is unchanged. `NodeCard` re-measures itself from the
 * same signal for the same reason.
 *
 * ## Why the popover opens downward
 *
 * `placement="bottom"`. A chip already sits above the card, so a popover
 * above the chip would be a second thing climbing away from the node it is
 * about; opening it downward puts the account over the card that produced
 * it. It is portalled into `document.body` either way, so no paper viewport
 * clips it and no `overflow` on a card can.
 *
 * ## What it does not do
 *
 * Nothing here reads a controller, dispatches a command, or touches the
 * model. It is handed `node.runtime.spawned` — run state, written by
 * `projectSpawned`, cleared by `IDLE_RUNTIME` — and renders it.
 */
export function CardSpawnedPills({
  spawned,
  running,
  startedBy,
}: {
  readonly spawned: readonly SpawnedChild[];
  readonly running: boolean;
  /** This card's own title: on the canvas the launcher is what you are looking at. */
  readonly startedBy: string;
}) {
  const paper = usePaperController();
  const subscribeAnchorMoved = useCallback(
    (update: () => void) => paper?.viewport.onChange(update) ?? (() => {}),
    [paper],
  );

  if (spawned.length === 0) return null;

  return (
    <div
      className="node__spawned"
      // Not `data-no-drag`, which is the card's opt-out for its own
      // controls — this rail is outside the card's box, so a drag never
      // started here in the first place. `Pill` stops its own pointer-down
      // regardless, which is what keeps a click on a chip from reaching
      // JointJS's document-level handlers.
      role="group"
      aria-label={
        spawned.length === 1
          ? `1 worker ${startedBy} started`
          : `${spawned.length} workers ${startedBy} started`
      }
    >
      {spawned.map((task) => (
        <SpawnedTaskPill
          key={task.key}
          task={task}
          running={running}
          startedBy={startedBy}
          placement="bottom"
          subscribeAnchorMoved={subscribeAnchorMoved}
        />
      ))}
    </div>
  );
}
