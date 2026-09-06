/**
 * Tabs in one browser telling each other they saved — `osg-agent-experience/69`.
 *
 * ## Why this exists beside the SSE stream rather than instead of it
 *
 * `GET /api/workflows/{slug}/events` covers **every** writer, because it
 * watches the file: a second tab, `openstategraph` on the command line, a
 * coding agent through the MCP server. That is the correct mechanism and this
 * is not a replacement for it — a `BroadcastChannel` reaches only tabs of one
 * browser profile, which is a strict subset of the writers that matter.
 *
 * What it buys is **latency, in the case that is most likely to lose work**.
 * The stream's own poll is half a second and the round trip is on top; disk
 * autosave debounces at one second. So two tabs on one workflow — the case
 * this ticket is named after, and the one a single person actually creates —
 * can each write inside the other's blind window. A `postMessage` between
 * tabs of one browser is delivered in the same task, so the second tab knows
 * before its next debounce fires rather than after it.
 *
 * ## It carries the same revision, and that is what makes it safe to have two
 *
 * The frame is `{ slug, digest }`, identical to the SSE frame's payload,
 * because a listener must not be able to tell which transport a change arrived
 * on. Both end in `decideExternalChange` against `getKnownDigest(slug)`, so
 * hearing about one save twice is one refresh and one ignore, in either order
 * — the deduplication is the digest, not a sequence number, and it works
 * across transports precisely because there is only one revision stamp in this
 * system (`osg-agent-experience/45`'s).
 *
 * ## What it is not
 *
 * Not a lock, and not a leader election. `workflowStore`'s `WriteGuard` and
 * `claimSession` already answer *may this tab write*, over `localStorage`,
 * durably, and they answer it for a tab that was open before this channel
 * existed. This announces a fact after the fact; nothing waits on it, and a
 * browser with no `BroadcastChannel` loses the head start and nothing else.
 */

/** What one tab tells the others after it wrote. */
export interface WorkflowSavedAnnouncement {
  readonly slug: string;
  /** The digest the backend answered with — the file's revision after the write. */
  readonly digest: string;
}

/**
 * The channel name, spelled once.
 *
 * `BroadcastChannel` is keyed by name within an origin and the editor shares
 * its origin with the customer chat page, so the name says which product
 * surface it belongs to rather than just what it carries.
 */
export const WORKFLOW_SAVE_CHANNEL = 'openstategraph-workflow-saved';

/**
 * The one channel this tab holds, opened on first use.
 *
 * Lazy rather than at module load: a non-DOM host (a unit test, a worker) has
 * no `BroadcastChannel`, and constructing one at import time would make merely
 * importing `diskAutosave` throw there. `null` is a real answer — this browser
 * cannot do it — and every function below reads as a no-op under it.
 */
let channel: BroadcastChannel | null = null;
let unavailable = false;

function open(): BroadcastChannel | null {
  if (channel || unavailable) return channel;
  if (typeof BroadcastChannel === 'undefined') {
    unavailable = true;
    return null;
  }
  try {
    channel = new BroadcastChannel(WORKFLOW_SAVE_CHANNEL);
  } catch {
    // A browser that has the constructor and refuses it (a sandboxed frame,
    // a hardened profile) must cost this feature and nothing else.
    unavailable = true;
  }
  return channel;
}

/**
 * Say that this tab just wrote `slug`, and what revision the file now holds.
 *
 * Called after the backend answered, never before: announcing an intention
 * would tell the other tabs to refresh to a version that may have been
 * refused, which is the opposite of the 409 guard's whole point.
 *
 * A tab does not hear its own `postMessage` — that is `BroadcastChannel`'s own
 * rule, not something arranged here — so the writer needs no self-filter. The
 * digest check in `decideExternalChange` is still what makes a *reconnecting*
 * SSE stream harmless, and the two are independent on purpose.
 */
export function announceWorkflowSaved(slug: string, digest: string | undefined): void {
  if (!digest) return;
  try {
    open()?.postMessage({ slug, digest } satisfies WorkflowSavedAnnouncement);
  } catch {
    // A structured-clone failure on two strings is not a thing, but a closed
    // channel after a `bfcache` restore is — and losing the head start is the
    // documented cost of this whole module.
  }
}

/**
 * Hear the other tabs of this browser. Returns the unsubscribe.
 *
 * The listener is handed only well-formed announcements: a frame from a future
 * version of this editor, or from anything else that guessed the channel name,
 * is dropped here rather than reaching a caller that would treat a missing
 * digest as "the package is gone".
 */
export function subscribeWorkflowSaved(
  listener: (announcement: WorkflowSavedAnnouncement) => void,
): () => void {
  const live = open();
  if (!live) return () => {};
  const handler = (event: MessageEvent) => {
    const data = event.data as Partial<WorkflowSavedAnnouncement> | null;
    if (!data || typeof data.slug !== 'string' || typeof data.digest !== 'string') return;
    if (!data.slug || !data.digest) return;
    listener({ slug: data.slug, digest: data.digest });
  };
  live.addEventListener('message', handler);
  return () => live.removeEventListener('message', handler);
}

/**
 * Drop the channel — for tests, and for a host that has torn the page down.
 *
 * Closing rather than leaving it to garbage collection: an open
 * `BroadcastChannel` keeps its page referenced by the browser's messaging
 * machinery, and a test file that opened one in `jsdom` leaks it into the next.
 */
export function closeWorkflowSaveChannel(): void {
  channel?.close();
  channel = null;
  unavailable = false;
}
