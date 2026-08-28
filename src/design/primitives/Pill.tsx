import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import clsx from 'clsx';
import { useFloating, type Alignment, type Placement } from './useFloating';
import './Pill.css';

/* ------------------------------------------------------------------ *
 * Pill — a runtime chip, and what it opens.
 *
 * `canvas-feels-right/07`. The owner named the mental model: **a pill per
 * spawned child; click it and a popover shows that child's account; click
 * outside and it closes.**
 *
 * The shape is the substance. The ticket's original open question was "ghost
 * node, badge, or stack?", and a ghost node was rejected because it would
 * read as part of the saved document — which is the exact failure the
 * overlay exists to avoid. A pill cannot be mistaken for a node: it has no
 * ports, no card, no position anyone chose, and no gesture on it reaches the
 * model. `pillIsNotANode.test.ts` pins that as a property of this file
 * rather than as an intention in a comment.
 *
 * One primitive, and `140`'s precedent is why: *one `design/` primitive,
 * three surfaces, never three implementations*. The chat panel is the first
 * surface. The canvas is the second, and this is written for it already —
 * the popover is portalled into `document.body` and closes on the **capture**
 * phase, which is what `Menu` had to do to survive JointJS's own
 * document-level pointer handlers.
 *
 * There is no app logic here. It is handed a label, a flag and some children;
 * it decides nothing about what a child is or when it stops.
 * ------------------------------------------------------------------ */

export interface PillProps {
  /** What to call the child — an archetype or a declared worker name. */
  readonly label: string;
  /** A short qualifier shown after the label, e.g. "in the background". */
  readonly detail?: string;
  /**
   * Whether this child is still going.
   *
   * Drives the pulse and nothing else. A settled pill **stays** — `140` fixed
   * the rule that a finished account is worth keeping and only stops looking
   * like activity, and a pill that vanished on completion would take the
   * evidence of a fan-out with it at the exact moment somebody looks for it.
   */
  readonly live?: boolean;
  /** The popover's heading. Falls back to the label. */
  readonly title?: string;
  /** The popover's body. Rendered only while open. */
  readonly children: ReactNode;
  readonly placement?: Placement;
  readonly align?: Alignment;
  readonly className?: string;
}

/**
 * A chip that opens a popover, and closes on click-outside or Escape.
 *
 * Uncontrolled on purpose: whether a reader has one of these open is not a
 * fact about the run, so it does not belong in run state or anywhere near
 * the model.
 */
export function Pill({
  label,
  detail,
  live = false,
  title,
  children,
  placement = 'top',
  align = 'start',
  className,
}: PillProps) {
  const anchorRef = useRef<HTMLButtonElement | null>(null);
  const floatingRef = useRef<HTMLDivElement | null>(null);
  const [open, setOpen] = useState(false);
  const panelId = useId();

  const position = useFloating(anchorRef, floatingRef, {
    placement,
    align,
    offset: 6,
    enabled: open,
  });

  useEffect(() => {
    if (!open) return;

    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (floatingRef.current?.contains(target)) return;
      if (anchorRef.current?.contains(target)) return;
      setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      setOpen(false);
      anchorRef.current?.focus();
    };

    // Capture phase, exactly as `Menu` does: the canvas installs its own
    // document-level pointer handlers, and a popover that lost that race
    // would stay open under a pan gesture it never saw.
    document.addEventListener('pointerdown', onPointerDown, true);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown, true);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  return (
    <>
      <button
        ref={anchorRef}
        type="button"
        className={clsx('pill', live && 'pill--live', open && 'pill--open', className)}
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        onClick={() => setOpen((was) => !was)}
        // The canvas pans on wheel and drags on pointer-down; a chip drawn
        // over a card must not start either.
        onPointerDown={(event) => event.stopPropagation()}
      >
        <span className="pill__mark" aria-hidden="true" />
        <span className="pill__label">{label}</span>
        {detail ? <span className="pill__detail">{detail}</span> : null}
      </button>
      {open
        ? createPortal(
            <div
              ref={floatingRef}
              id={panelId}
              className="pill-popover"
              role="dialog"
              aria-label={title ?? label}
              style={{
                transform: `translate3d(${position?.x ?? 0}px, ${position?.y ?? 0}px, 0)`,
                visibility: position ? 'visible' : 'hidden',
              }}
              onWheel={(event) => event.stopPropagation()}
              onPointerDown={(event) => event.stopPropagation()}
            >
              <p className="pill-popover__title">{title ?? label}</p>
              {children}
            </div>,
            document.body,
          )
        : null}
    </>
  );
}
