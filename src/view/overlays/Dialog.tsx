import { useEffect, useRef, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { Icon, IconButton, IconTile } from '@design/primitives';
import './overlays.css';

interface DialogProps {
  title: string;
  subtitle?: string;
  icon?: LucideIcon;
  onClose: () => void;
  footer?: ReactNode;
  children: ReactNode;
}

/**
 * A modal dialog.
 *
 * Handles the three things a modal must get right and is usually missing:
 * Escape closes it, focus moves inside on open and is trapped there, and the
 * backdrop only closes on a click that both started *and* ended on it — so
 * releasing a text selection over the backdrop doesn't discard the dialog.
 */
export function Dialog({ title, subtitle, icon, onClose, footer, children }: DialogProps) {
  const panelRef = useRef<HTMLDivElement | null>(null);
  const backdropMouseDown = useRef(false);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        onClose();
        return;
      }
      if (event.key !== 'Tab') return;

      const focusable = panelRef.current?.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
      );
      if (!focusable || focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (!first || !last) return;

      // Wrap at both ends so Tab can never reach the page behind the modal.
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', onKeyDown, true);
    // Focus the panel itself rather than the first control: landing on
    // "Forget all keys" would be a hostile default.
    panelRef.current?.focus();
    return () => document.removeEventListener('keydown', onKeyDown, true);
  }, [onClose]);

  return createPortal(
    <div
      className="dialog-backdrop"
      onMouseDown={(event) => {
        backdropMouseDown.current = event.target === event.currentTarget;
      }}
      onMouseUp={(event) => {
        if (backdropMouseDown.current && event.target === event.currentTarget) onClose();
        backdropMouseDown.current = false;
      }}
    >
      <div
        ref={panelRef}
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
      >
        <header className="dialog__header">
          {icon ? <IconTile glyph={icon} size="lg" /> : null}
          <div className="dialog__heading">
            <h2 className="dialog__title">{title}</h2>
            {subtitle ? <p className="dialog__subtitle">{subtitle}</p> : null}
          </div>
          <IconButton
            label="Close dialog"
            icon={<Icon glyph={X} size="md" />}
            onClick={onClose}
          />
        </header>

        <div className="dialog__body">{children}</div>

        {footer ? <footer className="dialog__footer">{footer}</footer> : null}
      </div>
    </div>,
    document.body,
  );
}
