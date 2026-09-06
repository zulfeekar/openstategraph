import { MARK } from '../tokens';

/**
 * The OpenStateGraph mark.
 *
 * The owner's authored logo, `Turn 2 — Circuit`, marked **LOCKED** in the
 * design project. Its own specification, quoted so nobody has to open the
 * design file to know what may be changed here (nothing):
 *
 * > A four-node graph traversed clockwise with one diagonal transition:
 * > hollow node = initial state, accent node = terminal state. Locked.
 * > Geometry sits on a 100-unit grid: 5.5-unit stroke, 10-unit node radius —
 * > one weight, no curves, no radius.
 *
 * **Every coordinate is the author's, transcribed rather than derived.** The
 * obvious derivation — a line stops at the node's rim, `24 + 10 + 5.5/2` —
 * gives 36.75 where the author drew 38, and 33.02 where the author drew 33.9.
 * The author drew a slightly larger gap than tangency, consistently, on all
 * four transitions. A mark that is locked is locked including the parts that
 * look like arithmetic.
 *
 * **The geometry is still not decoration.** `--osg-node-ring` (5.5) and
 * `--osg-node-r` (10) are two of the tokens the design system ships, and they
 * are the stroke and the radius of a node *on the canvas* as much as of a node
 * in the logo. They live in `design/tokens.ts` as `MARK`, for the reason that
 * file's own docstring gives — anything read by both TypeScript and the
 * stylesheet lives there — and `markGeometry.test.ts` fails if the two
 * descriptions ever disagree.
 *
 * **The two colours.** The authored SVG names `var(--color-text)` and
 * `var(--mark-accent)`, neither of which is a role in this product. They
 * resolve here as:
 *
 * - the ink → `currentColor`, so the mark takes the colour of whatever names
 *   the product. In the toolbar that is `--color-text-primary`, which in both
 *   themes now resolves to the authored ink.
 * - the terminal node → `--osg-node-terminal`, the authored token for exactly
 *   this ("accent node = terminal state"). It is the one accent voice, and it
 *   flips to the dark-ground accent with the theme on its own.
 *
 * A favicon has no CSS and no `currentColor`, so it can use neither. That copy
 * lives in `public/favicon.svg` and resolves both by inlining them — see the
 * comment inside that file.
 */
export function Mark({ size = 24, title }: { size?: number; title?: string }): React.JSX.Element {
  const { grid, ring, radius, hollowRadius, near, far, edgeGap, diagonalGap } = MARK;

  return (
    <svg
      viewBox={`0 0 ${grid} ${grid}`}
      width={size}
      height={size}
      role={title ? 'img' : 'presentation'}
      aria-hidden={title ? undefined : true}
      aria-label={title}
      focusable="false"
    >
      {title ? <title>{title}</title> : null}
      <g stroke="currentColor" strokeWidth={ring} fill="none">
        <line x1={edgeGap} y1={near} x2={grid - edgeGap} y2={near} />
        <line x1={far} y1={edgeGap} x2={far} y2={grid - edgeGap} />
        <line x1={grid - edgeGap} y1={far} x2={edgeGap} y2={far} />
        <line x1={diagonalGap} y1={diagonalGap} x2={grid - diagonalGap} y2={grid - diagonalGap} />
        <circle cx={near} cy={near} r={hollowRadius} />
      </g>
      <circle cx={far} cy={near} r={radius} fill="currentColor" />
      <circle cx={far} cy={far} r={radius} fill="currentColor" />
      <circle cx={near} cy={far} r={radius} fill="var(--osg-node-terminal)" />
    </svg>
  );
}
