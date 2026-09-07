/**
 * The mark a run leaves behind while it is in flight, and what to say if the
 * editor comes back to find one.
 *
 * Reloading mid-run dropped the run with no notice (production-ready 55.6).
 * The stream dies with the page — that part is unavoidable — but the run had
 * already reached the server, its checkpoints are in `GET /api/threads`, and
 * the editor said nothing at all: no line, no way back to it, no sign that
 * anything had been happening. A person who reloads by reflex loses the
 * thread of what they were doing, not the run.
 *
 * `sessionStorage`, deliberately, and it carries the semantics for free: it
 * survives a reload of *this tab* and dies with the tab. A mark that outlived
 * the browser would announce a run from last Tuesday.
 *
 * The thread id is **not** here, because at the moment a run starts nobody
 * knows it — the backend mints it and reports it back on the terminal frame,
 * which is the frame a reload never receives. So this records that a run was
 * under way and which workflow it belonged to, and the answer to "which run"
 * is the History list, which reads the server rather than guessing.
 */

const KEY = 'openstategraph.run-in-flight';

/** The subset of `Storage` this needs, so a test can pass a plain object. */
export interface MarkStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

/** One run, under way when the page was last alive. */
export interface RunMark {
  /** The open workflow, when there was one. A canvas-only run has none. */
  readonly slug?: string;
  /** Epoch ms the run started. */
  readonly at: number;
}

function browserStorage(): MarkStorage | null {
  try {
    return window.sessionStorage;
  } catch {
    // Restricted contexts throw on access, not on use.
    return null;
  }
}

export function markRunInFlight(
  mark: RunMark,
  storage: MarkStorage | null = browserStorage(),
): void {
  try {
    storage?.setItem(KEY, JSON.stringify(mark));
  } catch {
    // A full or unavailable store costs a notice, never a run.
  }
}

export function clearRunInFlight(storage: MarkStorage | null = browserStorage()): void {
  try {
    storage?.removeItem(KEY);
  } catch {
    // As above.
  }
}

/**
 * The mark, if a run was in flight when this tab last rendered — and clearing
 * it in the same breath.
 *
 * Read-and-clear rather than read: the notice is about *this* reload. Leaving
 * it behind would greet the next reload with the same sentence, and a message
 * that repeats regardless of what happened is one people stop reading.
 */
export function takeInterruptedRun(storage: MarkStorage | null = browserStorage()): RunMark | null {
  let raw: string | null;
  try {
    raw = storage?.getItem(KEY) ?? null;
  } catch {
    return null;
  }
  if (raw === null) return null;
  clearRunInFlight(storage);
  try {
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== 'object' || parsed === null) return null;
    const { slug, at } = parsed as { slug?: unknown; at?: unknown };
    return {
      ...(typeof slug === 'string' && slug !== '' ? { slug } : {}),
      at: typeof at === 'number' ? at : 0,
    };
  } catch {
    // Someone else's key, or a half-written value. Not a run.
    return null;
  }
}

/**
 * What the editor says about it.
 *
 * Careful about the one thing it cannot know: whether the run finished. The
 * editor stopped watching, so the honest claim is about the *watching*, and
 * the server's own record is where the answer is.
 */
export function interruptedRunNotice(mark: RunMark): string {
  const workflow = mark.slug ? ` of ${mark.slug}` : '';
  return (
    `A run${workflow} was under way when this page reloaded — the editor stopped following it. ` +
    `It kept going on the server; what was recorded is in Past runs, below.`
  );
}
