import { LAYOUT, NODE } from '@design/tokens';

/**
 * The height axis of the shell, which until now did not exist.
 *
 * `panelFit.ts` beside this file adds up **widths**: every panel this editor
 * has ever had took a column out of one row, and `LAYOUT` carried exactly one
 * height (`topbarHeight`) that nothing could move. `memory-and-replay` 51 adds
 * a bottom dock with a draggable top edge, so for the first time a gesture
 * changes how tall the rest of the app is — and that question is arithmetic
 * for the same reason the width question is: *does what is open leave the
 * canvas enough room to be a canvas?*
 *
 * Its own module rather than three more exports on `panelFit`, because the two
 * axes answer to different things. `panelFit` is driven by which panels are
 * open — a set of booleans — and this is driven by one number a user is
 * dragging. Pure, and takes the shell's height as data, so every clamp is
 * decidable in a unit test rather than by dragging a browser.
 */

/**
 * The shortest canvas still worth calling one.
 *
 * The sibling of `MIN_CANVAS_WIDTH`, and derived the same way: a card, plus a
 * card's worth of air around it. `NODE.minHeight` is the floor of a card
 * rather than its typical size (the shipped Chinook document has cards over a
 * thousand model units tall), so four of them is deliberately generous —
 * a canvas you cannot drop a card into and still see it is the state the dock
 * must never be allowed to create.
 */
export const MIN_CANVAS_HEIGHT = NODE.minHeight * 4;

/**
 * How tall the dock opens the first time anybody opens it.
 *
 * Enough for the head row, five or six lanes and the caveat line — a run's
 * *shape* readable without a drag, which is the whole claim the bars make.
 * Anything taller opens by eating the canvas, and the first thing a user would
 * do is drag it back down.
 */
export const DOCK_DEFAULT_HEIGHT = 260;

/**
 * The shortest the dock may be dragged and still be a dock.
 *
 * The head row plus two lanes plus the caveat. Below this the drag has
 * produced a strip that says nothing, and a user has no way back except to
 * find the same 6px edge again — so the floor is here rather than at zero.
 * Closing it is a different gesture, and it has a button and a shortcut.
 */
export const DOCK_MIN_HEIGHT = 140;

/**
 * The tallest the dock may be, given the shell it is sharing.
 *
 * Not a fraction of the window: a percentage claims to know how much room the
 * canvas needs and does not. This subtracts what is actually spoken for — the
 * top bar's row, and the canvas's own floor — which is the same arithmetic
 * `panelsMustOverlay` does across the other axis.
 *
 * On a window too short to hold all three, the floor wins over the ceiling and
 * this returns `DOCK_MIN_HEIGHT`. That is a deliberate order: a dock squeezed
 * below its floor is unreadable, and the canvas has pan and zoom while the
 * dock has neither.
 */
export function dockMaxHeight(shellHeight: number): number {
  return Math.max(DOCK_MIN_HEIGHT, shellHeight - LAYOUT.topbarHeight - MIN_CANVAS_HEIGHT);
}

/** The height a drag asked for, brought inside what the shell can give. */
export function clampDockHeight(requested: number, shellHeight: number): number {
  if (!Number.isFinite(requested)) return DOCK_DEFAULT_HEIGHT;
  return Math.min(Math.max(Math.round(requested), DOCK_MIN_HEIGHT), dockMaxHeight(shellHeight));
}
