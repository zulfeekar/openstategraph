/**
 * What a tab does when somebody else writes the package it has open —
 * `osg-agent-experience/69`.
 *
 * ## The failure this exists for
 *
 * The owner, 2026-09-05, after `68`: *"a user opens three tabs on the same
 * workflow, how does each get the latest changes?"* Four kinds of writer — an
 * editor tab, a second editor tab, the CLI, a coding agent through the MCP
 * server — and a tab that was not the writer learned nothing until its user
 * reloaded. A reload is exactly the gesture `68` shows can lose work.
 *
 * The backend half is `GET /api/workflows/{slug}/events`, which watches the
 * file and so fires for every writer. This is the decision the frame produces,
 * and it is separate from the machinery for the reason
 * `decideFileWatchAction` is: a rule about somebody's unsaved work should be
 * runnable without a network, a timer or React.
 *
 * ## Why there are three answers and not two
 *
 * A tab with **no unsaved edits** has nothing to lose, so asking it a question
 * would be a modal dialog raised over a decision that has only one sensible
 * answer — the notification fatigue that makes the *real* question, the one
 * below, get dismissed unread. It refreshes silently.
 *
 * A tab with **unsaved edits** holds the only copy of them. Taking the file
 * would destroy them and keeping the draft would destroy the file, and the
 * editor is not the one who knows which is wanted — the call
 * `restoredDraftConflict` already makes for a reload, in the same words and
 * through the same dialog.
 *
 * And a frame carrying **the revision this tab already has** is this tab's own
 * write coming back to it. Refreshing on that would be a fetch per keystroke;
 * asking on it would be a dialog per keystroke.
 */

/**
 * How the document on screen stands to the file this tab last knew about.
 *
 * Three states rather than a `dirty` boolean, because the third one is not
 * "dirty": `unbaselined` is a tab that has been *disarmed* — a save was
 * refused, a package was deleted, a reload found a conflict — and
 * `writeOpenWorkflowToDisk` already reads a missing baseline as *never write
 * this package*. Folding it into `matches` would refresh over a document the
 * editor has been told it must not overwrite; folding it into `differs` is
 * what this module does, deliberately, because a question is the safe answer
 * when the tab's state is unknown.
 */
export type DiskDocumentStatus = 'matches' | 'differs' | 'unbaselined';

export type ExternalChangeAction =
  /** Nothing to do — this tab already holds that revision, or has no stake. */
  | { readonly kind: 'ignore' }
  /** No unsaved edits: load the new revision and say nothing. */
  | { readonly kind: 'refresh' }
  /** Unsaved edits: write nothing, and put the choice in front of the user. */
  | { readonly kind: 'ask' };

export interface ExternalChangeInput {
  /** The revision the frame announced — the digest of the file right now. */
  readonly incomingDigest: string;
  /** The revision this tab believes it is editing, if it knows one. */
  readonly knownDigest: string | undefined;
  readonly status: DiskDocumentStatus;
}

/**
 * The rule, on facts a caller has already gathered.
 *
 * **An empty incoming digest is a package that is not there**, and it is
 * ignored here rather than handled: the file watch's `notify-deleted` already
 * owns deletion, and it does more than notify — `abandonDeletedWorkflow`
 * disarms the writer and releases the slug (`launch-readiness/147`). A second
 * verdict about the same event, arriving from a different transport half a
 * second earlier, would be two mechanisms racing over one tab's identity.
 */
export function decideExternalChange(input: ExternalChangeInput): ExternalChangeAction {
  if (!input.incomingDigest) return { kind: 'ignore' };
  // Its own write coming back, or a revision it has already taken. Checked
  // first, so a tab that has just saved is never asked about itself — which
  // is the difference between this being usable and being a dialog per
  // keystroke, since disk autosave writes on every edit.
  if (input.knownDigest !== undefined && input.knownDigest === input.incomingDigest) {
    return { kind: 'ignore' };
  }
  return input.status === 'matches' ? { kind: 'refresh' } : { kind: 'ask' };
}

/* -------------------------------------------------------------------------
 * Where a revision is heard from, and why there are three sources
 * ---------------------------------------------------------------------- */

/**
 * A revision this tab has just learned the file holds, from any source.
 *
 * **This exists because of a connection budget, measured rather than
 * anticipated** (`osg-agent-experience/69`, staged on 2026-09-05 against the
 * running editor). A browser allows six concurrent HTTP/1.1 connections per
 * origin, and each editor tab held a long-lived one for `/api/events` and
 * another for `/api/kanban/patrol/events`. The package stream `69` added was a
 * third — so **two** tabs saturated the budget and the last stream opened
 * never left `CONNECTING`. Observed exactly that: with two tabs on one
 * workflow the second tab's `EventSource` sat at `readyState 0` for minutes,
 * and opened within a second of the other tab closing.
 *
 * Two tabs on one workflow is `69`'s own scenario, so a mechanism that fails
 * there is not a mechanism — and this seam is what let the editor have a
 * *third* source without a third socket. The five-second `savedAt` poll
 * `useWorkflowFileWatch` already runs receives the file's digest in the same
 * row it already reads, costs no connection at all, and works however many
 * tabs are open. It publishes here; the `BroadcastChannel` publishes here;
 * and since `osg-agent-experience/71` folded every live subject onto the one
 * connection a tab holds, `workflow.changed` publishes here too.
 * `decideExternalChange` deduplicates all three against the revision this tab
 * holds, so hearing one change three times is one action and two ignores.
 *
 * The ordering is worth stating because it is the whole design: the
 * `BroadcastChannel` is instant and covers other tabs of this browser, the
 * stream is sub-second and covers every writer, the poll is five seconds and
 * covers every writer with nothing of the backend but a row it was already
 * reading. Each is a strict fallback for the one above it, and losing the top
 * two costs latency rather than correctness.
 */
const revisionListeners = new Set<(slug: string, digest: string) => void>();

/** Say what the file is holding now — called by every transport. */
export function announceRevisionSeen(slug: string, digest: string | undefined): void {
  if (!slug || !digest) return;
  for (const listener of [...revisionListeners]) listener(slug, digest);
}

export function subscribeRevisionSeen(
  listener: (slug: string, digest: string) => void,
): () => void {
  revisionListeners.add(listener);
  return () => {
    revisionListeners.delete(listener);
  };
}
