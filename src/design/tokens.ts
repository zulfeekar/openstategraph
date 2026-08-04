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
  root.style.setProperty('--canvas-grid-size', `${CANVAS.gridSize}px`);
  root.style.setProperty('--node-width', `${NODE.width}px`);
}
