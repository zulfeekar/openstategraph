import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { CircleAlert, X } from 'lucide-react';
import { Icon, IconButton } from '@design/primitives';
import './overlays.css';

interface Toast {
  readonly id: number;
  readonly message: string;
}

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

  const notify = useCallback(
    (message: string) => {
      if (!message.trim()) return;
      setToasts((current) => {
        if (current.some((toast) => toast.message === message)) return current;
        const id = nextId.current++;
        const timer = window.setTimeout(() => dismiss(id), LIFETIME_MS);
        timers.current.set(id, timer);
        return [...current, { id, message }].slice(-MAX_TOASTS);
      });
    },
    [dismiss],
  );

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
