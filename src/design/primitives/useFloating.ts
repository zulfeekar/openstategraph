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

function resolve(
  anchor: DOMRect,
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

function fitsInViewport(
  pos: { x: number; y: number },
  floating: { width: number; height: number },
  padding: number,
): boolean {
  return (
    pos.x >= padding &&
    pos.y >= padding &&
    pos.x + floating.width <= window.innerWidth - padding &&
    pos.y + floating.height <= window.innerHeight - padding
  );
}

/**
 * Minimal viewport-aware positioning for tooltips, menus and popovers:
 * measure, try the requested side, flip to the opposite side if it does
 * not fit, then clamp along the cross axis.
 *
 * Deliberately not a full floating-ui port — the app only ever anchors to
 * elements already inside the viewport, so flip + clamp is sufficient and
 * costs a few hundred bytes instead of 20kB.
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
  }: FloatingOptions = {},
): FloatingPosition | null {
  const [position, setPosition] = useState<FloatingPosition | null>(null);

  const update = useCallback(() => {
    const anchor = anchorRef.current;
    const floating = floatingRef.current;
    if (!anchor || !floating) return;

    const anchorRect = anchor.getBoundingClientRect();
    const size = { width: floating.offsetWidth, height: floating.offsetHeight };

    let used = placement;
    let next = resolve(anchorRect, size, used, align, offset);

    if (!fitsInViewport(next, size, padding)) {
      const flipped = resolve(anchorRect, size, OPPOSITE[used], align, offset);
      if (fitsInViewport(flipped, size, padding)) {
        used = OPPOSITE[used];
        next = flipped;
      }
    }

    // Clamp whatever remains out of bounds rather than leaving it clipped.
    const x = Math.min(Math.max(next.x, padding), window.innerWidth - size.width - padding);
    const y = Math.min(Math.max(next.y, padding), window.innerHeight - size.height - padding);

    setPosition((prev) =>
      prev && prev.x === x && prev.y === y && prev.placement === used
        ? prev
        : { x, y, placement: used },
    );
  }, [anchorRef, floatingRef, placement, align, offset, padding]);

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
    return () => {
      window.removeEventListener('scroll', update, true);
      window.removeEventListener('resize', update);
    };
  }, [enabled, update]);

  return position;
}
