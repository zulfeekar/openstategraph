import { useCallback, useEffect, useMemo, useRef, useSyncExternalStore } from 'react';
import type { RunLane, RunLanes, StepKind, TimelineStep } from './timeline';
import { REPLAY_SPEEDS, replayTransport, stopsOf, transportOffered } from '../run/replayTransport';
import { runProfile } from '../run/runProfile';
import { WHY, barFacts, formatMs, laneCaption } from '../run/barDetail';

/**
 * The run chart: lanes, semantic bars, a playhead and a transport.
 *
 * `memory-and-replay` 58 and 52, ported from the design prototype the owner
 * authored (`osg-replay.html`) rather than re-derived from it. The prototype's
 * stylesheet defines no token of its own — every rule consumes one — so the
 * port is a rename of `--osg-*` to the `--color-*` role that resolves to it,
 * and its class names survive because **the class names are the design**. Its
 * transport logic (the rAF loop, stepping by frame, seek measured off a real
 * track element, the speed group) is the same logic, expressed as React state.
 *
 * What was *not* ported, and why, is as much of the decision as what was —
 * `RunDock` carries that list.
 *
 * # The bar vocabulary
 *
 * Semantic, never decorative. A model call is solid ink, a bar that spent no
 * model time is hollow with the node's own ink as a ring, a mount is hatched
 * because it is another document, and a refusal is the one place the accent is
 * spent. `StepKind` in the fold is where each of those is decided, from frames
 * that were already on the wire.
 *
 * # The three shapes that are not bars
 *
 * These are `58`'s and `52`'s honesty rules, and they are shapes rather than
 * captions, because a column of identical rectangles claims otherwise whatever
 * the caption underneath says:
 *
 * - **A bar the run never timed** is drawn as a short dashed notch, not as a
 *   rectangle of some width. `108` settled the label — `—`, never `0 ms` — and
 *   a hollow bar of zero width would be a different lie in the same place.
 * - **A run that reported no clock at all** has no axis, so its bars are laid
 *   out in sequence with no widths and the transport is withheld entirely.
 * - **An open-ended lane** runs to the right edge and is cut off there rather
 *   than ending: no right border, a fade, and a caption saying which kind of
 *   open the run recorded (`50`'s `ending`).
 */
export function RunTimeline({
  lanes,
  totalMs,
  running = false,
  tall = false,
  selected: picked,
  onSelect: setPicked,
}: RunLanes & {
  readonly running?: boolean;
  /**
   * The dock was dragged tall enough to earn the axis, the profile strip and
   * the legend. At 260 px they would take the chart's height from the thing
   * the chart is for; the decision, and what stays at every height, is
   * recorded on `RunDock`.
   */
  readonly tall?: boolean;
  /** The bar the reader is pointing at — held by the dock, because the pane
   * that answers for it is the dock's, not this chart's. */
  readonly selected: string | null;
  readonly onSelect: (key: string | null) => void;
}) {
  const profile = useMemo(() => runProfile({ lanes, totalMs }), [lanes, totalMs]);
  const offered = transportOffered(running, totalMs);
  const stops = useMemo(() => (offered ? stopsOf(lanes, totalMs) : []), [offered, lanes, totalMs]);

  useEffect(() => {
    replayTransport.attach(stops, offered ? totalMs : null);
  }, [stops, offered, totalMs]);

  const transport = useSyncExternalStore(
    useCallback((listener: () => void) => replayTransport.subscribe(listener), []),
    useCallback(() => replayTransport.read(), []),
  );

  // The prototype's `tick`, as an effect. A run in flight has no playhead of
  // its own — it is pinned to the head, which is what the last frame says.
  useEffect(() => {
    if (!transport.playing || totalMs === null) return;
    let frame = 0;
    let last = 0;
    const step = (now: number): void => {
      // The prototype's `tick` opens with this line and it is not belt and
      // braces: `cancelAnimationFrame` runs in the effect's cleanup, which is
      // a React scheduling decision, while `playing` goes false the instant
      // the button is pressed. Reading the store here is what makes Pause stop
      // the film rather than stop it soon.
      const at = replayTransport.read();
      if (!at.playing) return;
      if (last === 0) last = now;
      const next = at.atMs + ((now - last) / 1000) * at.rate * 1000;
      last = now;
      if (next >= totalMs) {
        replayTransport.seek(totalMs, false);
        return;
      }
      replayTransport.seek(next, true);
      frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [transport.playing, totalMs]);

  const at = offered ? transport.atMs : (totalMs ?? 0);
  const track = useRef<HTMLDivElement | null>(null);
  const dragging = useRef(false);

  // Seek measured off a real track element rather than off the name column's
  // width, deliberately: the number stays in the stylesheet only.
  const seekFrom = useCallback(
    (clientX: number): void => {
      const box = track.current?.getBoundingClientRect();
      if (!box || box.width === 0 || totalMs === null) return;
      replayTransport.seek(((clientX - box.left) / box.width) * totalMs, false);
    },
    [totalMs],
  );

  const onLanePointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>): void => {
      if (event.button !== 0 || !offered) return;
      const box = track.current?.getBoundingClientRect();
      // The name column is not a timeline.
      if (!box || event.clientX < box.left) return;
      dragging.current = true;
      seekFrom(event.clientX);
    },
    [offered, seekFrom],
  );

  useEffect(() => {
    const move = (event: PointerEvent): void => {
      if (dragging.current) seekFrom(event.clientX);
    };
    const up = (): void => {
      dragging.current = false;
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
    return () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
  }, [seekFrom]);

  if (lanes.every((lane) => lane.steps.length === 0)) {
    return <p className="ask__meta">No steps have fired yet.</p>;
  }

  const fraction = totalMs === null || totalMs <= 0 ? 1 : Math.min(1, at / totalMs);

  return (
    <div className="rtl" data-unclocked={totalMs === null || undefined}>
      {offered ? <Transport transport={transport} totalMs={totalMs} at={at} /> : null}

      {tall ? <Profile profile={profile} /> : null}

      <div className="rtl__main">
        {tall && totalMs !== null ? <Axis totalMs={totalMs} /> : null}

        {/* The lanes are the scrubber. A timeline you can read but not
              point at makes the reader translate "that bar" into a position
              on a separate strip below — so a click or drag anywhere on a
              track moves the playhead there, and the strip stays because it
              is still the easier target for a long drag. Every bar on these
              lanes is a real button, and the keyboard route to the playhead
              is the slider underneath. */}
        <div className="rtl__lanes" onPointerDown={onLanePointerDown}>
          {lanes.map((lane, index) => (
            <div className="rtl__lane" key={lane.key} data-depth={lane.kind === 'run' ? 0 : 1}>
              <div className="rtl__name" title={laneCaption(lane)}>
                {laneCaption(lane)}
              </div>
              <div className="rtl__track" ref={index === 0 ? track : undefined}>
                {lane.steps.map((step) => (
                  <Bar
                    key={step.key}
                    step={step}
                    totalMs={totalMs}
                    at={offered ? at : null}
                    selected={picked === step.key}
                    onSelect={setPicked}
                  />
                ))}
                {/* `54`'s `settled` frame, made visible: a 2 px tick where
                      the run said this child closed. A lane the run never
                      closed gets no tick — it gets the strip below instead,
                      because absence is not a mark a reader can see. */}
                {lane.endMs !== null && totalMs !== null && totalMs > 0 ? (
                  <span
                    className="rtl__mark"
                    style={{ insetInlineStart: `${(lane.endMs / totalMs) * 100}%` }}
                    title={`settled at ${formatMs(lane.endMs)}`}
                  />
                ) : null}
                {/* An open-ended lane runs to the edge and is cut off there
                      (`memory-and-replay` 50). The strip starts where the
                      lane's last dated moment was and fades out at the right
                      margin: no closing border, no width anybody measured, and
                      a title saying which kind of open the run recorded. A bar
                      with no end must not look like a bar with one. */}
                {lane.openEnded && totalMs !== null && totalMs > 0 ? (
                  <span
                    className="rtl__open"
                    style={{ insetInlineStart: `${(openFrom(lane) / totalMs) * 100}%` }}
                    title={openCaption(lane)}
                  />
                ) : null}
              </div>
            </div>
          ))}
          {/* The playhead and the scrubber are one decision, so they read one
              predicate (`memory-and-replay` 63). A run in flight draws no
              vertical line at all: it has no right-hand edge to reach, and a
              rule down the chart that cannot be moved is a control's whole
              affordance with none of its behaviour. It used to be drawn
              wherever the run had a clock and pinned to the head by
              `[data-live]`. */}
          {offered ? (
            <div
              className="rtl__playhead"
              style={{
                insetInlineStart: `calc(var(--rtl-name) + (100% - var(--rtl-name)) * ${fraction})`,
              }}
            />
          ) : null}
        </div>

        {offered ? <Scrub at={at} totalMs={totalMs ?? 0} /> : null}
        {tall ? <Legend /> : null}
        <p className="rtl__caveat">
          {caveatFor(
            lanes.flatMap((lane) => lane.steps),
            totalMs,
          )}
        </p>
      </div>
    </div>
  );
}

/**
 * The selected bar, in the dock's right-hand pane.
 *
 * **Not a third thing** — that was `58`'s open question. The prototype put the
 * selected step's payload beside the lanes and `51` had already moved the trace
 * tree into the same slot, so the honest reading is that they are one pane
 * answering one question in two grains: *this bar*, and then *everything that
 * ran*. It sits above the trace rather than beside it or behind a tab, because
 * a reader who clicks a bar has just told you which grain they want first.
 */
export function SelectedBar({
  lanes,
  selected,
}: {
  readonly lanes: readonly RunLane[];
  readonly selected: string | null;
}) {
  const found = findStep(lanes, selected);
  if (!found) {
    return (
      <p className="rtl__why">
        Pick a bar to see what it was, and when the run opened and closed it.
      </p>
    );
  }
  return (
    <div className="rtl__detail">
      <dl>
        {barFacts(found.lane, found.step).map((fact) => (
          <div key={fact.term}>
            <dt>{fact.term}</dt>
            <dd>{fact.value}</dd>
          </div>
        ))}
      </dl>
      <p className="rtl__why">{WHY[found.step.kind]}</p>
    </div>
  );
}

/** One bar, and the three shapes that are not one. */
function Bar({
  step,
  totalMs,
  at,
  selected,
  onSelect,
}: {
  readonly step: TimelineStep;
  readonly totalMs: number | null;
  /** Where the playhead is, or `null` when no transport is offered. */
  readonly at: number | null;
  readonly selected: boolean;
  readonly onSelect: (key: string) => void;
}) {
  const clocked = totalMs !== null && totalMs > 0 && step.startMs !== null;
  const unmeasured = step.durationMs === null;
  const style = clocked
    ? {
        insetInlineStart: `${((step.startMs ?? 0) / (totalMs ?? 1)) * 100}%`,
        width: unmeasured
          ? undefined
          : `${Math.max(0.6, ((step.durationMs ?? 0) / (totalMs ?? 1)) * 100)}%`,
      }
    : undefined;
  return (
    <button
      type="button"
      className="rtl__bar"
      data-kind={step.kind}
      data-unmeasured={unmeasured ? 'true' : undefined}
      data-pending={at !== null && step.startMs !== null && step.startMs > at ? 'true' : undefined}
      data-flow={clocked ? undefined : 'true'}
      aria-pressed={selected}
      style={style}
      title={`${step.label} · ${formatMs(step.durationMs)}`}
      onClick={() => onSelect(step.key)}
    >
      <span>
        {step.label}
        {step.visit > 1 ? ` ×${step.visit}` : ''}
      </span>
    </button>
  );
}

/** Where an open-ended lane's strip begins: the last moment it was dated. */
export function openFrom(lane: RunLane): number {
  const ends = lane.steps
    .filter((step) => step.startMs !== null)
    .map((step) => (step.startMs ?? 0) + (step.durationMs ?? 0));
  return Math.max(lane.startMs ?? 0, ...ends, 0);
}

/**
 * Which kind of open this is, in `50`'s words.
 *
 * Three different facts and never one word for all of them: a background child
 * is still working, a recording that stopped owes an account, and a child that
 * has simply not finished is neither. None of them is given a duration,
 * because the run measured none.
 */
export function openCaption(lane: RunLane): string {
  if (lane.ending === 'detached') return 'still running outside this run — the run never closed it';
  if (lane.ending === 'unknown') return 'the recording ended owing an account of this lane';
  if (lane.ending === 'error') return 'never ran';
  return 'not finished when this recording ended';
}

function Transport({
  transport,
  totalMs,
  at,
}: {
  readonly transport: { readonly playing: boolean; readonly rate: number };
  readonly totalMs: number | null;
  readonly at: number;
}) {
  return (
    <div className="rtl__transport">
      {/* No autoplay. A finished run opens paused at zero — someone opening a
          run is usually looking for a moment, not watching a film. */}
      <button
        type="button"
        className="rtl__play"
        aria-pressed={transport.playing}
        onClick={() => replayTransport.toggle()}
      >
        {transport.playing ? 'Pause' : 'Play'}
      </button>
      <button type="button" onClick={() => replayTransport.restart()}>
        Restart
      </button>
      {/* By frame, not by second: the useful unit is "what happened next", and
          a ten-second model call is one thing happening. */}
      <button type="button" onClick={() => replayTransport.stepBack()}>
        ◀ Step
      </button>
      <button type="button" onClick={() => replayTransport.stepForward()}>
        Step ▶
      </button>
      <span className="rtl__speeds" role="group" aria-label="Playback speed">
        {REPLAY_SPEEDS.map((rate) => (
          <button
            key={rate}
            type="button"
            aria-pressed={transport.rate === rate}
            onClick={() => replayTransport.setRate(rate)}
          >
            {rate}×
          </button>
        ))}
      </span>
      <span className="rtl__clock">
        <b>{formatMs(at)}</b> / {formatMs(totalMs)}
      </span>
    </div>
  );
}

function Scrub({ at, totalMs }: { readonly at: number; readonly totalMs: number }) {
  return (
    <div className="rtl__scrubrow">
      <div className="rtl__scrublabel">Scrub</div>
      <div
        className="rtl__scrub"
        role="slider"
        tabIndex={0}
        aria-label="Playhead position"
        aria-valuemin={0}
        aria-valuemax={Math.round(totalMs)}
        aria-valuenow={Math.round(at)}
        aria-valuetext={formatMs(at)}
        onPointerDown={(event) => {
          event.currentTarget.setPointerCapture(event.pointerId);
          seekWithin(event.currentTarget, event.clientX, totalMs);
        }}
        onPointerMove={(event) => {
          if (!event.currentTarget.hasPointerCapture(event.pointerId)) return;
          seekWithin(event.currentTarget, event.clientX, totalMs);
        }}
        onKeyDown={(event) => {
          // The slider's own arrows move by time, because that is what a
          // slider means; stepping by frame is the two Step buttons and the
          // shell's binding table.
          const step = event.shiftKey ? 1000 : 250;
          if (event.key === 'ArrowRight') replayTransport.seek(at + step);
          else if (event.key === 'ArrowLeft') replayTransport.seek(at - step);
          else if (event.key === 'Home') replayTransport.restart();
          else if (event.key === 'End') replayTransport.seek(totalMs);
          else return;
          event.preventDefault();
        }}
      >
        <div className="rtl__scrubfill" style={{ width: `${(at / (totalMs || 1)) * 100}%` }} />
      </div>
    </div>
  );
}

function seekWithin(element: HTMLElement, clientX: number, totalMs: number): void {
  const box = element.getBoundingClientRect();
  if (box.width === 0) return;
  replayTransport.seek(((clientX - box.left) / box.width) * totalMs, false);
}

function Axis({ totalMs }: { readonly totalMs: number }) {
  return (
    <div className="rtl__axis">
      <div />
      <div className="rtl__ticks">
        {axisTicks(totalMs).map((tick) => (
          <div
            key={tick}
            className="rtl__tick"
            style={{ insetInlineStart: `${(tick / totalMs) * 100}%` }}
          >
            {formatMs(tick)}
          </div>
        ))}
      </div>
    </div>
  );
}

/** Five or so round offsets across the run — never more than the width can hold. */
export function axisTicks(totalMs: number): readonly number[] {
  if (totalMs <= 0) return [0];
  const raw = totalMs / 5;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((n) => n * magnitude).find((n) => n >= raw) ?? raw;
  const ticks: number[] = [];
  for (let at = 0; at < totalMs; at += step) ticks.push(at);
  return ticks;
}

function Profile({ profile }: { readonly profile: ReturnType<typeof runProfile> }) {
  const cells: readonly (readonly [string, string, boolean])[] = [
    ['Duration', formatMs(profile.totalMs), false],
    ['Steps', String(profile.steps), false],
    ['Model calls', String(profile.modelCalls), false],
    ['Tool calls', String(profile.toolCalls), false],
    ['Revise laps', String(profile.reviseLaps), profile.reviseLaps > 0],
    ['Measured ends', `${profile.measured} of ${profile.steps}`, false],
  ];
  return (
    <dl className="rtl__kpis">
      {cells.map(([term, value, accent]) => (
        <div className="rtl__kpi" key={term} data-accent={accent || undefined}>
          <dt>{term}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function Legend() {
  const keys: readonly (readonly [StepKind | 'settled', string])[] = [
    ['model', 'Model call'],
    ['tool', 'No model time'],
    ['mount', 'Mounted workflow'],
    ['refusal', 'Refused'],
    ['settled', 'Spawn settled'],
  ];
  return (
    <div className="rtl__legend">
      {keys.map(([key, label]) => (
        <span key={key}>
          <i data-kind={key} />
          {label}
        </span>
      ))}
    </div>
  );
}

/**
 * The bar a key names, and the lane it is on.
 *
 * Exported for the payload pane the dock puts under this one
 * (`memory-and-replay` 59): two panes answering about *the same selected bar*
 * must not each decide for themselves which bar that is.
 */
export function findStep(
  lanes: readonly RunLane[],
  key: string | null,
): { lane: RunLane; step: TimelineStep } | null {
  if (key === null) return null;
  for (const lane of lanes) {
    const step = lane.steps.find((candidate) => candidate.key === key);
    if (step) return { lane, step };
  }
  return null;
}

/**
 * The line under the bars, which has to be true of every bar above it.
 *
 * Three states rather than two (`memory-and-replay` 57). A mount's bar is a
 * measured start and end — its `spawn` and its `settled`, both dated — so a
 * flat "not a measured start and end" became false about part of the chart
 * the moment rule 6 landed. Pure and exported so the claim is pinned by a
 * test rather than by a reader noticing.
 */
export function caveatFor(steps: readonly { measured: boolean }[], totalMs: number | null): string {
  if (totalMs === null) return 'This run reported no clock, so its steps have no durations.';
  return steps.some((step) => step.measured)
    ? 'Server time. A bar is a span between stream frames, except where the run dated both ends — those are marked measured.'
    : 'Server time, measured between stream frames — not a measured start and end.';
}
