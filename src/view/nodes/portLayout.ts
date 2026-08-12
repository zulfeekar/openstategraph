import {
  resolvePortSide,
  type FlowDirection,
  type IPortDescriptor,
  type PortSide,
} from '@core/model/contracts/ports';
import { bottomPortOffsets, type PillMetrics } from './bottomPorts';

/**
 * Where a port's dot is actually anchored, once appearance and flow direction
 * have both had their say.
 *
 * `pill` is its own anchor rather than "bottom, but bigger": a pill is drawn by
 * CSS at the card's bottom centre in *both* flow directions, so its dot follows
 * the rendered capsule and ignores the rotation that moves every other port.
 * The alternative — letting the pill rotate onto a flank with the rest of its
 * side — put the dot on the left edge while the capsule stayed drawn at bottom
 * centre, which is the same "link arrives beside the thing it binds to" defect
 * `bottomPorts.ts` exists to prevent, one flow direction along.
 */
export type PortAnchor = PortSide | 'pill';

/** A port's line in the card's footer legend. */
export interface PlannedPortRow {
  readonly port: IPortDescriptor;
  /** Which of the footer's two columns: inputs left, outputs right. */
  readonly column: 'in' | 'out';
  /** 1-based CSS grid row. Two ports sharing a row are drawn as a pair. */
  readonly row: number;
  /** Where this port's dot goes — the flank beside its row, or a card edge. */
  readonly anchor: PortAnchor;
}

export interface PortLayoutPlan {
  readonly rows: readonly PlannedPortRow[];
  /** Total footer rows, so a caller can size the grid without re-deriving it. */
  readonly rowCount: number;
  readonly anchors: ReadonlyMap<string, PortAnchor>;
  /** The one port drawn as the bus capsule, if this card has one. */
  readonly pill: IPortDescriptor | null;
}

/**
 * Assigns every port a footer row and an anchor.
 *
 * **The defect this replaces.** `.node__ports` is a two-column grid with
 * `grid-column` declared per port and the row left to auto-placement, and the
 * card emitted its rows in source order — every input, then every output. CSS
 * sparse auto-placement never moves its cursor backwards, so the first output
 * lands on the row of the *last* input rather than the first: an agent's
 * `prompt`, `skill`, `feedback`, `result` placed `result` on row 3, level with
 * `feedback`, and left row 1's right-hand cell empty. Two inputs and two
 * outputs came out worse still — four ports across three rows, none of them
 * paired. That is not cosmetic: `NodeCard.report()` measures a port's `y` from
 * its own row's rect, so a row placed oddly *is* a dot placed oddly.
 *
 * The fix is to stop asking auto-placement a question it answers per column
 * cursor rather than per column: each column is numbered independently from 1,
 * so the nth input and the nth output are on the nth row by construction.
 *
 * **Why edge-anchored ports sort last.** A binding — an agent's `skill`, a
 * tool's `tool` — keeps its footer label (that is the footer's job: it is the
 * card's legend, naming every port) but its dot is on the top or bottom edge,
 * not on the flank beside its row. Left where it was declared, `skill` sat
 * between `prompt` and `feedback` and put a dotless gap in the middle of the
 * left-hand stack. Sorted to the foot of its own column, the flank dots stay
 * contiguous and the legend-only lines trail below them.
 *
 * Pure, so "every declared port has a dot, no two on one point, in both flow
 * directions" is an assertion over the whole catalogue rather than a squint at
 * one card.
 */
export function planPortLayout(
  ports: readonly IPortDescriptor[],
  flow: FlowDirection,
): PortLayoutPlan {
  const anchors = new Map<string, PortAnchor>();
  for (const port of ports) {
    anchors.set(port.id, port.appearance === 'pill' ? 'pill' : resolvePortSide(port, flow));
  }

  const onFlank = (port: IPortDescriptor) => {
    const anchor = anchors.get(port.id);
    return anchor === 'left' || anchor === 'right';
  };

  const column = (direction: 'in' | 'out'): readonly IPortDescriptor[] => {
    const inColumn = ports.filter(
      (port) => port.direction === direction && (port.appearance ?? 'row') === 'row',
    );
    return [...inColumn.filter(onFlank), ...inColumn.filter((port) => !onFlank(port))];
  };

  const rows: PlannedPortRow[] = [];
  for (const direction of ['in', 'out'] as const) {
    column(direction).forEach((port, index) => {
      rows.push({
        port,
        column: direction,
        row: index + 1,
        anchor: anchors.get(port.id) ?? 'left',
      });
    });
  }

  return {
    rows,
    rowCount: rows.reduce((max, entry) => Math.max(max, entry.row), 0),
    anchors,
    pill: ports.find((port) => port.appearance === 'pill') ?? null,
  };
}

/** What the card measured about itself, in model units. */
export interface CardMetrics {
  readonly width: number;
  readonly height: number;
  /** Measured centre `y` of each footer row, keyed by port id. */
  readonly rowCentres: ReadonlyMap<string, number>;
  /** The rendered bus capsule, or `null` before it reaches the DOM. */
  readonly pill: PillMetrics | null;
  /** Half the capsule's height — its dot sits on the capsule's lower rim. */
  readonly pillOverhang: number;
}

export interface PortPoint {
  readonly x: number;
  readonly y: number;
}

/** Even spread of `count` items along `extent`, with a margin at each end. */
function spread(index: number, count: number, extent: number): number {
  return Math.round((extent * (index + 1)) / (count + 1));
}

/**
 * Turns a plan plus the card's measurements into one point per declared port.
 *
 * Every port in `plan.anchors` gets a point — there is no path that returns
 * fewer, which is what makes "no port is missing a dot" checkable rather than
 * hopeful. A flank port whose row has not been measured yet (first paint, before
 * layout) falls back to an even spread down the card rather than to the card's
 * middle, where a second unmeasured port would land on the same pixel.
 */
export function portPositions(plan: PortLayoutPlan, metrics: CardMetrics): Map<string, PortPoint> {
  const { width, height, rowCentres, pill, pillOverhang } = metrics;
  const points = new Map<string, PortPoint>();

  const ids = [...plan.anchors.keys()];
  const withAnchor = (wanted: PortAnchor) => ids.filter((id) => plan.anchors.get(id) === wanted);

  const topIds = withAnchor('top');
  topIds.forEach((id, index) => {
    points.set(id, { x: spread(index, topIds.length, width), y: 0 });
  });

  // The bottom edge can hold the bus capsule *and* plain dots at once — an
  // agent's `skill` and its `tools` are both bindings — so `bottomPortOffsets`
  // owns that arithmetic, measured from the rendered capsule rather than
  // re-derived from a number that would have to track a stylesheet.
  const bottomIds = [...withAnchor('bottom'), ...withAnchor('pill')];
  const bottomOffsets = bottomPortOffsets(
    bottomIds.map((id) => ({ id, isPill: plan.anchors.get(id) === 'pill' })),
    width,
    pill,
  );
  for (const id of bottomIds) {
    const isPill = plan.anchors.get(id) === 'pill';
    points.set(id, {
      x: bottomOffsets.get(id) ?? Math.round(width / 2),
      y: height + (isPill ? Math.round(pillOverhang) : 0),
    });
  }

  const rowOf = new Map(plan.rows.map((entry) => [entry.port.id, entry.row]));
  for (const side of ['left', 'right'] as const) {
    const flankIds = withAnchor(side);
    flankIds.forEach((id, index) => {
      const measured = rowCentres.get(id);
      const fallbackRow = rowOf.get(id);
      const y =
        measured ??
        (fallbackRow != null
          ? spread(fallbackRow - 1, plan.rowCount, height)
          : spread(index, flankIds.length, height));
      points.set(id, { x: side === 'left' ? 0 : width, y });
    });
  }

  return points;
}
