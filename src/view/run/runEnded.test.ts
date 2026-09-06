import { describe, expect, it } from 'vitest';

import type { RunUsage } from '@core/runtime/RuntimeClient';

import type { ActivityRow } from '../ask/traceTree';

import { runEnded } from './runEnded';
import { RunViewStore, type RunView } from './runView';

/**
 * *A run just ended*, decided from the snapshot rather than from a dead event.
 *
 * `stable-beta-public/14`. The shell's toast and the token bar's refresh were
 * both hung off `workbench.engine`'s `run:finish`, and nothing in the shipped
 * app calls `engine.run()` any more — so both listeners were correct, tested,
 * and never once invoked. The one source of "a run ended" the shell already
 * has is the `runView` snapshot the dock is drawn from, and a transition needs
 * two snapshots, which is why this is a pure function of *before* and *after*
 * rather than a predicate on one.
 *
 * Tested here and not in the shell for the reason `useSpend.test.ts` states:
 * `vite.config.ts` runs on `node` with no DOM, so what a hook does is proven
 * in the browser and what it *decides* is proven as a function.
 */
const ROWS: readonly ActivityRow[] = [];

/** One model's row, of which only `model` and `totalTokens` are read here. */
function spent(model: string, totalTokens: number): RunUsage {
  return { model, inputTokens: 0, outputTokens: totalTokens, totalTokens };
}

function live(over: Partial<RunView> = {}): RunView {
  return {
    source: 'live',
    question: 'What did it cost?',
    rows: ROWS,
    running: false,
    threadId: 'thread-1',
    usage: null,
    ...over,
  };
}

describe('runEnded — the transition, not the state', () => {
  it('a live run that stopped running has ended', () => {
    const before = live({ running: true });
    const after = live({ usage: [spent('gpt-oss:120b-cloud', 2455)] });

    expect(runEnded(before, after)).toEqual({
      totalTokens: 2455,
      toast: 'Run finished · 2,455 tokens',
    });
  });

  it('a run still streaming has not ended', () => {
    expect(runEnded(live({ running: true }), live({ running: true }))).toBeNull();
  });

  it('a finished run republished is not a second ending', () => {
    expect(runEnded(live(), live({ threadId: 'thread-2' }))).toBeNull();
  });

  it('nothing before means nothing ended — a fresh tab is not a finished run', () => {
    expect(runEnded(null, live())).toBeNull();
  });

  it('a failed run ended too, and says so by naming no tokens', () => {
    const ended = runEnded(live({ running: true }), live({ usage: null }));

    expect(ended).toEqual({ totalTokens: null, toast: null });
  });

  it('opening a recording is not a run ending', () => {
    const recording = live({ source: 'stored' });

    expect(runEnded(live({ running: true }), recording)).toBeNull();
    expect(runEnded(recording, live())).toBeNull();
  });

  it('sums every model the run reported', () => {
    const after = live({
      usage: [spent('a', 1000), spent('b', 455)],
    });

    expect(runEnded(live({ running: true }), after)?.totalTokens).toBe(1455);
  });
});

/**
 * The shell's two consequences, driven through the real store.
 *
 * This is the ticket's own reproduction: drive `runView` to finished and
 * assert the spend refresh key moved and the toast text was produced. The
 * subscriber below is the shape `AppShell` holds — one reader on the
 * subscription it already had, keeping the previous snapshot in a ref.
 */
describe('driving runView to finished', () => {
  function shell(store: RunViewStore) {
    let previous: RunView | null = null;
    let refreshKey = 0;
    const toasts: string[] = [];
    const off = store.subscribe(() => {
      const ended = runEnded(previous, store.read());
      previous = store.read();
      if (ended === null) return;
      refreshKey += 1;
      if (ended.toast !== null) toasts.push(ended.toast);
    });
    return {
      off,
      toasts,
      key: () => refreshKey,
    };
  }

  it('bumps the spend refresh key and produces the toast', () => {
    const store = new RunViewStore();
    const reader = shell(store);

    store.publish(live({ running: true }));
    expect(reader.key()).toBe(0);
    expect(reader.toasts).toEqual([]);

    store.publish(live({ usage: [spent('m', 2455)] }));

    expect(reader.key()).toBe(1);
    expect(reader.toasts).toEqual(['Run finished · 2,455 tokens']);
    reader.off();
  });

  it('a failed run still moves the bar, and says nothing it cannot say', () => {
    const store = new RunViewStore();
    const reader = shell(store);

    store.publish(live({ running: true }));
    store.publish(live({ usage: null }));

    expect(reader.key()).toBe(1);
    expect(reader.toasts).toEqual([]);
    reader.off();
  });
});
