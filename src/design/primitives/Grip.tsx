import clsx from 'clsx';
import './Grip.css';

/**
 * A draggable edge — `stable-beta-public/21`.
 *
 * **The look and the accessibility shell, and deliberately nothing else.**
 * The arithmetic of a drag belongs to the surface that owns the thing being
 * sized: the column's bounds are facts about the window and about which
 * panels are open (`view/layout/panelWidth.ts`), the dock's are facts about
 * the timeline, and this primitive can see neither. So every handler is
 * passed in, and what is shared is what a reader sees and what a screen
 * reader is told.
 *
 * That split is why it is one control and not two: `16` and `19` shipped a
 * grip on each axis, each written in its own surface stylesheet, and the
 * two came apart on the one property neither file could compare — weight.
 * The states live in `Grip.css`; a surface cannot pick one.
 *
 * `role="separator"` with `aria-orientation` and a `valuenow/min/max` is
 * the ARIA pattern for a resizable pane divider, and `tabIndex={0}` is what
 * makes the keyboard path reachable at all. `max` is optional because the
 * dock's ceiling is the viewport rather than a number it holds.
 */
export function Grip({
  orientation,
  ariaLabel,
  value,
  min,
  max,
  onPointerDown,
  onPointerMove,
  onPointerUp,
  onPointerCancel,
  onKeyDown,
}: {
  readonly orientation: 'horizontal' | 'vertical';
  readonly ariaLabel: string;
  readonly value: number;
  readonly min: number;
  readonly max?: number;
  readonly onPointerDown: (event: React.PointerEvent<HTMLDivElement>) => void;
  readonly onPointerMove: (event: React.PointerEvent<HTMLDivElement>) => void;
  readonly onPointerUp: (event: React.PointerEvent<HTMLDivElement>) => void;
  readonly onPointerCancel: (event: React.PointerEvent<HTMLDivElement>) => void;
  readonly onKeyDown: (event: React.KeyboardEvent<HTMLDivElement>) => void;
}) {
  return (
    <div
      className={clsx('grip', `grip--${orientation}`)}
      role="separator"
      aria-orientation={orientation}
      aria-label={ariaLabel}
      aria-valuenow={Math.round(value)}
      aria-valuemin={min}
      aria-valuemax={max}
      tabIndex={0}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerCancel}
      onKeyDown={onKeyDown}
    />
  );
}
