import { LAYOUT } from '@design/tokens';

/**
 * How wide this person wants the right-hand column, and what stops a drag.
 *
 * `dockFit.ts` beside this file is the same question on the other axis, and
 * `stable-beta-public/16` is the ticket that asked for it: a long answer with
 * a table arrives in a chat column a little over 300px wide, and until now
 * `AppShell.css` said the plain truth — *"both panels are fixed width"*. The
 * dock's mechanism turned ninety degrees.
 *
 * Two things are kept apart here on purpose:
 *
 * - **The floor is derived, not stored.** It is what the open panels are
 *   worth today (`LAYOUT.inspectorWidth` each), so opening the Inspector
 *   beside the chat cannot squeeze either of them below the width they have
 *   always had. A single stored floor would have to be wrong for one of the
 *   two cases.
 * - **The ceiling is half the viewport**, which is a promise to the canvas
 *   rather than to the panels: this editor is a canvas, and a column that can
 *   eat it is a drag a user has no way back from except another drag.
 *
 * Pure, and takes the viewport and the storage as data, so every bound is
 * decidable in the `node` environment the suite runs in — the shape
 * `dockFit` and `dockHeightMemory` already use.
 */

const KEY = 'openstategraph.right-panels-width';

/** Which of the two right-hand panels are open. */
export interface OpenRightPanels {
  readonly ask?: boolean;
  readonly inspector?: boolean;
}

/** The width the open panels have always had — the narrowest the column goes. */
export function panelColumnMinWidth(open: OpenRightPanels): number {
  const panels = (open.ask ? 1 : 0) + (open.inspector ? 1 : 0);
  return Math.max(panels, 1) * LAYOUT.inspectorWidth;
}

/**
 * The widest the column may be, given the window it is sharing.
 *
 * Half the viewport — and the floor wins when the window is too narrow to
 * hold both halves, the same order `dockMaxHeight` keeps: a column narrower
 * than the panels inside it is unreadable, and the canvas has pan and zoom
 * while a panel has neither.
 */
export function panelColumnMaxWidth(viewportWidth: number, minWidth: number): number {
  return Math.max(minWidth, Math.round(viewportWidth / 2));
}

/** The width a drag asked for, brought inside what the window can give. */
export function clampPanelColumnWidth(
  requested: number,
  viewportWidth: number,
  minWidth: number,
): number {
  if (!Number.isFinite(requested)) return minWidth;
  return Math.min(
    Math.max(Math.round(requested), minWidth),
    panelColumnMaxWidth(viewportWidth, minWidth),
  );
}

/**
 * How far one arrow press moves the edge. The dock's step, deliberately: two
 * separators in one shell that move by different amounts are two gestures.
 */
export const PANEL_COLUMN_KEYBOARD_STEP = 24;

/**
 * The width a drag is asking for, given where it started.
 *
 * **The edge is the column's left one**, so the width grows as `clientX`
 * *falls* — the mirror of `dockHeightFromDrag`, and the one subtraction in
 * this feature that is only ever wrong in a hand. Unclamped: the shell owns
 * the clamp, because the bounds are facts about the window and the column
 * cannot see past itself.
 */
export function panelColumnWidthFromDrag(
  startWidth: number,
  startPointerX: number,
  pointerX: number,
): number {
  return startWidth + (startPointerX - pointerX);
}

/**
 * The width an arrow press is asking for, or `null` for a key this separator
 * has no opinion about — so the handler knows whether to `preventDefault`,
 * and a keyboard user can still Tab off the handle.
 */
export function panelColumnWidthFromArrow(width: number, key: string): number | null {
  if (key === 'ArrowLeft') return width + PANEL_COLUMN_KEYBOARD_STEP;
  if (key === 'ArrowRight') return width - PANEL_COLUMN_KEYBOARD_STEP;
  return null;
}

/**
 * The width this viewer last chose, or `null` for *no preference*.
 *
 * `null` rather than a default, because the default depends on which panels
 * are open and this module is read before that is known. The shell clamps
 * whatever comes back against the floor it can see. `localStorage` throws — a
 * private window, a browser set to block site data — so both directions are
 * wrapped, exactly as `dockHeightMemory` wraps them: a preference that
 * crashes the shell on a drag is worse than no preference at all.
 */
export function readPanelColumnWidth(storage: Storage | null = defaultStorage()): number | null {
  try {
    const stored = storage?.getItem(KEY) ?? null;
    if (stored === null || stored.trim() === '') return null;
    const parsed = Number(stored);
    return Number.isFinite(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export function rememberPanelColumnWidth(
  width: number,
  storage: Storage | null = defaultStorage(),
): void {
  try {
    storage?.setItem(KEY, String(Math.round(width)));
  } catch {
    // Storage unavailable — the width still holds for this session.
  }
}

function defaultStorage(): Storage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage;
  } catch {
    return null;
  }
}
