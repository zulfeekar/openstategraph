import { useCallback, useRef } from 'react';
import { panelColumnWidthFromArrow, panelColumnWidthFromDrag } from './panelWidth';

/**
 * The handle on the right-hand column's left edge (`stable-beta-public/16`).
 *
 * Its own component rather than eleven more lines in `AppShell`, for the
 * reason the module ceiling exists: the shell already composes a dozen
 * surfaces, and a gesture with a pointer path, a keyboard path and an ARIA
 * contract is a thing with its own reason to change.
 *
 * The dock's grip (`RunDock`) is the same control on the other axis, and the
 * two are deliberately identical in everything but direction: a separator, a
 * pointer capture so the drag survives leaving the 7px strip, arrows that
 * come from the same module as the drag, and `null` from that module for a
 * key it has no opinion about — so Tab still leaves the handle.
 *
 * The width it reports is **unclamped**. The shell owns the clamp: the
 * bounds are facts about the window and about which panels are open, and
 * this control can see neither.
 */
export function PanelColumnGrip({
  width,
  min,
  max,
  onWidthChange,
}: {
  readonly width: number;
  readonly min: number;
  readonly max: number;
  readonly onWidthChange: (requested: number) => void;
}) {
  const dragFrom = useRef<{ pointerX: number; width: number } | null>(null);

  const onPointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      event.preventDefault();
      event.currentTarget.setPointerCapture(event.pointerId);
      dragFrom.current = { pointerX: event.clientX, width };
    },
    [width],
  );

  const onPointerMove = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      const from = dragFrom.current;
      if (!from) return;
      onWidthChange(panelColumnWidthFromDrag(from.width, from.pointerX, event.clientX));
    },
    [onWidthChange],
  );

  const endDrag = useCallback(() => {
    dragFrom.current = null;
  }, []);

  const onKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      const asked = panelColumnWidthFromArrow(width, event.key);
      if (asked === null) return;
      onWidthChange(asked);
      event.preventDefault();
    },
    [width, onWidthChange],
  );

  return (
    <div
      className="app-shell__column-grip"
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize the chat and inspector column"
      aria-valuenow={Math.round(width)}
      aria-valuemin={min}
      aria-valuemax={max}
      tabIndex={0}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onKeyDown={onKeyDown}
    />
  );
}
