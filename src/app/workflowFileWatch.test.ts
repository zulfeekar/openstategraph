import { describe, expect, it } from 'vitest';
import type { ToolCapability, WorkflowSummary } from '@core/runtime/WorkflowFileClient';
import {
  decideCapabilityRefresh,
  decideFileWatchAction,
  forgetKnownSavedAt,
  getKnownSavedAt,
  recordKnownSavedAt,
} from './workflowFileWatch';

const summary = (slug: string, savedAt: string): WorkflowSummary => ({
  slug,
  name: slug,
  savedAt,
  nodeCount: 0,
  edgeCount: 0,
});

const capability = (id: string): ToolCapability => ({
  id,
  name: id,
  description: `discovered tool ${id}`,
  argsSchema: {},
});

/**
 * Ticket 16's other half: noticing a `workflow.json` change made outside
 * this tab. `decideFileWatchAction` is the pure decision one poll makes;
 * the hook wrapping it (timers, network) is deliberately left untested at
 * the unit level, same as `useWorkflowSession`'s own thin React wiring.
 */
describe('decideFileWatchAction', () => {
  it('establishes a baseline on first observation, rather than treating it as a change', () => {
    const action = decideFileWatchAction([summary('a', 't1')], 'a', undefined);
    expect(action).toEqual({ kind: 'baseline', savedAt: 't1' });
  });

  it('does nothing when the observed savedAt matches what is known', () => {
    const action = decideFileWatchAction([summary('a', 't1')], 'a', 't1');
    expect(action).toEqual({ kind: 'none' });
  });

  it('flags an external change when the observed savedAt differs from what is known', () => {
    const action = decideFileWatchAction([summary('a', 't2')], 'a', 't1');
    expect(action).toEqual({ kind: 'notify-changed' });
  });

  it('flags a deletion when the slug is no longer in the list at all', () => {
    const action = decideFileWatchAction([summary('other', 't1')], 'a', 't1');
    expect(action).toEqual({ kind: 'notify-deleted' });
  });

  it('flags a deletion even before any baseline was ever recorded', () => {
    const action = decideFileWatchAction([], 'a', undefined);
    expect(action).toEqual({ kind: 'notify-deleted' });
  });
});

describe('recordKnownSavedAt / forgetKnownSavedAt', () => {
  it('a recorded value is what the next decision compares against', () => {
    recordKnownSavedAt('b', 't1');
    expect(decideFileWatchAction([summary('b', 't1')], 'b', 't1')).toEqual({ kind: 'none' });
  });

  it('ignores an undefined savedAt rather than recording a bogus baseline', () => {
    forgetKnownSavedAt('c');
    recordKnownSavedAt('c', undefined);
    // Still no baseline — this must read as "not yet observed", not as
    // "known to be undefined".
    const action = decideFileWatchAction([summary('c', 't1')], 'c', undefined);
    expect(action).toEqual({ kind: 'baseline', savedAt: 't1' });
  });

  it('forgetting a slug clears the baseline it had recorded', () => {
    recordKnownSavedAt('d', 't1');
    expect(getKnownSavedAt('d')).toBe('t1');

    forgetKnownSavedAt('d');

    expect(getKnownSavedAt('d')).toBeUndefined();
    expect(decideFileWatchAction([summary('d', 't1')], 'd', getKnownSavedAt('d'))).toEqual({
      kind: 'baseline',
      savedAt: 't1',
    });
  });
});

/**
 * Ticket 18's hot-reload gap: a new file in a workflow's `tools/` folder
 * doesn't touch `workflow.json`'s `savedAt` at all, so it needs its own
 * comparison sharing the same poll cadence `decideFileWatchAction` uses.
 */
describe('decideCapabilityRefresh', () => {
  it('establishes a baseline on first observation, rather than treating it as new', () => {
    const action = decideCapabilityRefresh([capability('a')], undefined);
    expect(action).toEqual({ kind: 'baseline', ids: ['a'] });
  });

  it('does nothing when the observed set matches what is known', () => {
    const action = decideCapabilityRefresh([capability('a'), capability('b')], ['a', 'b']);
    expect(action).toEqual({ kind: 'unchanged' });
  });

  it('is unchanged regardless of ordering — the backend promises no stable order', () => {
    const action = decideCapabilityRefresh([capability('b'), capability('a')], ['a', 'b']);
    expect(action).toEqual({ kind: 'unchanged' });
  });

  it('flags a newly discovered tool, naming it', () => {
    const action = decideCapabilityRefresh([capability('a'), capability('b')], ['a']);
    expect(action).toEqual({ kind: 'changed', ids: ['a', 'b'], added: ['b'] });
  });

  it('flags a removed tool too, even though nothing was added', () => {
    const action = decideCapabilityRefresh([capability('a')], ['a', 'b']);
    expect(action).toEqual({ kind: 'changed', ids: ['a'], added: [] });
  });

  it('an empty list is a real baseline, not skipped', () => {
    const action = decideCapabilityRefresh([], undefined);
    expect(action).toEqual({ kind: 'baseline', ids: [] });
  });
});
