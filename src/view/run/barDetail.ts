import type { RunLane, StepKind, TimelineStep } from '../ask/timeline';

/**
 * The pane beside the chart: what the selected bar is, in the run's own words.
 *
 * `memory-and-replay` 58, ported from the design prototype. Pure and
 * framework-free so the honesty rules below are unit-tested rather than
 * eyeballed in a rendered panel — `vitest` runs `src/**\/*.test.ts` in `node`,
 * which is the reason every decidable part of this surface is a `.ts` module
 * and only the JSX is a `.tsx`.
 *
 * **What this pane is not, yet.** The prototype showed the selected step's
 * *payload* — what it **asked** and what it **produced**, worded per node
 * family: a router's routes and decision, a supervisor's subtasks by id, a
 * grader's verdict and reason, a mount's nested outputs. `ActivityRow.output`
 * carries one opaque string and the fold does not keep it, so building that
 * here would mean inventing per-family readings from a field that has none.
 * Filed as `memory-and-replay` 59 and deliberately absent rather than faked.
 */
export interface BarFact {
  readonly term: string;
  readonly value: string;
}

/**
 * One sentence per bar kind — the prototype's `WHY` map, kept because it is
 * content rather than scaffolding: it is where a reader learns that hollow
 * means *no model time was spent here* rather than *something is missing*.
 */
export const WHY: Readonly<Record<StepKind, string>> = {
  model:
    'A model call. The bar spans the frames this node owned — attributed by the ' +
    "server's own `activeNode`, not by whichever bar happened to be open.",
  tool:
    'No model time was spent in this bar. Hollow, with the node’s own ink as a ring — ' +
    'an input, an output, a join, or a loop that only reached for tools.',
  mount:
    'A mounted workflow — another package run as one isolated step. Its own nodes fold ' +
    'into this bar, and the run dated both of its ends.',
  refusal:
    'A refusal: a deterministic check rejected the candidate before any model was asked. ' +
    'It is the one place this design spends its accent.',
};

/** A dash, never a zero, for a span nobody measured — `launch-readiness` 108. */
export function formatMs(ms: number | null): string {
  if (ms === null) return '—';
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`;
}

/**
 * The selected bar, as terms and values.
 *
 * Three of these can be unknown and each says so as `—` rather than as a
 * number. **Closed** is the load-bearing one: a bar with no end is not a bar
 * that ended at its start, and on an open-ended lane it says which *kind* of
 * open the run recorded (`50`'s `ending`) instead of a time.
 */
export function barFacts(lane: RunLane, step: TimelineStep): readonly BarFact[] {
  const end =
    step.startMs !== null && step.durationMs !== null ? step.startMs + step.durationMs : null;
  const facts: BarFact[] = [
    { term: 'Node', value: step.label },
    { term: 'Lane', value: laneCaption(lane) },
    { term: 'What', value: WHAT[step.kind] },
    { term: 'Opened', value: formatMs(step.startMs) },
    { term: 'Closed', value: end === null ? closedUnknown(lane) : formatMs(end) },
    { term: 'Span', value: formatMs(step.durationMs) },
    {
      term: 'Ends',
      value: step.measured
        ? 'both dated by the run'
        : 'a span between the frames that arrived, not a measured start and end',
    },
  ];
  if (step.visit > 1) facts.push({ term: 'Lap', value: `visit ${step.visit} of this node` });
  if (step.internalSteps > 0) {
    facts.push({ term: 'Inside', value: `${step.internalSteps} internal steps` });
  }
  if (step.concurrent.length > 0) {
    const others = step.concurrent.length;
    // "at least", always: `concurrent` is a floor and never a ceiling, because
    // two span-attributed bars are laid end to end by construction and can
    // never be *found* to overlap even when they did.
    facts.push({
      term: 'Alongside',
      value: `at least ${others} other bar${others === 1 ? '' : 's'}`,
    });
  }
  if (step.taskId) facts.push({ term: 'Task', value: step.taskId });
  return facts;
}

const WHAT: Readonly<Record<StepKind, string>> = {
  model: 'a model call',
  tool: 'no model time',
  mount: 'a mounted workflow',
  refusal: 'a refusal',
};

/** Why a bar has no end — a statement about the recording, not about the work. */
function closedUnknown(lane: RunLane): string {
  if (!lane.openEnded) return '—';
  if (lane.ending === 'detached') return 'never — still running outside this run';
  if (lane.ending === 'unknown') return 'the recording ended owing an account';
  if (lane.ending === 'error') return 'never ran';
  return 'not yet';
}

/** How the lane names itself, siblings and all. */
export function laneCaption(lane: RunLane): string {
  const sibling = lane.sibling ? ` ${lane.sibling.index} of ${lane.sibling.of}` : '';
  return `${lane.name}${sibling}`;
}
