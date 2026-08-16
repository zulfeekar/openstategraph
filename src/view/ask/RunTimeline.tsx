import { useMemo } from 'react';
import { barOffsetPercent, barWidthPercent, buildTimeline, type TimelineRow } from './timeline';

/**
 * The run timeline.
 *
 * Thin bars on a shared track, one per fired step, laid out on the run's own
 * clock — so the shape of a run is readable at a glance: which step dominated,
 * where the gaps were, how many laps a revise loop took.
 *
 * Deliberately no chart library. This is a flex row with two percentages; a
 * charting dependency would be several hundred kilobytes to draw a rectangle,
 * and would bring its own colours into a design system that already has some.
 *
 * Muted monochrome plus one accent: the bar's *position and length* carry the
 * data, so colour is spent only where it means something — the currently
 * running step, and the extra laps of a loop.
 */
export function RunTimeline({
  rows,
  running = false,
}: {
  rows: readonly TimelineRow[];
  readonly running?: boolean;
}) {
  // See the note in `Activity`: same pure fold, same per-frame re-render, so
  // the same cache. `rows` identity changes only for the streaming turn.
  const { steps, totalMs } = useMemo(() => buildTimeline(rows), [rows]);

  if (steps.length === 0) {
    return <p className="ask__meta">No steps have fired yet.</p>;
  }

  const last = steps[steps.length - 1];

  return (
    <div className="timeline">
      <div className="timeline__head">
        <span>
          {steps.length} step{steps.length === 1 ? '' : 's'}
        </span>
        <span className="timeline__total">{formatMs(totalMs)}</span>
      </div>

      <ol className="timeline__lanes">
        {steps.map((step) => (
          <li
            key={step.key}
            className="timeline__lane"
            data-live={running && step === last ? 'true' : undefined}
            data-repeat={step.visit > 1 ? 'true' : undefined}
          >
            <span className="timeline__order">{step.order}</span>
            {/* Only the two facts that change how a bar should be *read* get a
                badge — this lane is one of several visits, or it is a whole
                subgraph folded into one. Internal step counts and a worker's
                task id matter, but not enough to spend width on in a 300px
                panel, so they live in the tooltip. */}
            <span className="timeline__label" title={describe(step)}>
              <span className="timeline__name">{step.label}</span>
              {step.visit > 1 ? <span className="timeline__badge">×{step.visit}</span> : null}
              {step.namespace ? <span className="timeline__badge">⊞{step.count}</span> : null}
            </span>
            <span className="timeline__track">
              <span
                className="timeline__bar"
                style={{
                  marginInlineStart: `${barOffsetPercent(step, totalMs)}%`,
                  width: `${barWidthPercent(step, totalMs)}%`,
                }}
              />
            </span>
            <span className="timeline__ms">{formatMs(step.durationMs)}</span>
          </li>
        ))}
      </ol>

      {/* Said plainly, once, rather than implied by a precise-looking number:
          the backend reports a node only after it finishes, so these are gaps
          between frames, not measured spans. */}
      <p className="timeline__caveat">
        Durations are gaps between stream frames, not measured spans.
      </p>
    </div>
  );
}

/** Everything about a bar that the row itself has no room to say. */
function describe(step: {
  label: string;
  visit: number;
  namespace: string | null;
  count: number;
  internalSteps: number;
  taskId: string | null;
}): string {
  const parts = [step.label];
  if (step.visit > 1) parts.push(`visit ${step.visit}`);
  // "mount", not "subgraph": the settled lexicon, and the compiler emits no
  // LangGraph subgraph anyway (consistency-sweep ticket 10).
  if (step.namespace) parts.push(`${step.count} steps inside this mount`);
  if (step.internalSteps > 0) parts.push(`${step.internalSteps} internal steps`);
  if (step.taskId) parts.push(`task ${step.taskId}`);
  return parts.join(' · ');
}

function formatMs(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`;
}
