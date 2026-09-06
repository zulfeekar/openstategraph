import { unionRects, type Rect, type Size } from '@core/kernel/geometry';

/**
 * **Why this lives in `core/model/` rather than beside `canvas/layout/`.**
 * "How a frame wraps its children" is a fact about the model, and two layers
 * need it: `GroupingController` when it creates a container around a
 * selection, and `AutoLayout` when it re-wraps one afterwards. `controller/`
 * must not import from `canvas/` — that is the layering rule — so a home in
 * `canvas/` would have forced a second copy of the same arithmetic, which is
 * precisely the duplicated *knowledge* that goes quietly wrong. `bindingLayout`
 * stays in `canvas/layout/` because it is about layout, which only the canvas
 * does; this is about containment, which the model owns.
 */

/** The slack a frame keeps between its border and its children. */
export interface Padding {
  readonly top: number;
  readonly right: number;
  readonly bottom: number;
  readonly left: number;
}

/** A container, reduced to what fitting reasons about. */
export interface ContainerShape {
  readonly id: string;
  readonly childIds: readonly string[];
  /** What it measures now — returned unchanged when it has nothing to wrap. */
  readonly rect: Rect;
}

/**
 * One frame's rect, given the box its children occupy.
 *
 * The single definition of the arithmetic, so the frame a **new** group is
 * created with and the frame `AutoLayout` **re-fits** cannot disagree.
 *
 * The padding is asymmetric on purpose — `top` is 128 because a frame has a
 * title bar — and the minimum grows the frame right and down only, so the
 * top-left stays welded to the children and the gap above the first card is
 * exactly `padding.top` whatever the minimum turns out to be. Fitting
 * symmetrically would tuck that card under the title, which is the one thing
 * the padding exists to prevent.
 */
export function fitAround(childrenBox: Rect, padding: Padding, minimum: Size): Rect {
  return {
    x: Math.round(childrenBox.x - padding.left),
    y: Math.round(childrenBox.y - padding.top),
    width: Math.round(Math.max(minimum.width, childrenBox.width + padding.left + padding.right)),
    height: Math.round(Math.max(minimum.height, childrenBox.height + padding.top + padding.bottom)),
  };
}

/**
 * Every frame re-wrapped around its children, after something moved them.
 *
 * **Why this is needed.** `AutoLayout` excludes containers and annotations
 * from the ranking, and rightly: a frame has no edges, so a layered algorithm
 * would park it in a rank of its own. But nothing put it back. Every card
 * inside a group moved to its new rank while the group's own rectangle stayed
 * where it was, so on the seeded demo the "Ask the database" frame ended up
 * floating over cards it has nothing to do with.
 *
 * Pure by construction — rects in, rects out — the same shape as
 * `bindingLayout`, and for the same reason: this is arithmetic with awkward
 * cases in it, and arithmetic belongs somewhere it can be asserted on rather
 * than eyeballed through a browser.
 *
 * Two of those cases beyond the padding itself, each of which is a test:
 *
 * - **Nesting.** An outer frame must be measured against the *fitted* inner
 *   one, not the stale rect the inner frame had before the layout. So this
 *   resolves depth-first and memoises, rather than looping over a flat list.
 * - **A childless frame is left exactly as it is** — absent from the result
 *   entirely, so no move and no resize is emitted for it. Collapsing it to
 *   zero, or to the minimum parked at the origin, would read as the layout
 *   having deleted a label somebody placed on purpose.
 */
export function fitContainers(
  containers: readonly ContainerShape[],
  leafRects: ReadonlyMap<string, Rect>,
  padding: Padding,
  minimum: Size,
): ReadonlyMap<string, Rect> {
  const byId = new Map(containers.map((container) => [container.id, container]));
  const fitted = new Map<string, Rect>();
  const resolving = new Set<string>();
  /**
   * Containers caught in a parent cycle. Every one of them is dropped at the
   * end rather than merely broken out of: once a cycle is entered, one member
   * is measured against another member's *stale* rect, so every fit computed
   * around the loop is arbitrary. Moving a frame to an arbitrary place is
   * worse than leaving it where the user put it.
   */
  const cyclic = new Set<string>();

  /** This container's rect after fitting, or its current one if it cannot. */
  const resolve = (id: string): Rect => {
    const container = byId.get(id);
    if (!container) return leafRects.get(id) ?? { x: 0, y: 0, width: 0, height: 0 };
    const already = fitted.get(id);
    if (already) return already;
    // A container that (transitively) contains itself is not something the
    // model can produce, but a pure function that loops forever on bad input
    // is still a bug — and a frozen canvas cannot be undone. Everything
    // currently on the stack *is* the cycle, so the whole loop is condemned.
    if (resolving.has(id)) {
      for (const member of resolving) cyclic.add(member);
      return container.rect;
    }
    resolving.add(id);

    const childRects = container.childIds
      .map((childId) => (byId.has(childId) ? resolve(childId) : leafRects.get(childId)))
      .filter((childRect): childRect is Rect => childRect != null);
    resolving.delete(id);

    const box = unionRects(childRects);
    // Nothing to wrap: keep what it has, and record nothing so no move or
    // resize is emitted for it at all.
    if (!box) return container.rect;

    const next = fitAround(box, padding, minimum);
    fitted.set(id, next);
    return next;
  };

  for (const container of containers) resolve(container.id);
  for (const id of cyclic) fitted.delete(id);
  return fitted;
}

/**
 * Ancestors before descendants.
 *
 * **Load-bearing, not tidiness.** `JointGraphAdapter` applies a move with
 * `element.position(x, y, { deep: true })` — deliberately, so that dragging a
 * frame carries its children the way the user saw it drag. The model, though,
 * moves only the node it was told to move. So when a frame and its children
 * are all repositioned in one batch, the frame's deep move shifts children the
 * graph has already been told about, and only a later *absolute* set for each
 * descendant brings the two back into agreement.
 *
 * Emitting in this order is what makes that hold: every node is positioned
 * after every ancestor of it, so the last write for any node is its own
 * absolute one.
 */
export function depthFirstOrder(
  ids: readonly string[],
  parentOf: (id: string) => string | null,
): readonly string[] {
  const depthOf = new Map<string, number>();
  const depth = (id: string): number => {
    const known = depthOf.get(id);
    if (known !== undefined) return known;
    // Provisional value first: it both memoises and breaks a parent cycle,
    // since a second visit finds this instead of recursing again.
    depthOf.set(id, 0);
    const parent = parentOf(id);
    const value = parent === null ? 0 : depth(parent) + 1;
    depthOf.set(id, value);
    return value;
  };
  return [...ids]
    .map((id, index) => ({ id, index, depth: depth(id) }))
    .sort((a, b) => a.depth - b.depth || a.index - b.index)
    .map((entry) => entry.id);
}
