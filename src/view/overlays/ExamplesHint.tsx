import { useEffect, useMemo, useState } from 'react';
import { FileJson, X } from 'lucide-react';
import { Button, Icon } from '@design/primitives';
import { WorkflowFileClient } from '@core/runtime/WorkflowFileClient';
import { EXAMPLES_HINT_ACTION, examplesHintText } from '@view/workflow/examplesJourney';
import { EXAMPLES_HINT_KEY, ONBOARDED_KEY, alreadyAnswered, markAnswered } from './onceOnlyFlag';
import './overlays.css';

/**
 * First-run pointer at the examples shelf (production-ready ticket 23).
 *
 * install-experience wave 3 collapsed the shelf by default and was right to:
 * before you have a workflow of your own, an expanded gallery makes the
 * Workflows panel someone else's twenty-three above your nothing. But a
 * collapsed shelf inside a panel nobody has opened is a gallery with no door,
 * and the owner's QA is the receipt — "it is not clear how to load the 20
 * examples and what to do." This is the door. **The collapse stays**;
 * discoverability comes from the signpost.
 *
 * `OnboardingHint` is the precedent and this deliberately mirrors it: a
 * popover anchored to the control that fixes it, shown once, dismissal counted
 * as an answer, the flag owned here rather than threaded through the shell.
 *
 * ## Two things it does that the credentials hint does not
 *
 * **It waits its turn.** It renders only once `ONBOARDED_KEY` is answered, so
 * a fresh install is never met by two popovers at once — and at phone widths,
 * where the toolbar wraps to three rows, two 260px bubbles would genuinely
 * overlap rather than merely crowd. The check is on every render rather than
 * in a `useState` initialiser, because the answer arrives from a *sibling*
 * component: pressing "Add keys" opens the credentials dialog, the shell
 * re-renders, and this appears without waiting for a reload.
 *
 * **It counts before it speaks.** The number in the sentence is the length of
 * `GET /api/examples` and never a literal — prose in this repository has
 * claimed twenty, twenty-one and twenty-two against an actual 23. If the
 * runtime is down or the list is empty the hint simply does not appear, which
 * is the same silence the shelf itself keeps: no gallery is a smaller loss
 * than a bubble promising examples that cannot be fetched.
 */
export function ExamplesHint({ onBrowseExamples }: { onBrowseExamples: () => void }) {
  const [dismissed, setDismissed] = useState(false);
  const [count, setCount] = useState(0);
  const client = useMemo(() => new WorkflowFileClient(), []);

  const wanted =
    !dismissed && alreadyAnswered(ONBOARDED_KEY) && !alreadyAnswered(EXAMPLES_HINT_KEY);

  useEffect(() => {
    if (!wanted) return;
    void client.examples().then((outcome) => {
      if (outcome.ok) setCount(outcome.value.length);
    });
  }, [wanted, client]);

  const close = () => {
    markAnswered(EXAMPLES_HINT_KEY);
    setDismissed(true);
  };

  if (!wanted || count === 0) return null;

  return (
    <div className="onboarding-hint onboarding-hint--start" role="status">
      <button type="button" className="onboarding-hint__close" aria-label="Dismiss" onClick={close}>
        <Icon glyph={X} size="sm" />
      </button>
      <p className="onboarding-hint__text">{examplesHintText(count)}</p>
      <Button
        variant="primary"
        size="sm"
        icon={<Icon glyph={FileJson} size="sm" />}
        onClick={() => {
          close();
          onBrowseExamples();
        }}
      >
        {EXAMPLES_HINT_ACTION}
      </Button>
    </div>
  );
}
