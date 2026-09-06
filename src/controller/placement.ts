import type { Point, Rect, Size } from '@core/kernel/geometry';

/**
 * Geometry over placed nodes.
 *
 * Shared by grouping (which container does this centre land in?) and selection
 * (what box encloses these nodes?). Kept out of `@core/kernel/geometry` because
 * these read a `{ position, size }` shape rather than a plain rect, and out of
 * either collaborator because both need them — duplicating would be duplicating
 * knowledge, not shape.
 */

export interface Placed {
  readonly position: Point;
  readonly size: Size;
}

export const rectOf = (node: Placed): Rect => ({
  x: node.position.x,
  y: node.position.y,
  width: node.size.width,
  height: node.size.height,
});

export const contains = (rect: Rect, p: Point): boolean =>
  p.x >= rect.x && p.x <= rect.x + rect.width && p.y >= rect.y && p.y <= rect.y + rect.height;

export const area = (rect: Rect): number => rect.width * rect.height;
