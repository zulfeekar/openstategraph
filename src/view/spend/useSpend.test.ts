import { describe, expect, it, vi } from 'vitest';

import type { Spend } from '@core/runtime/RuntimeClient';

import { nextSpendState, onWindowFocus, type FocusTarget } from './useSpend';

/**
 * `useSpend`'s two rules, checked away from React.
 *
 * `stable-beta-public/03`, slice 3. This project's test runner has no DOM —
 * `vite.config.ts` sets `test.environment: 'node'` deliberately, because the
 * view layer is proven in the browser rather than simulated — so the hook
 * itself cannot be rendered here. What it does instead, the same move
 * `useFloating.ts` already made for `placeFloating`: the two behaviours worth
 * pinning are pure functions the hook calls, exported and tested directly.
 * *Refetch when `refreshKey` changes* is the third behaviour the plan names;
 * it is React's own dependency-array mechanism over
 * `[client, sessionId, refreshKey, nonce]` and is proven in the browser step
 * of this slice rather than re-simulated here.
 */
const SPEND: Spend = {
  grandTotal: 1200,
  cachedTotal: 300,
  byModel: [],
  sessionByModel: [],
  sessionTotal: 400,
  sessions: [],
};

const OTHER_SPEND: Spend = { ...SPEND, grandTotal: 9999 };

describe('nextSpendState — an error keeps the last good value', () => {
  it('replaces the state on a successful fetch', () => {
    const next = nextSpendState({ spend: null, error: null }, { ok: true, value: SPEND });

    expect(next).toEqual({ spend: SPEND, error: null });
  });

  it('keeps the previous spend and records the error on a failed fetch', () => {
    const next = nextSpendState(
      { spend: SPEND, error: null },
      { ok: false, error: 'backend unreachable' },
    );

    expect(next.spend).toBe(SPEND);
    expect(next.error).toBe('backend unreachable');
  });

  it('a later success clears a previous error', () => {
    const afterFailure = nextSpendState(
      { spend: SPEND, error: null },
      { ok: false, error: 'backend unreachable' },
    );
    const afterRecovery = nextSpendState(afterFailure, { ok: true, value: OTHER_SPEND });

    expect(afterRecovery).toEqual({ spend: OTHER_SPEND, error: null });
  });

  it('a fetch before any good answer has arrived has nothing to fall back to', () => {
    const next = nextSpendState({ spend: null, error: null }, { ok: false, error: 'offline' });

    expect(next).toEqual({ spend: null, error: 'offline' });
  });
});

/** A `FocusTarget` a test can drive without a real `window`. */
function fakeWindow(): FocusTarget & { fireFocus: () => void } {
  const listeners = new Set<() => void>();
  return {
    addEventListener(type, listener) {
      if (type === 'focus') listeners.add(listener);
    },
    removeEventListener(type, listener) {
      if (type === 'focus') listeners.delete(listener);
    },
    fireFocus() {
      for (const listener of listeners) listener();
    },
  };
}

describe('onWindowFocus — refetch when the tab comes back', () => {
  it('calls the handler when the target reports focus', () => {
    const target = fakeWindow();
    const handler = vi.fn();

    onWindowFocus(target, handler);
    target.fireFocus();

    expect(handler).toHaveBeenCalledTimes(1);
  });

  it('the disposer stops the handler from firing again', () => {
    const target = fakeWindow();
    const handler = vi.fn();

    const dispose = onWindowFocus(target, handler);
    dispose();
    target.fireFocus();

    expect(handler).not.toHaveBeenCalled();
  });
});
