import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { CircleAlert, X } from 'lucide-react';
import { Icon, IconButton } from '@design/primitives';
import { appendToast, type Toast } from './toastList';
import './overlays.css';

/** Simultaneous toasts. Beyond this the oldest is dropped. */
const MAX_TOASTS = 3;
const LIFETIME_MS = 5000;

/**
 * Transient messages — rejected connections, failed runs, export problems.
 *
 * Deduplicated by message: dragging a link repeatedly onto the same invalid
 * port produces the same complaint each time, and stacking five copies of it
 * hides everything else.
 */
export function useToaster() {
  const [toasts, setToasts] = useState<readonly Toast[]>([]);
  const nextId = useRef(1);
  const timers = useRef(new Map<number, number>());

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
    const timer = timers.current.get(id);
    if (timer) {
      window.clearTimeout(timer);
      timers.current.delete(id);
    }
  }, []);

  const notify = useCallback((message: string) => {
    if (!message.trim()) return;
    // **The updater is pure.** It used to mint the id and start the dismissal
    // timer inside `setToasts`, and React is explicitly allowed to call an
    // updater more than once — so a single `notify` could schedule two timers,
    // one of them keyed to an id the state never kept, and that stray timer
    // then dismissed a *different, live* toast by number. Observed in a
    // production build: every deep-link message was added and removed again in
    // the same breath, so opening a workflow by link never said anything —
    // not "Opened", not "restored your unsaved edits", not "could not open
    // that" (`every-workflow-green` 26).
    //
    // Minting the id outside the updater makes one call mean one toast, and
    // scheduling moved to the effect below, where a side effect belongs.
    // The updater is `appendToast` and nothing else — pure, idempotent, and
    // unit-tested in `toastList.test.ts`, which is the only level at which
    // this rule can be run: vitest here is `environment: 'node'`, so the hook
    // itself cannot be rendered.
    const id = nextId.current++;
    setToasts((current) => appendToast(current, { id, message }, MAX_TOASTS));
  }, []);

  // Dismissal is scheduled *from* state, not from the act of notifying: a
  // toast that survived into the rendered list is exactly the set that should
  // expire, and one that was deduplicated away never gets a timer at all.
  useEffect(() => {
    for (const toast of toasts) {
      if (timers.current.has(toast.id)) continue;
      timers.current.set(
        toast.id,
        window.setTimeout(() => dismiss(toast.id), LIFETIME_MS),
      );
    }
  }, [toasts, dismiss]);

  useEffect(
    () => () => {
      for (const timer of timers.current.values()) window.clearTimeout(timer);
      timers.current.clear();
    },
    [],
  );

  return { toasts, notify, dismiss };
}

export function Toaster({
  toasts,
  onDismiss,
}: {
  toasts: readonly { id: number; message: string }[];
  onDismiss: (id: number) => void;
}) {
  if (toasts.length === 0) return null;

  return createPortal(
    // `polite` rather than `assertive`: these are advisory, and interrupting
    // a screen-reader user mid-sentence for a dismissible hint is rude.
    <div className="toaster" role="status" aria-live="polite">
      {toasts.map((toast) => (
        <div key={toast.id} className="toast">
          <Icon glyph={CircleAlert} size="sm" />
          <span>{toast.message}</span>
          <IconButton
            size="xs"
            label="Dismiss"
            icon={<Icon glyph={X} size="xs" />}
            onClick={() => onDismiss(toast.id)}
          />
        </div>
      ))}
    </div>,
    document.body,
  );
}
