import { intersects, type Point, type Rect } from '@core/kernel/geometry';

/** The part of the viewport this needs: model coordinates → screen ones. */
export interface ScreenProjection {
  readonly zoom: number;
  localToClient(point: Point): Point;
}

/**
 * Is the minimap sitting on top of a node?
 *
 * The minimap floats over the bottom-right of the canvas and is opaque, so a
 * card dropped there simply disappears under it — hit within the first five
 * minutes of using the product, with `Hide minimap` the only way out
 * (production-ready 55.8). Auto-*avoidance* — moving the map, or moving the
 * card — trades one surprise for another: the map would wander, or a node
 * would land somewhere nobody dropped it. So the map yields instead, fading
 * to let the card show through and coming back at full strength on hover.
 *
 * Both rectangles are in client space, which is the only space they share:
 * the map is a DOM element and the nodes are model coordinates.
 */
export function coversAnyNode(
  mapRect: Rect | null,
  nodes: readonly Rect[],
  view: ScreenProjection,
): boolean {
  if (mapRect === null) return false;
  return nodes.some((node) => {
    const at = view.localToClient(node);
    return intersects(mapRect, {
      x: at.x,
      y: at.y,
      width: node.width * view.zoom,
      height: node.height * view.zoom,
    });
  });
}
