import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * A text input that edits normalised model state without fighting the caret.
 *
 * The problem it solves is specific and easy to reintroduce. The model
 * normalises on write — `setNodeTitle` trims, and a blank title falls back to
 * the node type's label — which is correct for stored data. But a fully
 * controlled input that writes on every keystroke reads that normalised value
 * straight back, so:
 *
 * - Typing a space produces `"My "`, which trims to `"My"`, which is pushed
 *   back into the input. **The space is eaten, so a two-word name is
 *   untypeable.**
 * - Clearing the field makes the title blank, which falls back to the type
 *   label, so the input **refills itself with `"AI Agent"`** instead of
 *   emptying.
 *
 * The rule this encodes: **normalise at the boundary, buffer in the editor.**
 * The draft is what the user typed; the model gets a debounced, normalised
 * version. Keeping the trim in the model is deliberate — moving it here would
 * let trailing whitespace reach `workflow.json` and show up in diffs.
 *
 * External changes are still adopted, which is what keeps undo, import and
 * programmatic edits working: the draft yields whenever the incoming value is
 * not the one this hook last committed.
 */
export function useDraftValue(
  external: string,
  commit: (value: string) => void,
  delayMs = 200,
): { value: string; onChange: (next: string) => void; onBlur: () => void } {
  const [draft, setDraft] = useState(external);

  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pending = useRef<string | null>(null);
  /** The last value we pushed, so we can tell our own echo from a real change. */
  const committed = useRef(external);

  const flush = useCallback(() => {
    if (timer.current != null) {
      clearTimeout(timer.current);
      timer.current = null;
    }
    if (pending.current == null) return;
    const value = pending.current;
    pending.current = null;
    committed.current = value;
    commit(value);
  }, [commit]);

  const onChange = useCallback(
    (next: string) => {
      setDraft(next);
      pending.current = next;
      if (timer.current != null) clearTimeout(timer.current);
      timer.current = setTimeout(flush, delayMs);
    },
    [delayMs, flush],
  );

  // Adopt a value that came from somewhere else — an undo, an import, a
  // different panel. Skipped when it is the echo of our own commit, which is
  // the check that stops the normalised value from clobbering the draft.
  useEffect(() => {
    if (external === committed.current) return;
    committed.current = external;
    pending.current = null;
    if (timer.current != null) {
      clearTimeout(timer.current);
      timer.current = null;
    }
    setDraft(external);
  }, [external]);

  // Flush on unmount so typing then immediately selecting another node — or
  // closing the panel — does not silently discard the edit.
  useEffect(() => flush, [flush]);

  return { value: draft, onChange, onBlur: flush };
}
