import { useCallback, useEffect, useState } from 'react';

import type { IRuntimeClient, Spend } from '@core/runtime/RuntimeClient';

/**
 * The one fetch behind the status bar.
 *
 * `stable-beta-public/03`. **Nothing polls.** The bar is on screen at all
 * times and the numbers behind it only change when a run finishes, so a timer
 * would be a request per interval for an answer that is almost always the one
 * already shown. `refreshKey` is how a caller says *something happened* — the
 * run dock's terminal frame bumps it (`AppShell`); window focus is wired
 * inside this hook, since every caller wants it and there is nothing
 * app-specific about *the tab came back*.
 */
export interface SpendFeed {
  /** `null` until the first answer arrives — never a stand-in zero. */
  readonly spend: Spend | null;
  /** A sentence to show, or `null`. */
  readonly error: string | null;
  readonly refetch: () => void;
}

/** The two fields `useSpend` actually holds in state, kept apart from the
 * `refetch` callback so the reducer below has something small to work on. */
interface SpendState {
  readonly spend: Spend | null;
  readonly error: string | null;
}

const NOTHING_YET: SpendState = { spend: null, error: null };

/**
 * The one rule that survives a failed fetch, as a pure function.
 *
 * **The last good answer stands.** A backend that has gone away is not
 * evidence that the count went down, and blanking the bar to dashes would
 * make an unreachable server look like a store with no runs in it — the one
 * confusion this whole feature's dash rule exists to prevent. Pulled out of
 * the hook so this rule is checkable without a renderer, the same way
 * `placeFloating` is checkable without a canvas.
 */
export function nextSpendState(
  previous: SpendState,
  outcome: { ok: true; value: Spend } | { ok: false; error: string },
): SpendState {
  if (outcome.ok) return { spend: outcome.value, error: null };
  return { spend: previous.spend, error: outcome.error };
}

/** The narrow shape `onWindowFocus` needs — `Window` satisfies it, and so
 * does a plain object in a test that has no DOM to hand. */
export interface FocusTarget {
  addEventListener(type: 'focus', listener: () => void): void;
  removeEventListener(type: 'focus', listener: () => void): void;
}

/**
 * Subscribes `handler` to `target`'s `focus` event; returns the disposer.
 *
 * Extracted for the same reason as `nextSpendState`: this project's test
 * runner has no DOM (`vite.config.ts`'s `test.environment` is `'node'`, on
 * purpose — the view layer is proven in the browser, not simulated), so a
 * behaviour worth pinning has to be expressible against a plain object
 * instead of a real `window`.
 */
export function onWindowFocus(target: FocusTarget, handler: () => void): () => void {
  target.addEventListener('focus', handler);
  return () => target.removeEventListener('focus', handler);
}

export function useSpend(input: {
  client: IRuntimeClient;
  sessionId: string;
  refreshKey: number;
}): SpendFeed {
  const { client, sessionId, refreshKey } = input;
  const [state, setState] = useState<SpendState>(NOTHING_YET);
  const [nonce, setNonce] = useState(0);

  const refetch = useCallback(() => setNonce((value) => value + 1), []);

  useEffect(() => onWindowFocus(window, refetch), [refetch]);

  useEffect(() => {
    let live = true;
    void client.spend(sessionId).then((result) => {
      if (!live) return;
      setState((previous) => nextSpendState(previous, result));
    });
    return () => {
      live = false;
    };
  }, [client, sessionId, refreshKey, nonce]);

  return { spend: state.spend, error: state.error, refetch };
}
