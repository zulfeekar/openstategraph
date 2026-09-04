import { useCallback, useEffect, useState } from 'react';

import type { IRuntimeClient, Spend } from '@core/runtime/RuntimeClient';

/**
 * The one fetch behind the status bar.
 *
 * `stable-beta-public/03`. **Nothing polls.** The bar is on screen at all
 * times and the numbers behind it only change when a run finishes, so a timer
 * would be a request per interval for an answer that is almost always the one
 * already shown. `refreshKey` is how a caller says *something happened* —
 * slice 3 wires the run dock's terminal frame and window focus to it.
 */
export interface SpendFeed {
  /** `null` until the first answer arrives — never a stand-in zero. */
  readonly spend: Spend | null;
  /** A sentence to show, or `null`. */
  readonly error: string | null;
  readonly refetch: () => void;
}

export function useSpend(input: {
  client: IRuntimeClient;
  sessionId: string;
  refreshKey: number;
}): SpendFeed {
  const { client, sessionId, refreshKey } = input;
  const [spend, setSpend] = useState<Spend | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  const refetch = useCallback(() => setNonce((value) => value + 1), []);

  useEffect(() => {
    let live = true;
    void client.spend(sessionId).then((result) => {
      if (!live) return;
      if (result.ok) {
        setSpend(result.value);
        setError(null);
        return;
      }
      // **The last good answer stands.** A backend that has gone away is not
      // evidence that the count went down, and blanking the bar to dashes
      // would make an unreachable server look like a store with no runs in it
      // — the one confusion this whole feature's dash rule exists to prevent.
      setError(result.error);
    });
    return () => {
      live = false;
    };
  }, [client, sessionId, refreshKey, nonce]);

  return { spend, error, refetch };
}
