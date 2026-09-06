import { useEffect, useState } from 'react';
import { KeyRound, X } from 'lucide-react';
import { Button, Icon } from '@design/primitives';
import { serverReadiness } from '@core/providers/serverReadiness';
import { ONBOARDED_KEY, alreadyAnswered, markAnswered } from './onceOnlyFlag';
import './overlays.css';

/**
 * First-run pointer at "Models and credentials".
 *
 * A popover anchored to the key button, not a modal: the editor is genuinely
 * usable before any key is added (every node falls back to mock data), so
 * blocking the canvas to demand credentials would misstate the situation. It
 * points at the control that fixes it and gets out of the way.
 *
 * Owns its own storage flag rather than taking `seen`/`onSeen` props — there
 * is exactly one first run, and threading that state through the shell would
 * add a permanent prop to a layout for a one-time event. The flag's three
 * decisions moved to `onceOnlyFlag` when ticket 23 needed a second hint of the
 * same shape; the key and the behaviour are unchanged, so an install that has
 * already answered stays answered.
 *
 * **The flag is not the whole gate, and that was the bug.** The docstring
 * above used to justify the copy — *"the editor is genuinely usable before any
 * key is added (every node falls back to mock data)"* — which is a true
 * sentence about an *unconfigured* install that was being asserted
 * unconditionally. On a server with three keys set, the first sentence the
 * product ever said was "workflows run against mock data until you do", while
 * the dialog it points at said `ready` for all three
 * (providers-and-credentials 06). It reads `serverReadiness` now, the same
 * resolver the model picker and the reasoning row read.
 *
 * **"Falls back to mock data" stopped being true and nobody updated this
 * file** (providers-and-credentials/14). `MockProvider` is real, but the Run
 * button has not called the client-side engine that owns it since ticket 03
 * rewired it to stream a real backend run — `workbench.engine.run()` today
 * has no caller left outside a test. Pressing Run on an unconfigured server
 * reaches `/api/runs/stream` and 500s from `NoProviderInstalled`, which is
 * what `openstategraph serve` already says on the same install. So this
 * hint now prints the server's own `run_readiness` sentence — the same
 * clause `openstategraph providers` and `openstategraph serve` print —
 * instead of inventing a second, incompatible claim.
 *
 * It waits rather than flashing: `modelConfigured() === null` is "the server
 * has not answered", and a hint that appears for one poll and then admits it
 * was wrong is worse than one that arrives a beat late. The same wait now
 * applies to the sentence itself — `runReadiness() === null` until
 * `/api/providers` has answered — because a hint with no sentence yet is the
 * same mistake at a smaller scale.
 */
export function OnboardingHint({ onOpenCredentials }: { onOpenCredentials: () => void }) {
  const [answered, setAnswered] = useState(() => alreadyAnswered(ONBOARDED_KEY));
  const [configured, setConfigured] = useState(() => serverReadiness.modelConfigured());
  const [reason, setReason] = useState(() => serverReadiness.runReadiness());

  useEffect(() =>
    serverReadiness.onChange(() => {
      setConfigured(serverReadiness.modelConfigured());
      setReason(serverReadiness.runReadiness());
    }),
  );

  const close = () => {
    markAnswered(ONBOARDED_KEY);
    setAnswered(true);
  };

  // Only on an install that genuinely has no model: not before the server has
  // answered, never on one that has, and not before it has said the sentence
  // to show.
  if (answered || configured !== false || reason === null) return null;

  return (
    <div className="onboarding-hint" role="status">
      <button type="button" className="onboarding-hint__close" aria-label="Dismiss" onClick={close}>
        <Icon glyph={X} size="sm" />
      </button>
      <p className="onboarding-hint__text">{reason}</p>
      <Button
        variant="primary"
        size="sm"
        icon={<Icon glyph={KeyRound} size="sm" />}
        onClick={() => {
          close();
          onOpenCredentials();
        }}
      >
        Show me where
      </Button>
    </div>
  );
}
