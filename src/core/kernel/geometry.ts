/**
 * Plain geometry value types plus the handful of operations the model
 * needs. Deliberately independent of JointJS's `g` namespace: the model
 * must not depend on the rendering library, and these types are what get
 * serialized.
 */

export interface Point {
  x: number;
  y: number;
}

export interface Size {
  width: number;
  height: number;
}

export interface Rect extends Point, Size {}

export const point = (x: number, y: number): Point => ({ x, y });
export const size = (width: number, height: number): Size => ({ width, height });

export function translate(p: Point, dx: number, dy: number): Point {
  return { x: p.x + dx, y: p.y + dy };
}

export function snap(value: number, grid: number): number {
  return grid > 0 ? Math.round(value / grid) * grid : value;
}

export function snapPoint(p: Point, grid: number): Point {
  return { x: snap(p.x, grid), y: snap(p.y, grid) };
}

export function rectOf(p: Point, s: Size): Rect {
  return { x: p.x, y: p.y, width: s.width, height: s.height };
}

export function rectCenter(r: Rect): Point {
  return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
}

/** Shortest distance from `p` to the line segment `a`–`b`. */
export function distanceToSegment(p: Point, a: Point, b: Point): number {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const lengthSquared = dx * dx + dy * dy;
  const t =
    lengthSquared === 0 ? 0 : clamp(((p.x - a.x) * dx + (p.y - a.y) * dy) / lengthSquared, 0, 1);
  const closest = { x: a.x + t * dx, y: a.y + t * dy };
  return Math.hypot(p.x - closest.x, p.y - closest.y);
}

export function containsRect(outer: Rect, inner: Rect): boolean {
  return (
    inner.x >= outer.x &&
    inner.y >= outer.y &&
    inner.x + inner.width <= outer.x + outer.width &&
    inner.y + inner.height <= outer.y + outer.height
  );
}

export function intersects(a: Rect, b: Rect): boolean {
  return a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y;
}

export function containsPoint(r: Rect, p: Point): boolean {
  return p.x >= r.x && p.x <= r.x + r.width && p.y >= r.y && p.y <= r.y + r.height;
}

/** Bounding box of a set of rects, or null for an empty set. */
export function unionRects(rects: readonly Rect[]): Rect | null {
  if (rects.length === 0) return null;
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const r of rects) {
    minX = Math.min(minX, r.x);
    minY = Math.min(minY, r.y);
    maxX = Math.max(maxX, r.x + r.width);
    maxY = Math.max(maxY, r.y + r.height);
  }
  return { x: minX, y: minY, width: maxX - minX, height: maxY - minY };
}

export function inflate(r: Rect, dx: number, dy: number = dx): Rect {
  return { x: r.x - dx, y: r.y - dy, width: r.width + dx * 2, height: r.height + dy * 2 };
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}
