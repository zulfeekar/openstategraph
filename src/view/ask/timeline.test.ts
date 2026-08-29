import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import {
  barOffsetPercent,
  barWidthPercent,
  buildTimeline,
  stepLabel,
  type TimelineRow,
} from './timeline';

/**
 * These fixtures were written when a row carried its own `durationMs`. The
 * fold reads the server's cumulative `elapsedMs` now (`launch-readiness` 108),
 * so a per-frame gap is still the natural way to *write* a run and is
 * accumulated into a clock here rather than restated by hand in every case.
 */
type Gap = Omit<TimelineRow, 'elapsedMs'> & { readonly durationMs: number };

const row = (patch: Partial<Gap> & { node: string }): Gap => ({
  taskId: null,
  internal: false,
  namespace: [],
  durationMs: 10,
  ...patch,
});

/** Per-frame gaps → the offsets a real stream carries. */
const stream = (gaps: readonly Gap[]): TimelineRow[] => {
  let clock = 0;
  return gaps.map(({ durationMs, ...rest }) => {
    clock += Number.isFinite(durationMs) ? Math.max(0, durationMs) : 0;
    return { ...rest, elapsedMs: clock };
  });
};

describe('buildTimeline', () => {
  it('is empty for a run that produced no frames', () => {
    // `null`, not `0`: a run that produced nothing did not take no time, it
    // reported no time. The same distinction the bars themselves now draw.
    expect(buildTimeline([])).toEqual({ steps: [], totalMs: null });
  });

  it('gives each node frame a bar, in the order it fired', () => {
    const { steps, totalMs } = buildTimeline(
      stream([
        row({ node: 'node:in1', durationMs: 5 }),
        row({ node: 'node:router1', durationMs: 20 }),
        row({ node: 'node:out1', durationMs: 15 }),
      ]),
    );

    expect(steps.map((step) => [step.label, step.order, step.startMs, step.durationMs])).toEqual([
      ['in1', 1, 0, 5],
      ['router1', 2, 5, 20],
      ['out1', 3, 25, 15],
    ]);
    expect(totalMs).toBe(40);
  });

  it('folds internal machinery onto the bar that owns it, never a bar of its own', () => {
    const { steps } = buildTimeline(
      stream([
        row({ node: 'node:agent', durationMs: 10 }),
        row({ node: 'tools', internal: true, durationMs: 30 }),
        row({ node: 'model', internal: true, durationMs: 60 }),
      ]),
    );

    expect(steps).toHaveLength(1);
    expect(steps[0]!.internalSteps).toBe(2);
    // The internal time is charged to the node, not lost.
    expect(steps[0]!.durationMs).toBe(100);
  });

  it('drops an internal frame that arrives before any node frame', () => {
    const { steps, totalMs } = buildTimeline(
      stream([row({ node: 'model', internal: true, durationMs: 7 })]),
    );
    expect(steps).toEqual([]);
    expect(totalMs).toBe(7);
  });

  it('collapses a subgraph namespace to one lane with a count', () => {
    const { steps } = buildTimeline(
      stream([
        row({ node: 'node:in1', durationMs: 5 }),
        row({ node: 'inner_a', namespace: ['wf_music:1'], durationMs: 10 }),
        row({ node: 'inner_b', namespace: ['wf_music:1'], durationMs: 20 }),
        row({ node: 'inner_c', namespace: ['wf_music:1'], durationMs: 30 }),
        row({ node: 'node:out1', durationMs: 5 }),
      ]),
    );

    expect(steps.map((step) => step.label)).toEqual(['in1', 'wf_music:1', 'out1']);
    expect(steps[1]!.count).toBe(3);
    expect(steps[1]!.durationMs).toBe(60);
    expect(steps[1]!.namespace).toBe('wf_music:1');
  });

  it('keeps two different namespaces in two lanes', () => {
    const { steps } = buildTimeline(
      stream([
        row({ node: 'a', namespace: ['team_x'] }),
        row({ node: 'b', namespace: ['team_y'] }),
      ]),
    );
    expect(steps.map((step) => step.label)).toEqual(['team_x', 'team_y']);
  });

  it('keeps concurrently dispatched workers apart by taskId', () => {
    const { steps } = buildTimeline(
      stream([
        row({ node: 'w', namespace: ['workers'], taskId: 't1' }),
        row({ node: 'w', namespace: ['workers'], taskId: 't2' }),
      ]),
    );
    expect(steps).toHaveLength(2);
    expect(steps.map((step) => step.taskId)).toEqual(['t1', 't2']);
  });

  it('shows a revise loop as repeated bars, numbered by visit', () => {
    const { steps } = buildTimeline(
      stream([
        row({ node: 'node:agent' }),
        row({ node: 'node:grader' }),
        row({ node: 'node:agent' }),
        row({ node: 'node:grader' }),
      ]),
    );

    expect(steps).toHaveLength(4);
    expect(steps.map((step) => [step.label, step.visit])).toEqual([
      ['agent', 1],
      ['grader', 1],
      ['agent', 2],
      ['grader', 2],
    ]);
    // Keys stay unique across laps, or React would collapse the loop away.
    expect(new Set(steps.map((step) => step.key)).size).toBe(4);
  });

  it('treats a missing or non-finite duration as zero rather than poisoning the clock', () => {
    const { steps, totalMs } = buildTimeline(
      stream([
        row({ node: 'a', durationMs: Number.NaN }),
        row({ node: 'b', durationMs: -5 }),
        row({ node: 'c', durationMs: 12 }),
      ]),
    );
    expect(steps.map((step) => step.durationMs)).toEqual([0, 0, 12]);
    expect(totalMs).toBe(12);
  });
});

describe('bar geometry', () => {
  it('lays bars out proportionally along the run', () => {
    const { steps, totalMs } = buildTimeline(
      stream([row({ node: 'a', durationMs: 25 }), row({ node: 'b', durationMs: 75 })]),
    );
    expect(barOffsetPercent(steps[0]!, totalMs)).toBe(0);
    expect(barWidthPercent(steps[0]!, totalMs)).toBe(25);
    expect(barOffsetPercent(steps[1]!, totalMs)).toBe(25);
    expect(barWidthPercent(steps[1]!, totalMs)).toBe(75);
  });

  it('floors a near-instant step so it stays visible', () => {
    const { steps, totalMs } = buildTimeline(
      stream([row({ node: 'a', durationMs: 0 }), row({ node: 'b', durationMs: 10000 })]),
    );
    expect(barWidthPercent(steps[0]!, totalMs)).toBe(1.5);
  });

  it('falls back to a full bar when a run reported no time at all', () => {
    const { steps, totalMs } = buildTimeline(stream([row({ node: 'a', durationMs: 0 })]));
    expect(totalMs).toBe(0);
    expect(barWidthPercent(steps[0]!, totalMs)).toBe(100);
    expect(barOffsetPercent(steps[0]!, totalMs)).toBe(0);
  });
});

describe('stepLabel', () => {
  it('strips the canvas id prefix and leaves everything else alone', () => {
    expect(stepLabel('node:agent1')).toBe('agent1');
    expect(stepLabel('wf_music')).toBe('wf_music');
  });
});

describe('spawn rows', () => {
  const spawnRow = (patch: Partial<Gap> & { label: string }): Gap => ({
    node: 'node:orch',
    taskId: null,
    internal: false,
    namespace: [],
    durationMs: 0,
    ...patch,
    spawn: { kind: 'fanout', label: patch.label, instruction: 'do a thing' },
  });

  it('never gets a bar of its own', () => {
    const { steps } = buildTimeline(
      stream([
        row({ node: 'node:orch', durationMs: 10 }),
        spawnRow({ label: 'researcher', taskId: 't1' }),
      ]),
    );
    expect(steps).toHaveLength(1);
    expect(steps[0]!.label).toBe('orch');
  });

  it('names a dispatched worker lane after the child it announced', () => {
    const { steps } = buildTimeline(
      stream([
        spawnRow({ label: 'researcher', taskId: 't1' }),
        spawnRow({ label: 'analyst', taskId: 't2' }),
        row({ node: 'node:worker', taskId: 't1', durationMs: 20 }),
        row({ node: 'node:worker', taskId: 't2', durationMs: 30 }),
      ]),
    );
    expect(steps.map((s) => s.label)).toEqual(['researcher', 'analyst']);
  });

  it('names a subgraph lane after the mounted child, not the checkpoint id', () => {
    const { steps } = buildTimeline(
      stream([
        spawnRow({ label: 'wf_music', namespace: ['wf_music:abc123'] }),
        row({ node: 'node:a', namespace: ['wf_music:abc123'], durationMs: 20 }),
        row({ node: 'node:b', namespace: ['wf_music:abc123'], durationMs: 5 }),
      ]),
    );
    expect(steps).toHaveLength(1);
    expect(steps[0]!.label).toBe('wf_music');
    expect(steps[0]!.namespace).toBe('wf_music:abc123');
    expect(steps[0]!.count).toBe(2);
  });

  it('leaves a lane with the bare namespace when nothing announced it', () => {
    const { steps } = buildTimeline(
      stream([row({ node: 'node:a', namespace: ['wf_music:abc123'], durationMs: 20 })]),
    );
    expect(steps[0]!.label).toBe('wf_music:abc123');
  });
});

/**
 * The header states whose limitation the inferred clock is, and the answer
 * changed (`memory-and-replay` 48).
 *
 * Until 2026-08-29 the docstring above `buildTimeline`'s module attributed
 * the missing start event to LangGraph. LangGraph emits one — `TasksStreamPart`
 * carries a task **start** and a task **finish**, and the start is minted
 * before the node runs. The backend asks for three of the seven stream modes
 * and has never asked for that one, which makes the gap a subscription we did
 * not make rather than a library that cannot help.
 *
 * A comment cannot fail on its own, and this one was wrong for as long as it
 * existed, so the corrected version is pinned here — the same move
 * `backend/tests/test_a_library_default_is_never_literalised.py` makes for
 * every other library claim this repository states.
 */
describe('the timeline header, on whose limitation this is', () => {
  const header = readFileSync(fileURLToPath(new URL('./timeline.ts', import.meta.url)), 'utf8');

  it('does not claim the library reports no start event', () => {
    expect(header).not.toMatch(/there is no start event to subtract/);
  });

  it('names the mode that does carry one, so the correction is actionable', () => {
    expect(header).toMatch(/stream_mode="tasks"/);
  });

  it('says the start event carries no clock, so 46 is not made unnecessary', () => {
    expect(header).toMatch(/does \*not\* carry is a clock/);
  });
});
