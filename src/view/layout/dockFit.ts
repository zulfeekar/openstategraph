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

/**
 * How far one arrow press moves the edge.
 *
 * Here rather than in `RunDock`, because the two functions below are the only
 * places the number means anything and a step whose direction lives in one
 * module and whose size lives in another is two descriptions of one gesture.
 */
export const DOCK_KEYBOARD_STEP = 24;

/**
 * The height a drag is asking for, given where it started.
 *
 * **The edge is the dock's bottom one** (`memory-and-replay` 63): the surface
 * sits under the top bar and pushes the paper down, so its free edge is the
 * lower one and the height grows as `clientY` grows. Under `51` it was the
 * other edge and the other sign, and this is the whole of that difference —
 * one subtraction, written in the direction the panel is actually docked.
 *
 * Unclamped. The shell owns the clamp: the ceiling is a fact about how tall
 * the shell is, and the dock cannot see past itself.
 */
export function dockHeightFromDrag(
  startHeight: number,
  startPointerY: number,
  pointerY: number,
): number {
  return startHeight + (pointerY - startPointerY);
}

/**
 * The height an arrow press is asking for, or `null` for a key this separator
 * has no opinion about.
 *
 * `null` rather than the unchanged height, so the handler knows whether to
 * call `preventDefault`: a separator that swallows Tab is a separator a
 * keyboard user cannot leave.
 */
export function dockHeightFromArrow(height: number, key: string): number | null {
  if (key === 'ArrowDown') return height + DOCK_KEYBOARD_STEP;
  if (key === 'ArrowUp') return height - DOCK_KEYBOARD_STEP;
  return null;
}
