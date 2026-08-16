/**
 * Which packages are already above whatever the editor has open.
 *
 * `mountCycleRefusal` is pure and takes the trail as an argument, which is what
 * makes it testable at every depth. Something still has to *know* the trail, and
 * the two facts it is made of — the open document's own slug and the drill-in
 * stack — live in `sessionStorage`, in `app/`. `core/` may not reach up there.
 *
 * So this is the seam, in the shape `workflowCatalogue` already established on
 * this very field: a synchronous answer that `core/` can ask for during a
 * render, kept current by something that knows more than `core/` does. A
 * **reader**, not a snapshot, deliberately — a stored copy would be one more
 * thing to invalidate on every load, drill, pop and save, and a stale copy here
 * refuses a legitimate mount, which is the one failure this feature must not
 * have. Asking is cheap; remembering is what goes wrong.
 *
 * The default reads empty, so a `core/` test, a worker, or the editor before
 * bootstrap refuses nothing. That is the right way to fail: the compiler is the
 * authority, and this only ever reports its verdict earlier.
 */

/** Oldest first — the drill trail, then the document on screen. */
export type MountAncestryReader = () => readonly string[];

const NONE: MountAncestryReader = () => [];

let read: MountAncestryReader = NONE;

/**
 * Install the reader. Called once, from the composition root.
 *
 * Returns the previous reader so a test can put it back rather than leaving a
 * module singleton pointing at its fixtures.
 */
export function provideMountAncestry(reader: MountAncestryReader): MountAncestryReader {
  const previous = read;
  read = reader;
  return previous;
}

/** The trail as it stands right now. Never throws; a broken reader reads empty. */
export function mountAncestry(): readonly string[] {
  try {
    return read();
  } catch {
    // A field's `validate` runs inside a render. A reader that throws must cost
    // the refusal, never the card.
    return [];
  }
}
