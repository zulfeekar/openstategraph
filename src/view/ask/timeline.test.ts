import { describe, expect, it } from 'vitest';
import {
  barOffsetPercent,
  barWidthPercent,
  buildTimeline,
  stepLabel,
  type TimelineRow,
} from './timeline';

const row = (patch: Partial<TimelineRow> & { node: string }): TimelineRow => ({
  taskId: null,
  internal: false,
  namespace: [],
  durationMs: 10,
  ...patch,
});

describe('buildTimeline', () => {
  it('is empty for a run that produced no frames', () => {
    expect(buildTimeline([])).toEqual({ steps: [], totalMs: 0 });
  });

  it('gives each node frame a bar, in the order it fired', () => {
    const { steps, totalMs } = buildTimeline([
      row({ node: 'node:in1', durationMs: 5 }),
      row({ node: 'node:router1', durationMs: 20 }),
      row({ node: 'node:out1', durationMs: 15 }),
    ]);

    expect(steps.map((step) => [step.label, step.order, step.startMs, step.durationMs])).toEqual([
      ['in1', 1, 0, 5],
      ['router1', 2, 5, 20],
      ['out1', 3, 25, 15],
    ]);
    expect(totalMs).toBe(40);
  });

  it('folds internal machinery onto the bar that owns it, never a bar of its own', () => {
    const { steps } = buildTimeline([
      row({ node: 'node:agent', durationMs: 10 }),
      row({ node: 'tools', internal: true, durationMs: 30 }),
      row({ node: 'model', internal: true, durationMs: 60 }),
    ]);

    expect(steps).toHaveLength(1);
    expect(steps[0]!.internalSteps).toBe(2);
    // The internal time is charged to the node, not lost.
    expect(steps[0]!.durationMs).toBe(100);
  });

  it('drops an internal frame that arrives before any node frame', () => {
    const { steps, totalMs } = buildTimeline([
      row({ node: 'model', internal: true, durationMs: 7 }),
    ]);
    expect(steps).toEqual([]);
    expect(totalMs).toBe(7);
  });

  it('collapses a subgraph namespace to one lane with a count', () => {
    const { steps } = buildTimeline([
      row({ node: 'node:in1', durationMs: 5 }),
      row({ node: 'inner_a', namespace: ['wf_music:1'], durationMs: 10 }),
      row({ node: 'inner_b', namespace: ['wf_music:1'], durationMs: 20 }),
      row({ node: 'inner_c', namespace: ['wf_music:1'], durationMs: 30 }),
      row({ node: 'node:out1', durationMs: 5 }),
    ]);

    expect(steps.map((step) => step.label)).toEqual(['in1', 'wf_music:1', 'out1']);
    expect(steps[1]!.count).toBe(3);
    expect(steps[1]!.durationMs).toBe(60);
    expect(steps[1]!.namespace).toBe('wf_music:1');
  });

  it('keeps two different namespaces in two lanes', () => {
    const { steps } = buildTimeline([
      row({ node: 'a', namespace: ['team_x'] }),
      row({ node: 'b', namespace: ['team_y'] }),
    ]);
    expect(steps.map((step) => step.label)).toEqual(['team_x', 'team_y']);
  });

  it('keeps concurrently dispatched workers apart by taskId', () => {
    const { steps } = buildTimeline([
      row({ node: 'w', namespace: ['workers'], taskId: 't1' }),
      row({ node: 'w', namespace: ['workers'], taskId: 't2' }),
    ]);
    expect(steps).toHaveLength(2);
    expect(steps.map((step) => step.taskId)).toEqual(['t1', 't2']);
  });

  it('shows a revise loop as repeated bars, numbered by visit', () => {
    const { steps } = buildTimeline([
      row({ node: 'node:agent' }),
      row({ node: 'node:grader' }),
      row({ node: 'node:agent' }),
      row({ node: 'node:grader' }),
    ]);

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
    const { steps, totalMs } = buildTimeline([
      row({ node: 'a', durationMs: Number.NaN }),
      row({ node: 'b', durationMs: -5 }),
      row({ node: 'c', durationMs: 12 }),
    ]);
    expect(steps.map((step) => step.durationMs)).toEqual([0, 0, 12]);
    expect(totalMs).toBe(12);
  });
});

describe('bar geometry', () => {
  it('lays bars out proportionally along the run', () => {
    const { steps, totalMs } = buildTimeline([
      row({ node: 'a', durationMs: 25 }),
      row({ node: 'b', durationMs: 75 }),
    ]);
    expect(barOffsetPercent(steps[0]!, totalMs)).toBe(0);
    expect(barWidthPercent(steps[0]!, totalMs)).toBe(25);
    expect(barOffsetPercent(steps[1]!, totalMs)).toBe(25);
    expect(barWidthPercent(steps[1]!, totalMs)).toBe(75);
  });

  it('floors a near-instant step so it stays visible', () => {
    const { steps, totalMs } = buildTimeline([
      row({ node: 'a', durationMs: 0 }),
      row({ node: 'b', durationMs: 10000 }),
    ]);
    expect(barWidthPercent(steps[0]!, totalMs)).toBe(1.5);
  });

  it('falls back to a full bar when a run reported no time at all', () => {
    const { steps, totalMs } = buildTimeline([row({ node: 'a', durationMs: 0 })]);
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
