import { useEffect, useState } from 'react';
import { RuntimeClient } from '@core/runtime/RuntimeClient';

const POLL_MS = 10_000;

/**
 * One glanceable answer to "is the runtime up?" — ticket 58.
 *
 * The failure this exists for: the backend dies silently, and the next
 * symptom the user sees is a stale panel or a dead Send button that both
 * read as "the app is broken". A dot that flips red within one poll names
 * the actual problem, and its tooltip says what to run.
 */
export function RuntimeHealthDot() {
  const [up, setUp] = useState<boolean | null>(null);

  useEffect(() => {
    const client = new RuntimeClient();
    let cancelled = false;
    const probe = async () => {
      const outcome = await client.health();
      if (!cancelled) setUp(outcome.ok);
    };
    void probe();
    const timer = window.setInterval(() => void probe(), POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  const state = up === null ? 'checking' : up ? 'up' : 'down';
  const label =
    state === 'up'
      ? 'Runtime connected'
      : state === 'down'
        ? 'Runtime unreachable — start it with scripts/dev.sh'
        : 'Checking runtime…';

  return (
    <span
      className="topbar__health"
      data-state={state}
      role="status"
      aria-label={label}
      title={label}
    />
  );
}
