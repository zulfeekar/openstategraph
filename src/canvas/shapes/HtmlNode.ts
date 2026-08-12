import { dia } from '@joint/core';
import { NODE } from '@design/tokens';
import type { Point } from '@core/kernel/geometry';
import { LINK_CONNECTOR, LINK_ROUTER } from '../links/edgeDecoration';

export const HTML_NODE_TYPE = 'openstategraph.HtmlNode';
export const LINK_TYPE = 'openstategraph.Link';
export const PORT_GROUP = 'io';

/**
 * Geometry a rendered card reports back about itself.
 *
 * Node cards are content-driven: their height and the vertical position of
 * every port row are consequences of the HTML that React laid out, not
 * numbers the model can know in advance. The React card measures itself and
 * hands this back, and the adapter writes it onto the JointJS cell so links
 * land exactly on the dot the user sees.
 */
export interface NodeGeometry {
  readonly height: number;
  /** Port id → offset from the card's top-left, in model units. */
  readonly ports: Readonly<Record<string, Point>>;
}

/**
 * Port markup: a wide invisible hit target plus the visible dot.
 *
 * Splitting them is what makes ports easy to grab — a 4.5px dot is a
 * frustrating drag target, but enlarging the dot itself would wreck the
 * card's proportions. The hit circle carries the magnet; the dot is inert.
 */
const PORT_MARKUP: dia.MarkupJSON = [
  { tagName: 'circle', selector: 'portHit' },
  { tagName: 'circle', selector: 'portDot' },
];

/**
 * An element whose body is real HTML.
 *
 * A `foreignObject` holds a div that React portals into, so node bodies are
 * ordinary components with ordinary CSS — which is the only way to get the
 * typography, form controls and Markdown rendering this UI needs. Ports and
 * links stay SVG, so JointJS keeps handling magnets, routing and hit
 * testing natively.
 */
export const HtmlNode = dia.Element.define(
  HTML_NODE_TYPE,
  {
    size: { width: NODE.width, height: NODE.minHeight },
    attrs: {
      root: {
        // The card itself must not be a magnet, or dragging from anywhere on
        // it would start a link instead of moving the node.
        magnet: false,
      },
      foreignObject: {
        // `calc()` keeps the HTML wrapper locked to the element's size
        // without a resize handler.
        width: 'calc(w)',
        height: 'calc(h)',
      },
    },
    ports: {
      groups: {
        [PORT_GROUP]: {
          // Every port's position is supplied explicitly from the measured
          // card, so no built-in layout applies.
          position: 'absolute',
          markup: PORT_MARKUP,
          // Only geometry and behaviour here — every colour is applied from
          // `canvas.css`. SVG *presentation attributes* do not understand
          // `var()`, so a themed colour set this way silently falls back to
          // black; as a CSS property it resolves correctly and re-themes.
          attrs: {
            portHit: {
              r: 10,
              magnet: 'active',
              cursor: 'crosshair',
            },
            portDot: {
              r: NODE.portRadius,
              strokeWidth: 1.5,
              pointerEvents: 'none',
            },
          },
        },
      },
    },
  },
  {
    markup: [
      {
        tagName: 'foreignObject',
        selector: 'foreignObject',
        attributes: { overflow: 'visible' },
        children: [
          {
            tagName: 'div',
            namespaceURI: 'http://www.w3.org/1999/xhtml',
            selector: 'mount',
            className: 'node-mount',
          },
        ],
      },
    ],
  },
);

/**
 * The link between two ports.
 *
 * Styled through CSS custom properties rather than hardcoded colours so it
 * re-themes with everything else, and given a wide transparent overlay so
 * it can be selected without pixel-hunting a 1.5px line.
 */
export const FlowLink = dia.Link.define(
  LINK_TYPE,
  {
    // Geometry only; stroke colours come from `canvas.css` for the same
    // reason as the ports above.
    attrs: {
      line: {
        connection: true,
        strokeWidth: 1.5,
        strokeLinecap: 'round',
        fill: 'none',
        // Direction must be legible at rest (ticket 44): a filled chevron on
        // the target end. `context-stroke` makes the head follow the line's
        // *rendered* stroke — including the CSS hover/selected/active
        // colours — with no per-state marker plumbing.
        targetMarker: {
          type: 'path',
          d: 'M 9 -4.5 0 0 9 4.5 z',
          fill: 'context-stroke',
          stroke: 'none',
        },
      },
      outline: {
        connection: true,
        strokeWidth: 12,
        strokeLinecap: 'round',
        fill: 'none',
      },
      // The casing: a stroke in the canvas colour, a little wider than the
      // line and drawn just beneath it. Where two links cross, the one drawn
      // later breaks the one drawn earlier, so a crossing reads as an
      // over/under rather than as a junction where two flows merge.
      //
      // This is the cartographer's answer. It was originally the *only* one
      // available — JointJS's `jumpover` connector needs straight polyline
      // segments, which curves are not. Runs are orthogonal now, so jumpover
      // has become possible; casing is kept anyway. A hop is a mark the reader
      // has to decode, a break is not, and jumpover recomputes every
      // intersection on every render where casing is one extra path and the
      // graph's own z-order.
      casing: {
        connection: true,
        strokeWidth: 5,
        strokeLinecap: 'butt',
        fill: 'none',
      },
    },
    // A rigid orthogonal run, asked for by name: *"instead of spline would it
    // be possible to have rigid flow line"*. The route is the router's (see
    // `linkRouter`); the connector only decides what a corner looks like.
    connector: LINK_CONNECTOR,
    router: LINK_ROUTER,
    z: -1,
  },
  {
    markup: [
      { tagName: 'path', selector: 'outline', attributes: { 'pointer-events': 'stroke' } },
      { tagName: 'path', selector: 'casing', attributes: { 'pointer-events': 'none' } },
      { tagName: 'path', selector: 'line', attributes: { 'pointer-events': 'none' } },
    ],
  },
);

/** Cell namespace handed to the graph so serialized types resolve. */
export const CELL_NAMESPACE = {
  openstategraph: { HtmlNode, Link: FlowLink },
};

/* ------------------------------------------------------------------ *
 * Mount registry — the bridge from JointJS views to React.
 * ------------------------------------------------------------------ */

export type MountListener = () => void;

/**
 * Tracks the live DOM mount point for each node.
 *
 * JointJS owns element view lifecycle; React owns the card contents. This
 * registry is the seam: a view publishes its mount div here on render and
 * withdraws it on removal, and a single React component renders a portal
 * per entry. Without it, React would have no stable handle on DOM that
 * another library creates and destroys.
 */
export class NodeMountRegistry {
  private readonly mounts = new Map<string, HTMLElement>();
  private readonly listeners = new Set<MountListener>();

  /**
   * Memoised snapshot.
   *
   * `useSyncExternalStore` calls the snapshot getter on every render and
   * compares by identity — returning a freshly built array each time reads as
   * "changed on every render" and spins forever. The cache is rebuilt only
   * when the map actually changes.
   */
  private snapshot: readonly [string, HTMLElement][] = [];

  set(nodeId: string, element: HTMLElement): void {
    if (this.mounts.get(nodeId) === element) return;
    this.mounts.set(nodeId, element);
    this.invalidate();
  }

  delete(nodeId: string): void {
    if (this.mounts.delete(nodeId)) this.invalidate();
  }

  entries(): readonly [string, HTMLElement][] {
    return this.snapshot;
  }

  subscribe(listener: MountListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  clear(): void {
    if (this.mounts.size === 0) return;
    this.mounts.clear();
    this.invalidate();
  }

  private invalidate(): void {
    this.snapshot = [...this.mounts.entries()];
    // Deferred to a microtask so a burst of view renders (an import, a
    // paste) produces one React update rather than one per node.
    queueMicrotask(() => {
      for (const listener of this.listeners) listener();
    });
  }
}

/**
 * Builds the element view class bound to a mount registry.
 *
 * A factory rather than a plain class so the registry is injected instead of
 * reached for globally — two papers in one page keep separate registries.
 */
export function defineHtmlNodeView(mounts: NodeMountRegistry): typeof dia.ElementView {
  class HtmlNodeView extends dia.ElementView {
    override render(): this {
      super.render();
      this.publishMount();
      return this;
    }

    protected override onRemove(): void {
      mounts.delete(String(this.model.id));
      super.onRemove();
    }

    /**
     * Hands the freshly created mount div to React.
     *
     * Re-published on every render because JointJS recreates the markup —
     * and therefore the div — whenever it re-renders a view, which would
     * otherwise leave React portaling into a detached node.
     */
    private publishMount(): void {
      const mount = this.findNode('mount');
      if (mount instanceof HTMLElement) {
        mounts.set(String(this.model.id), mount);
      }
    }
  }

  // `ElementView` is generic over its model, and a subclass fixing that
  // parameter is not assignable to the generic constructor the paper option
  // expects. The behaviour is correct; only the variance needs asserting.
  return HtmlNodeView as unknown as typeof dia.ElementView;
}
