/**
 * Whether the Workflows panel's **Examples** shelf starts open.
 *
 * install-experience T9. The examples were already opt-in on substance —
 * they live outside `workflows_root()`, so `GET /api/workflows`, the `/chat`
 * picker and the generated project knowledge cannot see them whatever their
 * envelope says, and taking one is a copy that severs. What was not opt-in was
 * their *prominence*: the shelf rendered all of them unconditionally, so a
 * fresh install's Workflows panel was one empty section of your own work above
 * twenty-three of someone else's. Before you have any workflow at all, that is
 * the difference between a product with a gallery and someone else's gallery
 * with a product attached.
 *
 * So the shelf is opt-in **by gesture** rather than by packaging: closed until
 * asked for, and the answer remembered — the `OnboardingHint` precedent, which
 * owns `openstategraph.onboarded` the same way and for the same reason. A
 * section that reopens itself after you closed it is the most annoying kind of
 * onboarding there is.
 *
 * (Splitting the gallery into its own extra or distribution was measured and
 * rejected: 578 KiB of a 3.7 MB wheel, against a second distribution to
 * version, a second `force_include` with its own loud-failure guard, and the
 * end of `examples.DATA = Path(__file__).parent` — which is exactly the
 * two-locations bug `workflows_root.py` exists to have ended.)
 *
 * Framework-free and storage-injected so it is directly unit-testable: the
 * decision is the feature, and the component around it is a projection of it.
 */

/** This browser's answer. Namespaced like every other key we set. */
export const EXAMPLES_SHELF_KEY = 'openstategraph.examplesShelf';

const OPEN = 'open';
const CLOSED = 'closed';

/**
 * A `localStorage`-shaped thing. Narrow on purpose — two methods is the whole
 * dependency, so a test hands over an object literal rather than a DOM.
 */
export interface ShelfStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

function ambientStorage(): ShelfStorage | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage;
  } catch {
    // Private mode, an embedded frame, a sandboxed iframe: no store, and the
    // shelf falls back to its default rather than throwing on render.
    return null;
  }
}

/**
 * Whether to render the shelf expanded on mount.
 *
 * **Closed unless this browser said otherwise.** Not "closed until you have a
 * workflow of your own": that rule would reopen the panel for anyone who
 * deleted their last one, which is the moment they least want twenty-three
 * strangers back.
 */
export function examplesShelfStartsOpen(storage: ShelfStorage | null = ambientStorage()): boolean {
  try {
    return storage?.getItem(EXAMPLES_SHELF_KEY) === OPEN;
  } catch {
    return false;
  }
}

/** Record the choice. Both directions — closing it is as much an answer. */
export function rememberExamplesShelf(
  open: boolean,
  storage: ShelfStorage | null = ambientStorage(),
): void {
  try {
    storage?.setItem(EXAMPLES_SHELF_KEY, open ? OPEN : CLOSED);
  } catch {
    /* the choice holds for this session and is simply not carried forward */
  }
}
