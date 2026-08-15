import { useState } from 'react';
import { KeyRound, X } from 'lucide-react';
import { Button, Icon } from '@design/primitives';
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
 */
export function OnboardingHint({ onOpenCredentials }: { onOpenCredentials: () => void }) {
  const [visible, setVisible] = useState(() => !alreadyAnswered(ONBOARDED_KEY));

  const close = () => {
    markAnswered(ONBOARDED_KEY);
    setVisible(false);
  };

  if (!visible) return null;

  return (
    <div className="onboarding-hint" role="status">
      <button type="button" className="onboarding-hint__close" aria-label="Dismiss" onClick={close}>
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
