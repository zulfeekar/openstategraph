import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Err, Ok } from '@core/kernel/Result';
import type { WorkflowSummary } from '@core/runtime/WorkflowFileClient';
import {
  BLIND_AFTER_FAILED_POLLS,
  IN_TOUCH,
  type WatchReach,
  decideWatchStep,
  forgetKnownSavedAt,
  getWatchReach,
  publishWatchReach,
  subscribeWatchReach,
} from './workflowFileWatch';

const summary = (slug: string, savedAt: string): WorkflowSummary => ({
  slug,
  name: slug,
  published: true,
  savedAt,
  nodeCount: 0,
  edgeCount: 0,
  hidden: false,
});

const failed = Err('TypeError: Failed to fetch');

/** Feed a sequence of polls through the pure step and collect what it said. */
function run(
  outcomes: readonly (WorkflowSummary | null | 'fail')[],
  known: string | undefined,
): { readonly reach: WatchReach; readonly actions: readonly string[] } {
  let reach = IN_TOUCH;
  const actions: string[] = [];
  for (const outcome of outcomes) {
    const step = decideWatchStep(outcome === 'fail' ? failed : Ok(outcome), known, reach);
    reach = step.reach;
    actions.push(step.action.kind);
  }
  return { reach, actions };
}

/**
 * `say-it-on-the-surface/07` — deleted, unreachable and healthy looked the
 * same.
 *
 * The watch acted only `if (outcome.ok)` and had no `else`, so a poll that
 * could not reach the backend was indistinguishable from one that reached it
 * and found nothing wrong. Staged live on 2026-08-28 by shimming `fetch` to
 * reject `/api/workflows/<slug>/summary`: **nine consecutive failed polls over
 * ~45 s produced zero DOM mutations and no toast**, with Save and Publish both
 * live and promising to write a file nothing had been able to see.
 *
 * A watch that goes quiet when it cannot see is a watch that reports "fine"
 * when it means "blind". These pin the *blind* path specifically — a suite
 * that only exercises successful polls stays green against exactly this
 * defect, which is how it survived to a beta bar.
 */
describe('a watch that cannot reach the backend', () => {
  it('does not let a failed poll read as a clean one', () => {
    const step = decideWatchStep(failed, 't1', IN_TOUCH);
    // The reach is the observable that separates the two. Before this ticket
    // there was none, and `none` was the whole answer.
    expect(step.reach).not.toEqual(IN_TOUCH);
    expect(step.reach.consecutiveFailures).toBe(1);
    // And it must never be mistaken for evidence about the file itself.
    expect(step.action.kind).not.toBe('baseline');
    expect(step.action.kind).not.toBe('notify-deleted');
    expect(step.action.kind).not.toBe('notify-changed');
  });

  it('says nothing about a single failed poll, which is not an outage', () => {
    const { reach, actions } = run(['fail'], 't1');
    expect(actions).toEqual(['none']);
    expect(reach.blind).toBe(false);
  });

  it('stays quiet right up to the threshold', () => {
    const shortOfIt = Array.from({ length: BLIND_AFTER_FAILED_POLLS - 1 }, () => 'fail' as const);
    const { reach, actions } = run(shortOfIt, 't1');
    expect(actions.every((kind) => kind === 'none')).toBe(true);
    expect(reach.blind).toBe(false);
  });

  it('says so once the failures are continuous enough to be an outage', () => {
    const upToIt = Array.from({ length: BLIND_AFTER_FAILED_POLLS }, () => 'fail' as const);
    const { reach, actions } = run(upToIt, 't1');
    expect(actions.at(-1)).toBe('notify-blind');
    expect(reach.blind).toBe(true);
  });

  it('says it once, not nine times — the audit staged nine', () => {
    const nine = Array.from({ length: 9 }, () => 'fail' as const);
    const { reach, actions } = run(nine, 't1');
    expect(actions.filter((kind) => kind === 'notify-blind')).toHaveLength(1);
    expect(reach.blind).toBe(true);
    expect(reach.consecutiveFailures).toBe(9);
  });

  it('never cries wolf over a connection that answers even one poll in three', () => {
    // The threshold counts *consecutive* failures, so a flapping link that
    // lands a single successful poll never accumulates. This is the whole
    // defence against the panel that cries wolf.
    const flapping = ['fail', 'fail', summary('a', 't1'), 'fail', 'fail', summary('a', 't1')];
    const { reach, actions } = run(flapping as never, 't1');
    expect(actions).not.toContain('notify-blind');
    expect(reach.blind).toBe(false);
  });

  it('says when it can see again, rather than leaving a stale alarm on screen', () => {
    let reach = IN_TOUCH;
    for (let i = 0; i < BLIND_AFTER_FAILED_POLLS; i += 1) {
      reach = decideWatchStep(failed, 't1', reach).reach;
    }
    expect(reach.blind).toBe(true);

    const back = decideWatchStep(Ok(summary('a', 't1')), 't1', reach);
    expect(back.action.kind).toBe('notify-back-in-touch');
    expect(back.reach).toEqual(IN_TOUCH);
  });

  it('reports what it found instead, when what it found is more than "back"', () => {
    // A workflow deleted *while* the watch was blind: contact being restored
    // is implied by the deletion notice, and `notify-deleted` is the verdict
    // with a consequence (launch-readiness 147 disarms the writer on it).
    let reach = IN_TOUCH;
    for (let i = 0; i < BLIND_AFTER_FAILED_POLLS; i += 1) {
      reach = decideWatchStep(failed, 't1', reach).reach;
    }
    const back = decideWatchStep(Ok(null), 't1', reach);
    expect(back.action.kind).toBe('notify-deleted');
    // The marker still clears — the reach is what the surface reads.
    expect(back.reach).toEqual(IN_TOUCH);
  });

  it('keeps deciding about the file exactly as it always did while in touch', () => {
    expect(decideWatchStep(Ok(summary('a', 't1')), undefined, IN_TOUCH).action).toEqual({
      kind: 'baseline',
      savedAt: 't1',
    });
    expect(decideWatchStep(Ok(summary('a', 't2')), 't1', IN_TOUCH).action).toEqual({
      kind: 'notify-changed',
    });
    expect(decideWatchStep(Ok(null), 't1', IN_TOUCH).action).toEqual({ kind: 'notify-deleted' });
  });
});

/**
 * The reach is published because the *persistent* half of telling the three
 * states apart is on the toolbar, not in a toast — a toast fades after five
 * seconds and the ticket's complaint is precisely that what survives the fade
 * is identical in all three states.
 */
describe('the published reach', () => {
  beforeEach(() => {
    publishWatchReach(IN_TOUCH);
    forgetKnownSavedAt('a');
  });

  it('starts in touch, because silence before the first poll is not an outage', () => {
    expect(getWatchReach()).toEqual(IN_TOUCH);
  });

  it('tells subscribers when it changes, and only then', () => {
    const listener = vi.fn();
    const off = subscribeWatchReach(listener);
    publishWatchReach({ consecutiveFailures: 1, blind: false });
    expect(listener).toHaveBeenCalledTimes(1);
    publishWatchReach({ consecutiveFailures: 1, blind: false });
    expect(listener).toHaveBeenCalledTimes(1);
    publishWatchReach({ consecutiveFailures: 4, blind: true });
    expect(listener).toHaveBeenCalledTimes(2);
    off();
    publishWatchReach(IN_TOUCH);
    expect(listener).toHaveBeenCalledTimes(2);
  });
});
