/**
 * The one pure step of adding a toast — extracted so it can be *run*.
 *
 * `every-workflow-green` 26. Every deep-link message — "Opened: X", the
 * restored-draft notice, "could not open that" — was added to toast state and
 * removed again in the same breath, so a link never said anything. The cause
 * was a state updater with side effects in it: `notify` minted the id and
 * started the dismissal timer *inside* `setToasts`, and React is explicitly
 * allowed to call an updater more than once, so one `notify` could schedule
 * two timers — one keyed to an id the state never kept, which then dismissed a
 * live toast by number. Fixed in `9be5b53`.
 *
 * The fix is a rule about this function, and the rule is testable even though
 * the React defect was not: **it must be pure and idempotent.** Calling it
 * twice with the same arguments — which is exactly what React reserves the
 * right to do — must give the same answer and mint nothing. This repository's
 * vitest runs in `environment: 'node'`, so a hook cannot be rendered here; a
 * plain function can, which is why the rule was moved to one.
 */
export interface Toast {
  readonly id: number;
  readonly message: string;
}

/**
 * Add `toast` to `current`, deduplicating by message and keeping at most
 * `max`. Dragging a link repeatedly onto the same invalid port produces the
 * same complaint each time, and stacking five copies of it hides everything
 * else.
 */
export function appendToast(
  current: readonly Toast[],
  toast: Toast,
  max: number,
): readonly Toast[] {
  if (current.some((existing) => existing.message === toast.message)) return current;
  return [...current, toast].slice(-max);
}
