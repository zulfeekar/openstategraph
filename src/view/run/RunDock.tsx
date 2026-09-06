import { useCallback, useMemo, useRef, useState } from 'react';
import { Activity, exportTrace } from '../ask/traceTree';
import { RunTimeline, SelectedBar } from '../ask/RunTimeline';
import { laneFold, type RunLanes, type TimelineRow } from '../ask/timeline';
import { reusableFold } from '../ask/incrementalFold';
import type { RunView } from './runView';
import { runCost } from './runCost';
import { runView } from './runView';
import { PayloadPane } from './PayloadPane';
import { DOCK_MIN_HEIGHT, dockHeightFromArrow, dockHeightFromDrag } from '../layout/dockFit';
import { Grip } from '@design/primitives';
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
 * The run timeline, docked under the top bar with a draggable lower edge.
 *
 * `memory-and-replay` 51 and 63. The owner asked for the timeline as *"a
 * section on the top panel"*, and the part of that which was always settled is
 * that the *surface* is not a 48 px header strip: a scrubbable multi-lane
 * chart does not fit in one. **The control is an icon in the top bar and the
 * surface opens directly beneath it**, and it *pushes* rather than overlays —
 * the shell holds the top bar, then this panel, then a stage carrying
 * everything else, so the canvas is never covered; it is shorter, and shorter
 * from the top. Every other panel in this app overlays when the room runs out,
 * and none of them is a time axis you read while watching the thing it is
 * measuring.
 *
 * `51` docked it at the far edge of the window instead, and `63` is the
 * correction the owner asked for in their own words — *"clicking on it will
 * push down the paper"*. It is not a preference between two placements: a
 * control at the top of the window whose effect happens at the bottom of the
 * window has its effect where the user is not looking.
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
 * - **The answer re-typing at its recorded cadence.** Still absent, and the
 *   reason has narrowed rather than gone. This paragraph said the cadence had
 *   *"no HTTP route, and `burst` appears nowhere in `docs/openapi.json`"* —
 *   both are false since `memory-and-replay` 72: `GET /api/runs/recorded/{id}`
 *   publishes a recording, and `StoredRuns` puts one on this dock. What that
 *   door deliberately does **not** carry is `RunBurst.cadence`, the per-chunk
 *   blob, because nothing reads it yet and a field with no reader drifts. So
 *   `60` is still open and still for the same underlying reason: a paragraph
 *   re-typed at a uniform tick is the fabricated measurement `52` forbids, and
 *   the real offsets stay in the store until a surface asks for them.
 * The two the port went back for are now here, and one is still short:
 *
 * - **The payload pane** — what the selected step *asked* and *produced*
 *   (`memory-and-replay` 59). The fold keeps the payload now, so nothing is
 *   parsed in a renderer; `stepPayload` decides what to *call* it per bar kind
 *   and what to say when there is nothing.
 * - **The identity and the cost** (`memory-and-replay` 61) — the thread the run
 *   reported, and `usage`, which had ridden the terminal frames since `56` and
 *   reached no surface at all. **Not the prototype's whole masthead**: it also
 *   showed a sitting and a timestamp, and neither is something *this run*
 *   reported. The sitting is this tab's own `browserSessionId`, which
 *   identifies the browser rather than the run; a wall-clock start is on no
 *   frame at all, and `52` fixed that the axis *"refuses to claim absolute
 *   time"*. Printing either would be the masthead answering a question the
 *   recording did not.
 *
 * # Where the identity goes at 260 px
 *
 * In the header, not in the profile strip. The strip is `tall`-gated and is
 * six numbers **derived from the fold**; the thread and the token total are
 * two facts **the run reported**, and mixing the two sources in one row would
 * make a reader ask which of them the fold could be wrong about. The header is
 * one line at every height, which is where a thing you check once belongs.
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
      // Dragged **downward** to grow: the free edge is the lower one, so the
      // edge follows the pointer and the number goes up with `clientY`. The
      // direction is `dockFit`'s, not this handler's — it is one subtraction
      // that reads correctly either way round and is only ever wrong in a
      // hand, so it has a name and a test (`memory-and-replay` 63).
      onHeightChange(dockHeightFromDrag(from.height, from.pointerY, event.clientY));
    },
    [onHeightChange],
  );

  const endDrag = useCallback(() => {
    dragFrom.current = null;
  }, []);

  const onKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      // A separator a pointer can move and a keyboard cannot is a control half
      // the users of this editor do not have — and one whose arrows disagree
      // with the drag is worse than one with no arrows at all, so both
      // directions come from the same module.
      const asked = dockHeightFromArrow(height, event.key);
      if (asked === null) return;
      onHeightChange(asked);
      event.preventDefault();
    },
    [height, onHeightChange],
  );

  const empty = view.rows.length === 0 && !view.running;
  // Not memoised: it is a sum over at most a handful of rows, and a memo whose
  // key is the same array identity the store already compares by would be
  // book-keeping for nothing.
  const cost = runCost(view);
  // One fold, read twice: the chart draws it and the detail pane answers for
  // whichever bar of it the reader picked. Two folds would be two records.
  //
  // And **one fold across the whole run**, not one per frame
  // (`the-cost-of-one-more/04`). `AskPanel` rebuilds `view.rows` for every
  // arriving frame, so the memo above it is honest and useless while a run
  // streams: the key changes every time. `reusableFold` keeps the fold's own
  // state in this dock and consumes only what arrived, and falls back to a
  // whole fold for anything that is not an extension of what it has seen — a
  // stored run opened here, or a second run in the same tab.
  // Held as lazy initial state rather than in a ref, so nothing reads a ref
  // during render: this dock's own fold, for as long as this dock is mounted.
  const [fold] = useState<(rows: readonly TimelineRow[]) => RunLanes>(() => reusableFold(laneFold));
  const { lanes, totalMs } = useMemo(() => fold(view.rows), [fold, view.rows]);
  const [selected, setSelected] = useState<string | null>(null);
  // Tall enough to earn the axis, the profile strip and the legend. A number
  // rather than a container query because the dock's height is state this
  // component already holds, and a query would ask the browser a question the
  // shell has already answered.
  const tall = height >= DOCK_TALL;

  return (
    <section className="run-dock" style={{ height: `${height}px` }} aria-label="Run timeline">
      {/* The same control the chat column's edge draws, on the other axis
          (`stable-beta-public/21`) — the look and the ARIA come from the
          primitive, the arithmetic stays here. */}
      <Grip
        orientation="horizontal"
        ariaLabel="Resize the run timeline"
        value={height}
        min={DOCK_MIN_HEIGHT}
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
        {/* Which run this is, and what it cost — `memory-and-replay` 61.
            Rendered only when the run named a thread: `''` is the record
            saying it disclosed none, and a placeholder in an identity slot is
            an identity a reader would try to look up. */}
        {view.threadId === '' ? null : (
          <span className="run-dock__thread" title={`Thread ${view.threadId}`}>
            <span className="run-dock__thread-label">Thread</span>
            <code>{view.threadId}</code>
          </span>
        )}
        <span className="run-dock__cost" title={cost.caption}>
          <span className="run-dock__cost-label">Tokens</span>
          <code>{cost.total}</code>
        </span>
        <span className="run-dock__actions">
          {/* The way back out of a recording (`memory-and-replay` 73), and it
              lives here rather than only in the picker that opened it: that
              picker is a popover and closes on Escape, on a click outside and
              on its own control, so a reader looking at the chart they came
              for would have no way back at exactly the moment they want one.
              Offered only over a stored run, because a live run has nothing to
              return to. */}
          {view.source === 'stored' ? (
            <button
              type="button"
              className="run-dock__back"
              onClick={() => runView.release()}
              title="Show the run this tab is on again. Nothing re-runs either way."
            >
              Back to this tab&apos;s run
            </button>
          ) : null}
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
            <PayloadPane lanes={lanes} selected={selected} />
            <Activity rows={view.rows} />
          </div>
        </div>
      )}
    </section>
  );
}

/**
 * The height at which the chart gains its axis, profile strip and legend.
 *
 * Picked against the default: 260 px leaves the lanes about 150 px, and the
 * three together cost roughly 70 of it. At 360 the lanes keep what they had
 * and the extras are additions rather than a trade.
 */
export const DOCK_TALL = 360;
