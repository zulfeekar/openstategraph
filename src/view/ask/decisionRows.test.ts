import { describe, expect, it } from 'vitest';
import { decisionRows } from './decisionRows';

/**
 * `launch-readiness/175` on the surface that actually reads it.
 *
 * The panel's decision rows are the run's *record*, and they printed one label
 * per router — so a run where a `matchMode: "all"` classifier opened two desks
 * and a run where it opened one produced identical rows, while both desks'
 * answers were in `outputs`.
 */
describe('the decision rows beside an answer', () => {
  it('names every branch a parallel router matched', () => {
    const rows = decisionRows({
      decisions: { router1: 'b-cost' },
      routes: { router1: ['b-cost', 'b-risk'] },
    });

    expect(rows).toEqual([{ nodeId: 'router1', branch: 'b-cost + b-risk' }]);
  });

  it('leaves a single-branch router reading exactly as it always did', () => {
    const rows = decisionRows({
      decisions: { router1: 'b-risk' },
      routes: { router1: ['b-risk'] },
    });

    expect(rows).toEqual([{ nodeId: 'router1', branch: 'b-risk' }]);
  });

  it('tells the two runs apart, which is the whole ticket', () => {
    const both = decisionRows({
      decisions: { router1: 'b-cost' },
      routes: { router1: ['b-cost', 'b-risk'] },
    });
    const one = decisionRows({ decisions: { router1: 'b-cost' }, routes: { router1: ['b-cost'] } });

    expect(both[0]?.branch).not.toEqual(one[0]?.branch);
  });

  it('leaves a grader alone — it has no branches to report', () => {
    const rows = decisionRows({
      decisions: { grader1: 'pass', router1: 'b-cost' },
      routes: { router1: ['b-cost', 'b-risk'] },
    });

    expect(rows).toEqual([
      { nodeId: 'grader1', branch: 'pass' },
      { nodeId: 'router1', branch: 'b-cost + b-risk' },
    ]);
  });

  it('falls back to the dispatched label when no row reached this client', () => {
    // An older server, or a payload this client could not read. The row it
    // used to print is still the right one to print.
    const rows = decisionRows({ decisions: { 'node:router1': 'b-cost' }, routes: {} });

    expect(rows).toEqual([{ nodeId: 'router1', branch: 'b-cost' }]);
  });
});
