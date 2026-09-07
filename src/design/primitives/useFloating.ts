import { useCallback, useEffect, useLayoutEffect, useState, type RefObject } from 'react';

export type Placement = 'top' | 'bottom' | 'left' | 'right';
export type Alignment = 'start' | 'center' | 'end';

interface FloatingOptions {
  placement?: Placement;
  align?: Alignment;
  /** Gap between anchor and floating element. */
  offset?: number;
  /** Keep this much clearance from the viewport edge when clamping. */
  padding?: number;
  /** Skip all measurement while closed. */
  enabled?: boolean;
  /**
   * An extra reason to re-measure, supplied by whoever knows about one.
   *
   * `scroll` and `resize` cover every way the DOM itself moves an anchor,
   * and they are not enough on the canvas: JointJS pans and zooms by
   * changing an SVG transform, which fires neither. A wheel-zoom over the
   * paper therefore slid a node card out from under an open popover while
   * the popover stayed put — measured live on `parallel-workers-join`
   * (`canvas-feels-right/07`): the chip moved from y=406 to y=540 and the
   * popover did not move at all.
   *
   * The fix belongs here as a *subscription* rather than as knowledge of the
   * paper, because `design/` imports neither React-canvas nor JointJS. The
   * caller hands in "tell me when the anchor may have moved" and the canvas
   * layer is the only place that answers it — `PaperController.viewport
   * .onChange`, which `NodeCard` already uses for exactly this reason.
   *
   * Returns its own unsubscribe, so a caller that re-creates the function on
   * every render costs one re-subscription and never a leak.
   */
  subscribe?: (update: () => void) => () => void;
  /**
   * The box the floating element must stay inside. Defaults to the window.
   *
   * `launch-readiness` 189 needs this and nothing before it did: the shell's
   * stage is a **sibling** of the run dock (`memory-and-replay` 51), so
   * dragging the dock's edge makes the stage shorter while the window's size
   * is unchanged. A popover clamped to the window would hang over the
   * timeline, and the `resize` listener below would never fire to correct it —
   * hence `subscribe`, which is how the caller says the stage moved.
   *
   * A function rather than a ref, matching `subscribe` above and for a related
   * reason: the caller is the one that knows what its container is, and the
   * box has to be measured **from the window's origin** — `placeFloating`
   * clamps its low edge to `padding` from zero, so a bound with an origin of
   * its own would need an offset the clamp does not carry. Handing back
   * `{ width: rect.right, height: rect.bottom }` is what makes that true, and
   * saying so at the call site is more honest than a ref this could silently
   * mis-measure. `null` means *not measurable yet*, and the window is used.
   */
  bounds?: () => { width: number; height: number } | null;
}

export interface FloatingPosition {
  x: number;
  y: number;
  /** The placement actually used — may differ from the request after a flip. */
  placement: Placement;
}

const OPPOSITE: Record<Placement, Placement> = {
  top: 'bottom',
  bottom: 'top',
  left: 'right',
  right: 'left',
};

/** A rectangle, as `getBoundingClientRect` gives one. */
export interface AnchorRect {
  left: number;
  top: number;
  right: number;
  bottom: number;
  width: number;
  height: number;
}

function resolve(
  anchor: AnchorRect,
  floating: { width: number; height: number },
  placement: Placement,
  align: Alignment,
  offset: number,
): { x: number; y: number } {
  const alignAxis = (start: number, anchorSize: number, floatSize: number) => {
    if (align === 'start') return start;
    if (align === 'end') return start + anchorSize - floatSize;
    return start + (anchorSize - floatSize) / 2;
  };

  switch (placement) {
    case 'top':
      return {
        x: alignAxis(anchor.left, anchor.width, floating.width),
        y: anchor.top - floating.height - offset,
      };
    case 'bottom':
      return {
        x: alignAxis(anchor.left, anchor.width, floating.width),
        y: anchor.bottom + offset,
      };
    case 'left':
      return {
        x: anchor.left - floating.width - offset,
        y: alignAxis(anchor.top, anchor.height, floating.height),
      };
    case 'right':
      return {
        x: anchor.right + offset,
        y: alignAxis(anchor.top, anchor.height, floating.height),
      };
  }
}

/**
 * Where a floating element goes: try the requested side, flip if it does not
 * fit, then keep it on screen.
 *
 * Exported and pure so it can be tested as arithmetic rather than by opening
 * a menu and looking — `design/` holds no app logic, and this is the only
 * thing in it with a wrong answer.
 *
 * **`clamp` is a named function rather than the obvious one-liner**, because
 * the one-liner was the bug (canvas-feels-right ticket 02):
 *
 *     Math.min(Math.max(value, lo), hi)
 *
 * is a clamp only while `lo <= hi`. When the floating element is larger than
 * the viewport minus padding — a long menu, a short window, or a measurement
 * taken before layout, when `offsetHeight` is still 0 or wrong — the bounds
 * invert, `Math.min` wins, and the result is *less than* `lo`: negative, off
 * the top or left of the screen. The guard written to stop clipping was
 * producing it. Measured live: a menu at `y = -2`.
 *
 * When it genuinely cannot fit, the low bound wins: the popup starts at the
 * padding edge so its first item is reachable and the rest can scroll. Half
 * off the top is never the better answer.
 */
function clamp(value: number, lo: number, hi: number): number {
  if (hi < lo) return lo;
  return Math.min(Math.max(value, lo), hi);
}

export function placeFloating(
  anchor: AnchorRect,
  size: { width: number; height: number },
  viewport: { width: number; height: number },
  options: { placement: Placement; align: Alignment; offset: number; padding: number },
): FloatingPosition {
  const { placement, align, offset, padding } = options;

  const fits = (pos: { x: number; y: number }): boolean =>
    pos.x >= padding &&
    pos.y >= padding &&
    pos.x + size.width <= viewport.width - padding &&
    pos.y + size.height <= viewport.height - padding;

  let used = placement;
  let next = resolve(anchor, size, used, align, offset);

  if (!fits(next)) {
    const flipped = resolve(anchor, size, OPPOSITE[used], align, offset);
    if (fits(flipped)) {
      used = OPPOSITE[used];
      next = flipped;
    }
  }

  return {
    x: clamp(next.x, padding, viewport.width - size.width - padding),
    y: clamp(next.y, padding, viewport.height - size.height - padding),
    placement: used,
  };
}

/**
 * Minimal viewport-aware positioning for tooltips, menus and popovers:
 * measure, try the requested side, flip to the opposite side if it does
 * not fit, then keep it on screen.
 *
 * Deliberately not a full floating-ui port — flip + clamp is sufficient and
 * costs a few hundred bytes instead of 20kB. It used to say the app "only
 * ever anchors to elements already inside the viewport"; the canvas pans and
 * zooms, so that was never true and `placeFloating` no longer assumes it.
 */
export function useFloating(
  anchorRef: RefObject<HTMLElement | null>,
  floatingRef: RefObject<HTMLElement | null>,
  {
    placement = 'bottom',
    align = 'center',
    offset = 6,
    padding = 8,
    enabled = true,
    subscribe,
    bounds,
  }: FloatingOptions = {},
): FloatingPosition | null {
  const [position, setPosition] = useState<FloatingPosition | null>(null);

  const update = useCallback(() => {
    const anchor = anchorRef.current;
    const floating = floatingRef.current;
    if (!anchor || !floating) return;

    const anchorRect = anchor.getBoundingClientRect();
    const size = { width: floating.offsetWidth, height: floating.offsetHeight };

    const {
      x,
      y,
      placement: used,
    } = placeFloating(
      anchorRect,
      size,
      bounds?.() ?? { width: window.innerWidth, height: window.innerHeight },
      { placement, align, offset, padding },
    );

    setPosition((prev) =>
      prev && prev.x === x && prev.y === y && prev.placement === used
        ? prev
        : { x, y, placement: used },
    );
  }, [anchorRef, floatingRef, placement, align, offset, padding, bounds]);

  useLayoutEffect(() => {
    if (!enabled) {
      setPosition(null);
      return;
    }
    update();
  }, [enabled, update]);

  useEffect(() => {
    if (!enabled) return;
    // `true` on scroll catches scrolls in any ancestor, including the
    // canvas viewport, which is what moves an anchored node under us.
    window.addEventListener('scroll', update, true);
    window.addEventListener('resize', update);
    // The third reason, and the only one the DOM cannot raise on its own.
    const stop = subscribe?.(update);
    return () => {
      window.removeEventListener('scroll', update, true);
      window.removeEventListener('resize', update);
      stop?.();
    };
  }, [enabled, update, subscribe]);

  return position;
}
