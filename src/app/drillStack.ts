/**
 * Where the user came from, when they drilled into a shared package.
 *
 * Clicking **Edit team** on a mount card loads another document into the same
 * editor. That is a navigation, and a navigation with no visible origin is a
 * teleport: the canvas simply becomes a different workflow, with nothing
 * saying which one, why, or how to get back. This module is the missing half —
 * the trail of parents, so a banner can name where you are and offer the way
 * out.
 *
 * A **stack**, not a single "previous", because drill-ins nest: a workflow
 * mounts a team, that team mounts another. Popping one frame must return you
 * one level, not all the way to the start.
 *
 * `sessionStorage`, matching `CURRENT_SLUG_KEY`: the trail belongs to this tab
 * and this session, exactly like the slug it complements, and it must survive
 * the reload a workflow load can trigger without outliving the tab.
 *
 * Pure and framework-free on purpose — the whole point of separating it from
 * the banner is that push/pop/clear/round-trip are testable without React.
 */

export const DRILL_STACK_KEY = 'openstategraph.drillstack';

/** One rung of the trail: the workflow the user drilled *out of*. */
export interface DrillFrame {
  /** Slug to load to get back — identity, so a rename cannot break the return. */
  readonly slug: string;
  /** Display name, for the banner. Cosmetic; never used to load. */
  readonly name: string;
}

type Listener = () => void;

const listeners = new Set<Listener>();

/**
 * The trail, oldest first. Always re-read from storage rather than mirrored in
 * a module variable: a workflow load may reload the page, and a mirror would
 * then disagree with what persisted.
 */
export function readDrillStack(): readonly DrillFrame[] {
  let raw: string | null;
  try {
    raw = sessionStorage.getItem(DRILL_STACK_KEY);
  } catch {
    return [];
  }
  if (!raw) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    // Hand-written or stale storage is not a crash: keep the well-formed
    // frames and drop the rest, so a bad entry costs the trail, not the app.
    return parsed.filter(isFrame);
  } catch {
    return [];
  }
}

function isFrame(value: unknown): value is DrillFrame {
  if (!value || typeof value !== 'object') return false;
  const frame = value as Partial<DrillFrame>;
  return typeof frame.slug === 'string' && frame.slug !== '' && typeof frame.name === 'string';
}

/** The workflow one Back click would return to, if any. */
export function peekDrillFrame(): DrillFrame | undefined {
  const stack = readDrillStack();
  return stack.length > 0 ? stack[stack.length - 1] : undefined;
}

/**
 * Record that the user is leaving `frame` to drill into a child.
 *
 * Re-entering a workflow already on the trail truncates back to it rather than
 * growing a second copy: A → B → A is one level deep, not two, and a stack
 * that disagreed would demand two Backs to undo one drill-in.
 */
export function pushDrillFrame(frame: DrillFrame): readonly DrillFrame[] {
  const existing = readDrillStack();
  const seen = existing.findIndex((entry) => entry.slug === frame.slug);
  const next = (seen >= 0 ? existing.slice(0, seen) : existing).concat(frame);
  return write(next);
}

/** Take the top frame off and hand it back — the Back click's other half. */
export function popDrillFrame(): DrillFrame | undefined {
  const stack = readDrillStack();
  if (stack.length === 0) return undefined;
  const top = stack[stack.length - 1];
  write(stack.slice(0, -1));
  return top;
}

/**
 * Forget the trail entirely.
 *
 * Called whenever a workflow is loaded through the ordinary Workflows panel: a
 * manual load is a navigation of its own, and offering "Back to …" afterwards
 * would point at a parent the user deliberately left.
 */
export function clearDrillStack(): void {
  write([]);
}

function write(stack: readonly DrillFrame[]): readonly DrillFrame[] {
  try {
    if (stack.length === 0) sessionStorage.removeItem(DRILL_STACK_KEY);
    else sessionStorage.setItem(DRILL_STACK_KEY, JSON.stringify(stack));
  } catch {
    // Storage unavailable — the banner simply never appears; nothing else
    // in the editor depends on the trail.
  }
  for (const listener of listeners) listener();
  return stack;
}

/** Subscribe to changes. Returns the unsubscribe, same shape as the engine's. */
export function subscribeDrillStack(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
