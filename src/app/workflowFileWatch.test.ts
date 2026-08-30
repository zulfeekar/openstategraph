import { describe, expect, it } from 'vitest';
import type { WorkflowSummary } from '@core/runtime/WorkflowFileClient';
import {
  decideFileWatchAction,
  forgetKnownSavedAt,
  getKnownSavedAt,
  recordKnownSavedAt,
} from './workflowFileWatch';

const summary = (slug: string, savedAt: string, hidden = false): WorkflowSummary => ({
  slug,
  name: slug,
  published: true,
  savedAt,
  nodeCount: 0,
  edgeCount: 0,
  hidden,
  findings: [],
});

/**
 * Ticket 16's other half: noticing a `workflow.json` change made outside
 * this tab. `decideFileWatchAction` is the pure decision one poll makes;
 * the hook wrapping it (timers, network) is deliberately left untested at
 * the unit level, same as `useWorkflowSession`'s own thin React wiring.
 */
describe('decideFileWatchAction', () => {
  it('establishes a baseline on first observation, rather than treating it as a change', () => {
    const action = decideFileWatchAction(summary('a', 't1'), undefined);
    expect(action).toEqual({ kind: 'baseline', savedAt: 't1' });
  });

  it('does nothing when the observed savedAt matches what is known', () => {
    const action = decideFileWatchAction(summary('a', 't1'), 't1');
    expect(action).toEqual({ kind: 'none' });
  });

  it('flags an external change when the observed savedAt differs from what is known', () => {
    const action = decideFileWatchAction(summary('a', 't2'), 't1');
    expect(action).toEqual({ kind: 'notify-changed' });
  });

  it('flags a deletion when the backend reports no such workflow', () => {
    const action = decideFileWatchAction(null, 't1');
    expect(action).toEqual({ kind: 'notify-deleted' });
  });

  it('flags a deletion even before any baseline was ever recorded', () => {
    const action = decideFileWatchAction(null, undefined);
    expect(action).toEqual({ kind: 'notify-deleted' });
  });

  /**
   * Ticket 21, the whole point. A hidden package (`concierge`,
   * `workflow-architect`) is absent from `GET /api/workflows?surface=editor`
   * and present on disk. This function used to be handed that listing and
   * concluded "deleted"; it is now handed the answer to an existence
   * question, and hidden is simply another existing workflow.
   */
  it('does NOT flag a deletion for a hidden workflow — invisible is not absent', () => {
    expect(decideFileWatchAction(summary('concierge', 't1', true), undefined)).toEqual({
      kind: 'baseline',
      savedAt: 't1',
    });
    expect(decideFileWatchAction(summary('concierge', 't1', true), 't1')).toEqual({ kind: 'none' });
    expect(decideFileWatchAction(summary('concierge', 't2', true), 't1')).toEqual({
      kind: 'notify-changed',
    });
  });

  it('says nothing about a package it cannot date — mid-write is not deleted, nor changed', () => {
    expect(decideFileWatchAction(summary('a', ''), 't1')).toEqual({ kind: 'none' });
    expect(decideFileWatchAction(summary('a', ''), undefined)).toEqual({ kind: 'none' });
  });
});

describe('recordKnownSavedAt / forgetKnownSavedAt', () => {
  it('a recorded value is what the next decision compares against', () => {
    recordKnownSavedAt('b', 't1');
    expect(decideFileWatchAction(summary('b', 't1'), 't1')).toEqual({ kind: 'none' });
  });

  it('ignores an undefined savedAt rather than recording a bogus baseline', () => {
    forgetKnownSavedAt('c');
    recordKnownSavedAt('c', undefined);
    // Still no baseline — this must read as "not yet observed", not as
    // "known to be undefined".
    const action = decideFileWatchAction(summary('c', 't1'), undefined);
    expect(action).toEqual({ kind: 'baseline', savedAt: 't1' });
  });

  it('forgetting a slug clears the baseline it had recorded', () => {
    recordKnownSavedAt('d', 't1');
    expect(getKnownSavedAt('d')).toBe('t1');

    forgetKnownSavedAt('d');

    expect(getKnownSavedAt('d')).toBeUndefined();
    expect(decideFileWatchAction(summary('d', 't1'), getKnownSavedAt('d'))).toEqual({
      kind: 'baseline',
      savedAt: 't1',
    });
  });
});
