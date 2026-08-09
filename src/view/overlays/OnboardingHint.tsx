import { useState } from 'react';
import { KeyRound, X } from 'lucide-react';
import { Button, Icon } from '@design/primitives';
import './overlays.css';

/**
 * The flag that says this browser has seen the hint. Both buttons set it —
 * dismissing is as much an answer as acting on it, and a bubble that returns
 * after you closed it is the most annoying kind of onboarding there is.
 */
const ONBOARDED_KEY = 'openstategraph.onboarded';

function alreadyOnboarded(): boolean {
  try {
    return window.localStorage.getItem(ONBOARDED_KEY) === 'true';
  } catch {
    // Storage unavailable (private mode, embedded frame): show nothing rather
    // than a hint that can never be dismissed for good.
    return true;
  }
}

function markOnboarded(): void {
  try {
    window.localStorage.setItem(ONBOARDED_KEY, 'true');
  } catch {
    /* the hint is already hidden for this session */
  }
}

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
 * add a permanent prop to a layout for a one-time event.
 */
export function OnboardingHint({ onOpenCredentials }: { onOpenCredentials: () => void }) {
  const [visible, setVisible] = useState(() => !alreadyOnboarded());

  const close = () => {
    markOnboarded();
    setVisible(false);
  };

  if (!visible) return null;

  return (
    <div className="onboarding-hint" role="status">
      <button
        type="button"
        className="onboarding-hint__close"
        aria-label="Dismiss"
        onClick={close}
      >
        <Icon glyph={X} size="sm" />
      </button>
      <p className="onboarding-hint__text">
        New here? Add your Anthropic, OpenAI or Ollama cloud keys in Models &amp; credentials —
        workflows run against mock data until you do.
      </p>
      <Button
        variant="primary"
        size="sm"
        icon={<Icon glyph={KeyRound} size="sm" />}
        onClick={() => {
          close();
          onOpenCredentials();
        }}
      >
        Add keys
      </Button>
    </div>
  );
}
