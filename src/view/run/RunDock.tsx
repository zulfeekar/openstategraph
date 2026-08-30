import { useCallback, useMemo, useRef, useState } from 'react';
import { Activity, exportTrace } from '../ask/traceTree';
import { RunTimeline, SelectedBar } from '../ask/RunTimeline';
import { buildLanes } from '../ask/timeline';
import type { RunView } from './runView';
import { DOCK_MIN_HEIGHT } from '../layout/dockFit';
// The bars and the trace rows keep their styles where they were written. They
// are the same two renderings this panel is promoting out of the chat, and
// moving eight hundred lines of stylesheet in the same commit that moves the
// components would make one diff out of two changes. Declared rather than
// relied upon: `AskPanel.css` reaches the bundle today because `AppShell`
// imports the panel statically, and that is a fact about an import graph, not
// a guarantee.
import '../ask/AskPanel.css';
import './RunDock.css';

/**
 * The run timeline, as a bottom dock with a draggable top edge.
 *
 * `memory-and-replay` 51. The owner asked for the timeline as *"a section on
 * the top panel"*, and what that turned out to mean is settled: **the control
 * lives in the top bar, the surface lives at the bottom**, and the surface
 * *pushes* rather than overlays — the shell wraps the whole current view
 * (top bar, palette, canvas, inspector) in one stage and this panel is its
 * **sibling**. So the canvas is never covered; it is shorter. Every other
 * panel in this app overlays when the room runs out, and none of them is a
 * time axis you read while watching the thing it is measuring.
 *
 * **`view/`, and never a JointJS paper feature.** The canvas is a one-way
 * projection of the *model*; a timeline draws a *run*. One surface must not
 * project two sources of truth, and `canvas-feels-right` 07 already settled
 * that a run's activity writes to no model.
 *
 * **One component, two data sources.** It is written against `RunView` and
 * knows nothing about SSE or storage, so the lane rules (`memory-and-replay`
 * 50), the dash-for-no-clock rule (`launch-readiness` 108) and every fix a
 * future defect earns are learned once. Two of the three surfaces that drew a
 * run are here: the bars, and the trace tree beside them as the detail pane.
 * `PastRuns` stays in the chat panel on purpose — it is a list *of runs*,
 * which is a different job from drawing one.
 *
 * **The transport appears when the run has an end, and not before**
 * (`memory-and-replay` 52). The owner's words: *"a live run has no end yet; a
 * slider that cannot reach its right-hand edge is lying about what it can
 * do."* So a live run gets a playhead pinned to the head and no scrubber at
 * all, and the same panel gains the transport when the frames stop.
 *
 * # What earns 260 px, and what needs a drag
 *
 * The prototype was a full page arguing a design and the dock is 260 px by
 * default, so this is a decision rather than a port:
 *
 * | | at 260 px | why |
 * | --- | --- | --- |
 * | the lanes and their bars | **yes** | it is what the panel is |
 * | the transport row | **yes** | a control you have to make room for is a control nobody finds |
 * | the caveat line | **yes** | it has to be true of every bar above it, at every height |
 * | the selected bar's facts | **yes** | it is the answer to the click that was just made |
 * | the time axis with ticks | dragged taller | the bars are already in scale with each other; the ticks put numbers on it |
 * | the profile strip | dragged taller | six numbers about the whole run, none of which is why the panel was opened |
 * | the legend | dragged taller | the vocabulary is meant to read without one — it is a reference, not a key |
 *
 * # What was left out of the port, and why
 *
 * - **The answer re-typing at its recorded cadence.** It needs `47`'s bursts,
 *   and `47` is `partially`: the store keeps the cadence and the reader is
 *   Python-level — no HTTP route, and `burst` appears nowhere in
 *   `docs/openapi.json`. A paragraph re-typed at a uniform tick is exactly the
 *   fabricated measurement `52` exists to forbid, so it is absent rather than
 *   faked. `memory-and-replay` 60.
 * - **The payload pane** — what the selected step *asked* and *produced*.
 *   `ActivityRow.output` is one opaque string and the fold does not keep it, so
 *   the per-family readings the prototype showed would be invented here.
 *   `memory-and-replay` 59.
 * - **The identity masthead and the token total.** Thread, sitting and
 *   timestamp are `44`'s run record and tokens ride `56`'s terminal frames;
 *   `RunView` carries rows and nothing else. `memory-and-replay` 61.
 */
export function RunDock({
  view,
  height,
  onHeightChange,
  onClose,
}: {
  readonly view: RunView;
  readonly height: number;
  /**
   * A height the drag has asked for. **Unclamped** — the shell owns the
   * clamp, because the ceiling is a fact about how tall the shell is and the
   * dock cannot see past itself.
   */
  readonly onHeightChange: (requested: number) => void;
  readonly onClose: () => void;
}) {
  const dragFrom = useRef<{ pointerY: number; height: number } | null>(null);

  const onPointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      event.preventDefault();
      event.currentTarget.setPointerCapture(event.pointerId);
      dragFrom.current = { pointerY: event.clientY, height };
    },
    [height],
  );

  const onPointerMove = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      const from = dragFrom.current;
      if (!from) return;
      // Dragged **upward** to grow, the way a desktop app's bottom drawer
      // behaves: the edge follows the pointer, so the number goes up as
      // `clientY` goes down.
      onHeightChange(from.height + (from.pointerY - event.clientY));
    },
    [onHeightChange],
  );

  const endDrag = useCallback(() => {
    dragFrom.current = null;
  }, []);

  const onKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      // A separator a pointer can move and a keyboard cannot is a control half
      // the users of this editor do not have.
      if (event.key === 'ArrowUp') onHeightChange(height + KEYBOARD_STEP);
      else if (event.key === 'ArrowDown') onHeightChange(height - KEYBOARD_STEP);
      else return;
      event.preventDefault();
    },
    [height, onHeightChange],
  );

  const empty = view.rows.length === 0 && !view.running;
  // One fold, read twice: the chart draws it and the detail pane answers for
  // whichever bar of it the reader picked. Two folds would be two records.
  const { lanes, totalMs } = useMemo(() => buildLanes(view.rows), [view.rows]);
  const [selected, setSelected] = useState<string | null>(null);
  // Tall enough to earn the axis, the profile strip and the legend. A number
  // rather than a container query because the dock's height is state this
  // component already holds, and a query would ask the browser a question the
  // shell has already answered.
  const tall = height >= DOCK_TALL;

  return (
    <section className="run-dock" style={{ height: `${height}px` }} aria-label="Run timeline">
      <div
        className="run-dock__grip"
        role="separator"
        aria-orientation="horizontal"
        aria-label="Resize the run timeline"
        aria-valuenow={Math.round(height)}
        aria-valuemin={DOCK_MIN_HEIGHT}
        tabIndex={0}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        onKeyDown={onKeyDown}
      />

      <header className="run-dock__head">
        <h2 className="run-dock__title">Run timeline</h2>
        {/* What run this is, in the words it was asked in — the dock is
            outside the conversation now, so it has to say. */}
        <span className="run-dock__subject" title={view.question}>
          {view.question === '' ? 'Nothing has run in this tab yet' : view.question}
        </span>
        <span className="run-dock__state" data-running={view.running || undefined}>
          {view.running ? 'Running' : view.source === 'stored' ? 'Stored run' : 'Finished'}
        </span>
        <span className="run-dock__actions">
          {!view.running && view.rows.length > 0 ? (
            // Export travels with the trace, which is what it exports. It is
            // the one thing 51 said must stay reachable when these two views
            // left the chat panel, so it is on the surface that now holds them.
            <button
              type="button"
              className="ask__export"
              onClick={() =>
                exportTrace({ question: view.question, activity: view.rows, result: null })
              }
              title="Download this run as structured trace JSON"
            >
              Export trace JSON
            </button>
          ) : null}
          <button type="button" className="run-dock__close" onClick={onClose}>
            Close
          </button>
        </span>
      </header>

      {empty ? (
        <p className="run-dock__idle">
          Ask this workflow something, or press Run. The bars appear as the backend reports each
          step, and stay after it finishes.
        </p>
      ) : (
        <div className="run-dock__body">
          {/* When and for how long, then what ran and what it produced. Two
              readings of one record, side by side rather than behind a tab —
              which is the width a bottom dock buys and a 300px chat panel
              never had. */}
          <div className="run-dock__bars">
            <RunTimeline
              lanes={lanes}
              totalMs={totalMs}
              running={view.running}
              tall={tall}
              selected={selected}
              onSelect={setSelected}
            />
          </div>
          {/* Not a third pane. `58` asked whether the payload view and the
              trace tree are the same role, and they are: one pane answering
              one question in two grains — *this bar*, then *everything that
              ran*. The bar's facts sit above the trace because a reader who
              just clicked a bar has said which grain they want first. */}
          <div className="run-dock__detail">
            <SelectedBar lanes={lanes} selected={selected} />
            <Activity rows={view.rows} />
          </div>
        </div>
      )}
    </section>
  );
}

/** How much one arrow press moves the edge. */
const KEYBOARD_STEP = 24;

/**
 * The height at which the chart gains its axis, profile strip and legend.
 *
 * Picked against the default: 260 px leaves the lanes about 150 px, and the
 * three together cost roughly 70 of it. At 360 the lanes keep what they had
 * and the extras are additions rather than a trade.
 */
export const DOCK_TALL = 360;
