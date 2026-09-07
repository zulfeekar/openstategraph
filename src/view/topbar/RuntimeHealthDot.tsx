import { useEffect, useState } from 'react';
import { RuntimeClient } from '@core/runtime/RuntimeClient';
import { probeServerReadiness } from '@core/providers/serverReadiness';

const POLL_MS = 10_000;

/**
 * One glanceable answer to "is the runtime up?" — ticket 58.
 *
 * The failure this exists for: the backend dies silently, and the next
 * symptom the user sees is a stale panel or a dead Send button that both
 * read as "the app is broken". A dot that flips red within one poll names
 * the actual problem, and its tooltip says what to run.
 *
 * It asks through `probeServerReadiness` rather than calling `health()`
 * directly, because this component was already the only thing in the editor
 * asking the server how it is — and it threw `model_configured` away, so three
 * other surfaces guessed at model readiness from browser-local keys and told a
 * fully configured install it had none (providers-and-credentials 06). One
 * poll, one answer, published where the labels can read it.
 */
export function RuntimeHealthDot() {
  const [up, setUp] = useState<boolean | null>(null);

  useEffect(() => {
    const client = new RuntimeClient();
    let cancelled = false;
    const probe = async () => {
      const reachable = await probeServerReadiness(client);
      if (!cancelled) setUp(reachable);
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
