/**
 * The sitting a run belongs to — the one identity a client is entitled to mint.
 *
 * `memory-and-replay/45`. `session_id` was a complete feature except for a
 * writer: declared on `RunRequest`, carried into `configurable` by all four
 * doors, persisted into every checkpoint's metadata, read back onto
 * `ThreadSummary`, and filterable on `GET /api/threads?session_id=`, on
 * `openstategraph threads list --session` and on `runs list --session`. Nothing
 * populated it, so it was `""` on every real run and every one of those filters
 * matched the entire listing while looking like a working feature.
 *
 * ## Why the client mints this when it is forbidden to mint `user_email`
 *
 * `principal.py` refuses a client-supplied `user_email` and `RunRequest` has no
 * such field at all. Read that rule precisely: the danger it names is not
 * "client-supplied", it is **client-supplied and privilege-bearing** —
 * `user_email` keys a per-person memory namespace, so a client that could name
 * the person could read and write that person's memories.
 *
 * `session_id` grants nothing. It never enters a Store namespace (the memory
 * research settled that, and `RunRequest` says so at the field), no guard
 * consults it, and it changes no run's behaviour. It is a *label* on rows that
 * are already reachable in full without it — the worst a forged one achieves is
 * grouping your own runs under a name you chose.
 *
 * The proof that this is the existing rule rather than a new exemption is
 * `thread_id`, which the client has always minted and sent: a thread *selects a
 * checkpoint to continue*, which is strictly more power than a listing filter.
 * If a client may name the conversation, it may name the sitting.
 *
 * And it must, because the server cannot: a browser tab is a thing only the
 * browser knows about. Server-side minting would produce one "session" per
 * request — a synonym for `thread_id` — which is the axis `43` settled against.
 *
 * ## Why this is a second key beside `DRAFT_SESSION_KEY`
 *
 * `workflowDrafts.DRAFT_SESSION_KEY` is the same word on a different concept.
 * It holds *which draft key this tab autosaves under* — `slug-<slug>` or
 * `wf-<timestamp>` — and `startWorkflowSession` **re-keys it every time the
 * open workflow changes**. Reusing it would make "session" mean "the workflow I
 * happen to have open": one sitting would split into several the moment a user
 * loaded a second workflow, and two tabs editing one workflow would collapse
 * into one session. That is the opposite of the axis this field exists for, so
 * the words stay apart and each keeps one job.
 *
 * ## The lifetime, stated so nothing has to infer it
 *
 * **A browser tab.** `sessionStorage` is exactly that lifetime and nothing has
 * to be written to maintain it: it survives a reload and a crash restore, it is
 * not shared with another tab, and it dies when the tab does. That is what a
 * *sitting* is, and it is deliberately not a login — who a person is over time
 * is `user_email`'s job, decided by the server, and this field must never grow
 * into a second answer to it.
 */

/** The narrow slice of `Storage` this needs, so a test supplies a plain object. */
export interface SessionStore {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

/**
 * Where a tab records the sitting its runs belong to.
 *
 * Deliberately not `openstategraph-current-workflow-id` — see the module note.
 */
export const BROWSER_SESSION_KEY = 'openstategraph-run-session';

/** A value nothing else could have produced, and nothing can read anything out of. */
function mintSessionId(): string {
  const random =
    typeof globalThis.crypto?.randomUUID === 'function'
      ? globalThis.crypto.randomUUID().replace(/-/g, '').slice(0, 12)
      : Math.random().toString(36).slice(2, 14);
  return `sess-${random}`;
}

function ambientStore(): SessionStore | null {
  try {
    return globalThis.sessionStorage ?? null;
  } catch {
    return null; // Restricted contexts throw on the *access*, not on the call.
  }
}

/**
 * This tab's sitting, minted on first ask and stable for the rest of the tab.
 *
 * Returns `''` when there is no storage to remember one in — a private window
 * with site data blocked, a non-browser host. That is the honest answer and it
 * is the one the field already means everywhere else: *this caller did not name
 * a session*. Minting an id we could not persist would be worse than empty,
 * because every send would carry a different one and the filter would go from
 * matching everything to matching exactly one run.
 */
export function browserSessionId(
  store: SessionStore | null = ambientStore(),
  mint: () => string = mintSessionId,
): string {
  if (store == null) return '';
  try {
    const held = store.getItem(BROWSER_SESSION_KEY);
    if (held != null && held !== '') return held;
    const minted = mint();
    store.setItem(BROWSER_SESSION_KEY, minted);
    return minted;
  } catch {
    return '';
  }
}
