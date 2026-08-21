import { describe, expect, it } from 'vitest';
import { buildTrace, type ActivityRow } from './traceTree';
import { formatDuration } from './traceDuration';

/**
 * The row fixture is a real `chinook-assistant` revision loop, captured off
 * `POST /api/runs/stream` on 2026-08-21 and reduced to the gaps: router, then
 * three visits of `agent-sql` each followed by a visit of `grader-sql`. The
 * numbers are the wire's own, so this is the shape ticket 84 reported, not an
 * invented one.
 */
const step = (node: string, durationMs: number, internal: boolean, owner = node): ActivityRow => ({
  node,
  taskId: null,
  internal,
  durationMs,
  output: null,
  path: [owner],
  activeNode: owner,
});

/** One agent visit: its inner loop, then its own completion frame. */
const agentVisit = (steps: readonly number[], own: number): ActivityRow[] => [
  ...steps.map((ms) => step('model', ms, true, 'agent-sql')),
  step('agent-sql', own, false),
];

/** A grader that called a model — the ordinary revising path. */
const modelGrader = (ms: number) => step('grader-sql', ms, false);

/** A grader that rejected deterministically: empty candidate, no model call.
 * `BaseGrader.deterministic_checks` returns in ~0.02 ms, which the stream's
 * whole-millisecond rounding delivers as exactly `0`. */
const instantGrader = () => step('grader-sql', 0, false);

const label = (rows: readonly ActivityRow[]) =>
  buildTrace(rows).map((node) => `${node.node} ${formatDuration(node.durationMs)}`);

describe('a grader row in a revision loop', () => {
  it('prints the time a model-calling grader actually took, on every visit', () => {
    const rows: ActivityRow[] = [
      step('router1', 516, false),
      ...agentVisit([514, 774], 3),
      modelGrader(1320),
      ...agentVisit([1640, 1573], 1),
      modelGrader(2024),
      ...agentVisit([617, 1104], 1),
      modelGrader(922),
      step('out1', 2, false),
    ];

    expect(label(rows)).toEqual([
      'router1 516 ms',
      'agent-sql 1291 ms',
      'grader-sql 1320 ms',
      'agent-sql 3214 ms',
      'grader-sql 2024 ms',
      'agent-sql 1722 ms',
      'grader-sql 922 ms',
      'out1 2 ms',
    ]);
  });

  it('never renders a measured step as a confident `0 ms`', () => {
    // The reported run: the agent produced nothing, so the grader rejected on
    // its deterministic empty-answer check and never reached a model.
    const rows: ActivityRow[] = [
      step('router1', 536, false),
      ...agentVisit([1200, 1240], 0),
      instantGrader(),
      ...agentVisit([2040, 2046], 0),
      instantGrader(),
    ];

    const printed = label(rows);
    expect(printed).not.toContain('grader-sql 0 ms');
    expect(printed.filter((row) => row.startsWith('grader-sql'))).toEqual([
      'grader-sql <1 ms',
      'grader-sql <1 ms',
    ]);
  });

  it('says nothing confident about a duration it cannot read', () => {
    expect(formatDuration(Number.NaN)).toBe('—');
    expect(formatDuration(-1)).toBe('—');
  });
});
