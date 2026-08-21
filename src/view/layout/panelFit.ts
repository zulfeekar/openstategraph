import { LAYOUT, NODE } from '@design/tokens';

/**
 * Whether the open panels have to overlay the canvas instead of sharing the
 * row with it.
 *
 * The rule this replaces was a single `@media (max-width: 1100px)` in
 * `AppShell.css`, which asked the wrong question: it knew how wide the window
 * was and nothing about how much of it was already spoken for. Four columns
 * fit at 1280 — palette, chat, inspector and the Workflows drawer come to
 * 1152px — leaving about 140px of canvas, with nothing collapsing and nothing
 * said (production-ready 55.4). 1280 is a normal laptop.
 *
 * So the question is arithmetic, not a breakpoint: *does what is open leave
 * the canvas enough room to be a canvas?* One consequence worth stating —
 * opening a fourth panel on a wide screen is still fine, and closing one on a
 * narrow screen puts the rest back in the row. The old rule could express
 * neither.
 *
 * Pure, and takes the widths as data, so every combination is decidable in a
 * unit test rather than by resizing a browser.
 */

/**
 * The narrowest canvas still worth calling one: a card, plus a card's width of
 * air around it. Below this the canvas is a sliver you cannot drop into, which
 * is the state the ticket found.
 */
export const MIN_CANVAS_WIDTH = NODE.width * 2;

/** What each panel costs the row when it is open. */
export const PANEL_WIDTH = {
  palette: LAYOUT.paletteWidth,
  /** Both right-hand panels are `--layout-inspector-width` wide. */
  ask: LAYOUT.inspectorWidth,
  inspector: LAYOUT.inspectorWidth,
  workflows: LAYOUT.drawerWidth,
} as const;

export type PanelName = keyof typeof PANEL_WIDTH;

export type OpenPanels = { readonly [Name in PanelName]?: boolean };

/** The width the open panels take out of the shell's row. */
export function panelsWidth(open: OpenPanels): number {
  let total = 0;
  for (const name of Object.keys(PANEL_WIDTH) as PanelName[]) {
    if (open[name]) total += PANEL_WIDTH[name];
  }
  return total;
}

/** True when the row cannot hold the panels and a usable canvas at once. */
export function panelsMustOverlay(viewportWidth: number, open: OpenPanels): boolean {
  return viewportWidth - panelsWidth(open) < MIN_CANVAS_WIDTH;
}

/**
 * How much of the canvas's right edge the right-hand panels cover when they
 * overlay it instead of sharing the row.
 *
 * When the row has room, Ask and Inspector are flex siblings of the canvas —
 * the canvas element is already narrower by their width, so nothing more is
 * owed. When they overlay (production-ready 55.4), they float over the
 * canvas at `right: 0` instead of shrinking it, so the canvas element itself
 * is still full width and anything centred on it — the empty-state copy —
 * centres on space the panels are sitting on top of (production-ready 76).
 * Only Ask and Inspector overlay on the right; the palette and the Workflows
 * drawer are left-hand.
 */
export function rightOverlayWidth(
  overlay: boolean,
  open: Pick<OpenPanels, 'ask' | 'inspector'>,
): number {
  if (!overlay) return 0;
  return (open.ask ? PANEL_WIDTH.ask : 0) + (open.inspector ? PANEL_WIDTH.inspector : 0);
}
