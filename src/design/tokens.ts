/**
 * The slice of the design system that TypeScript also needs.
 *
 * Canvas maths (viewport insets, grid pitch, node geometry) has to agree
 * with the stylesheet exactly or nodes drift a pixel off their ports.
 * Rather than duplicate numbers, anything read by both lives here and is
 * projected into CSS custom properties at boot by `applyLayoutTokens`.
 */

export const ACCENTS = [
  'blue',
  'indigo',
  'green',
  'amber',
  'orange',
  'red',
  'violet',
  'teal',
  'neutral',
] as const;

export type Accent = (typeof ACCENTS)[number];

export const THEMES = ['light', 'dark'] as const;
export type Theme = (typeof THEMES)[number];

/** Chrome dimensions. Mirrored into `--layout-*` custom properties. */
export const LAYOUT = {
  topbarHeight: 48,
  paletteWidth: 232,
  inspectorWidth: 300,
  /** The Workflows drawer. Here rather than inline in `WorkflowManager`
   * because `panelFit` has to add it up with the others (55.4), and a width
   * two places know is a width that drifts. */
  drawerWidth: 320,
} as const;

/** Canvas geometry. The single source of truth for the paper. */
export const CANVAS = {
  /** Dot-grid pitch in model units. */
  gridSize: 8,
  /** Movement is snapped to this multiple while dragging. */
  snapGrid: 8,
  /** Slack around the graph bounding box when fitting to the viewport. */
  fitPadding: 64,
  zoom: { min: 0.25, max: 2.5, step: 0.1, default: 1 } as const,
  /**
   * How the camera frames the node it is following.
   *
   * `fill` is the share of the viewport **width** the focused node should
   * span — 0.42 leaves the majority of the screen for its neighbours, so a
   * followed node is readable without becoming the only thing on screen.
   * Width because `NODE.width` is fixed for every card while height is
   * content (100 to 1068 model units on the shipped Chinook document), so a
   * height-derived scale would punish the tallest, most informative card —
   * see `focusZoomFor`. `maxZoom` is the readable ceiling for *automatic*
   * zoom: the user
   * may still zoom to `zoom.max` by hand, but the follower never magnifies a
   * card past mildly-larger-than-design on their behalf.
   */
  follow: { fill: 0.42, maxZoom: 1.25 } as const,
} as const;

/** Node card geometry, shared by the model's default sizes and the CSS. */
export const NODE = {
  width: 252,
  minHeight: 72,
  headerHeight: 44,
  portRowHeight: 24,
  portRadius: 4.5,
  /** Horizontal overhang of a port dot beyond the card edge. */
  portOverhang: 0,
  cornerRadius: 9,
} as const;

/**
 * Graph layout spacing, as fractions of a card's width.
 *
 * **Why a fraction, and why of the width.** These were four constants picked
 * once — 96 between ranks, 48 within one — and never re-derived when the card
 * grew to 252px. 96 is 38% of a card, which is tighter than anything the field
 * ships once you normalise for node size, and it is narrower than the labels
 * the canvas draws on a router's branches, so those labels landed on the next
 * card instead of in the gap. Width is the anchor because it is the one card
 * dimension design fixes: `NODE.width` is the same for every card, while
 * height runs from 72 to 700-odd with content, so a height-derived gap would
 * change meaning card by card.
 *
 * **`rank` — along the flow — is ¾ of a card, and that number was measured.**
 * Sweeping the rank gap over `chinook-assistant` while counting how many links
 * cross a card and how many cross each other, the crossings go 3, 3, **0**, 0,
 * 0 at ½, ⅔, ¾, ⅚ and 1 card width: ¾ is the threshold at which a five-way
 * router's fan stops tangling, because the extra along-flow run is what lets
 * bundled curves separate before they diverge. ¾ is also the best of those
 * five on the second example and in the top-to-bottom reading, so it is a
 * minimum rather than one graph's lucky number. The full table is in
 * `docs/decisions/edge-legibility.md`.
 *
 * It lands just above where the field sits once you normalise for node size —
 * Graphviz `dot` pairs a 0.5in `ranksep` with a 0.75in node, and React Flow's
 * ELK example pairs a 100px `nodeNodeBetweenLayers` with a 150px node, both
 * 0.67 — and it clears our own label rhythm, which puts a five-way router's
 * last branch label 154px along its link (`edgeDecoration`'s 50 + 4 × 26); a
 * gap shorter than that prints the label on the next card.
 *
 * **`node` — across the flow — is half the rank gap**, which is Graphviz's
 * documented pairing (`ranksep` 0.5in, `nodesep` 0.25in). The old 96/48 already
 * honoured that ratio; only the magnitude was wrong, so the ratio is kept
 * rather than reinvented, and it is expressed as arithmetic here so the two
 * cannot drift apart.
 *
 * **`edge`** separates parallel links sharing one gap. **`shelf`** is the
 * clearance between a card and the equipment slung under it — measured too:
 * at ⅙ of a card the outer tools of a three-tool shelf drew their lines across
 * the middle tool's card, and ⅓ is where that stops. **`margin`** is slack
 * around the whole graph.
 */
const RANK_GAP = Math.round((NODE.width * 3) / 4);

export const GRAPH_SPACING = {
  /** Between ranks: ¾ of a card. */
  rank: RANK_GAP,
  /** Within a rank: half the rank gap, per Graphviz's `ranksep` = 2 × `nodesep`. */
  node: Math.round(RANK_GAP / 2),
  /** Between parallel links sharing one gap. */
  edge: Math.round(RANK_GAP / 8),
  /** Between a card and the equipment shelf under it. */
  shelf: Math.round(NODE.width / 3),
  /** Slack around the whole graph. */
  margin: Math.round(NODE.width / 6),
} as const;

export const GROUP = {
  /** Inner slack kept between a group's border and its children. */
  padding: { top: 128, right: 40, bottom: 32, left: 40 },
  minWidth: 280,
  minHeight: 200,
  cornerRadius: 12,
} as const;

/**
 * Publish the TS-side layout constants as CSS custom properties so the
 * stylesheet and the canvas cannot disagree. Called once from bootstrap.
 */
export function applyLayoutTokens(root: HTMLElement = document.documentElement): void {
  root.style.setProperty('--layout-topbar-height', `${LAYOUT.topbarHeight}px`);
  root.style.setProperty('--layout-palette-width', `${LAYOUT.paletteWidth}px`);
  root.style.setProperty('--layout-inspector-width', `${LAYOUT.inspectorWidth}px`);
  root.style.setProperty('--layout-drawer-width', `${LAYOUT.drawerWidth}px`);
  root.style.setProperty('--canvas-grid-size', `${CANVAS.gridSize}px`);
  root.style.setProperty('--node-width', `${NODE.width}px`);
}
