import { useCallback, useEffect, useRef, useState, type ReactNode, type RefObject } from 'react';
import { createPortal } from 'react-dom';
import { useFloating } from './useFloating';
import './Popover.css';

export interface PopoverProps {
  open: boolean;
  /** The control the popover belongs to. It is centred on this and closes back to it. */
  anchorRef: RefObject<HTMLElement | null>;
  onClose: () => void;
  /** Named for assistive technology, since a popover is a region and not a dialog. */
  label: string;
  /** See `useFloating.bounds` — the box to stay inside. Defaults to the window. */
  bounds?: () => { width: number; height: number } | null;
  /** See `useFloating.subscribe` — an extra reason the anchor may have moved. */
  subscribe?: (update: () => void) => () => void;
  children: ReactNode;
}

/**
 * A panel that hangs off the control that opened it.
 *
 * The third floating surface in the design system, and deliberately not a
 * fourth positioner: `Tooltip` and `Menu` already sit on `useFloating`, and
 * this does too. What it adds over `Menu` is that its content is arbitrary —
 * a `Menu` is a list of items it renders itself, and the Workflows list is a
 * tabbed surface with rows, buttons and its own state.
 *
 * **Why this exists at all** is `launch-readiness` 189: a control in the top
 * bar was opening a panel docked to the far edge of the screen, so the thing
 * that opened it and the thing that opened were as far apart as the window
 * allows. A popover has no such gap, and it is also the honest shape for the
 * content — a list you pick from and leave.
 *
 * Dismissal is a popover's whole contract, so all three ways are here: an
 * outside pointer press, `Escape`, and whatever the content decides finishes
 * the job (it calls `onClose`). The pointer listener runs in the **capture**
 * phase for the reason `Menu` records — the canvas installs its own
 * document-level pointer handlers and the floating surface must win the race.
 *
 * The maximum height is measured rather than declared: a popover has no flow
 * to get its height from, and the room below its trigger changes when the run
 * dock is dragged (`memory-and-replay` 51) without the window resizing at all.
 * That is what `bounds` and `subscribe` are for, and they are the same two
 * handles `useFloating` takes.
 */
export function Popover({
  open,
  anchorRef,
  onClose,
  label,
  bounds,
  subscribe,
  children,
}: PopoverProps) {
  const floatingRef = useRef<HTMLDivElement>(null);
  const [room, setRoom] = useState<number | null>(null);

  /**
   * `useFloating`'s own re-measure, captured on the way past.
   *
   * The two measurements are a cycle and the order matters: `useFloating`
   * reads `offsetHeight`, and `offsetHeight` is whatever the *previous*
   * render's `max-height` allowed. So when the room shrinks — the run dock
   * opening, or being dragged — the placement is computed against the old,
   * taller box, decides the popover cannot fit under its trigger, and pins it
   * to the top of the container instead. Measured: y jumped from 44 to 8 and
   * the list sat over the top bar.
   *
   * Nudging it once the new height has actually been applied is what closes
   * the loop, and it settles immediately because the second pass finds a box
   * that already fits. `subscribe` is the hook's existing "the anchor may have
   * moved" channel, so this borrows it rather than adding a second one.
   */
  const remeasure = useRef<(() => void) | null>(null);
  const subscribeFloating = useCallback(
    (update: () => void) => {
      remeasure.current = update;
      const stop = subscribe?.(update);
      return () => {
        remeasure.current = null;
        stop?.();
      };
    },
    [subscribe],
  );

  const position = useFloating(anchorRef, floatingRef, {
    placement: 'bottom',
    align: 'center',
    offset: OFFSET,
    padding: PADDING,
    enabled: open,
    bounds,
    subscribe: subscribeFloating,
  });

  /** How much of the container is left below the trigger. */
  const measure = useCallback(() => {
    const anchor = anchorRef.current;
    if (!anchor) return;
    // `bounds` reports its box from the window's origin, so its height *is*
    // the floor this popover has to stay above — the stage's bottom edge once
    // the run dock has taken its share, and the window's otherwise.
    const floor = bounds?.()?.height ?? window.innerHeight;
    // Both gaps, not one. `useFloating` places the popover `OFFSET` below the
    // trigger and refuses to let it come within `PADDING` of the container's
    // edge, so a maximum height accounting for only the first is a couple of
    // pixels too tall — and `placeFloating`, finding it does not fit, gives up
    // on hanging off the trigger and pins it to the top of the container
    // instead. Measured: the popover jumped from y=44 to y=8 and sat over the
    // top bar the moment the run dock opened.
    const next = Math.max(
      MIN_ROOM,
      Math.round(floor - anchor.getBoundingClientRect().bottom - OFFSET - PADDING),
    );
    setRoom((current) => (current !== null && Math.abs(current - next) < 1 ? current : next));
  }, [anchorRef, bounds]);

  useEffect(() => {
    if (!open) return;
    measure();
    window.addEventListener('resize', measure);
    window.addEventListener('scroll', measure, true);
    const stop = subscribe?.(measure);
    return () => {
      window.removeEventListener('resize', measure);
      window.removeEventListener('scroll', measure, true);
      stop?.();
    };
  }, [open, measure, subscribe]);

  useEffect(() => {
    // Second pass, once the measured height is the one the browser is using.
    remeasure.current?.();
  }, [room]);

  useEffect(() => {
    if (!open) return;

    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (floatingRef.current?.contains(target ?? null)) return;
      if (anchorRef.current?.contains(target ?? null)) return;
      onClose();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      onClose();
      // Back to the control that opened it: a popover dismissed with the
      // keyboard must not leave focus on nothing.
      anchorRef.current?.focus();
    };

    document.addEventListener('pointerdown', onPointerDown, true);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown, true);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open, onClose, anchorRef]);

  if (!open) return null;

  return createPortal(
    <div
      ref={floatingRef}
      className="popover"
      role="group"
      aria-label={label}
      style={{
        transform: `translate3d(${position?.x ?? 0}px, ${position?.y ?? 0}px, 0)`,
        // Hidden rather than unmounted until the first measurement, exactly as
        // `Menu` does: an unmeasured popover would paint one frame at the
        // origin before jumping to its anchor.
        visibility: position ? 'visible' : 'hidden',
        maxHeight: room === null ? undefined : `${room}px`,
      }}
    >
      {children}
    </div>,
    document.body,
  );
}

/** Air between the trigger and the popover. */
const OFFSET = 6;

/** The clearance `useFloating` keeps from the container's edge. */
const PADDING = 8;

/**
 * The shortest popover worth showing.
 *
 * The same trade the run dock makes on its own axis: in a container too short
 * to hold the popover under its trigger, slightly overhanging is better than a
 * sliver, and it scrolls either way.
 */
const MIN_ROOM = 160;
