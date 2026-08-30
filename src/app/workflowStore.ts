import type { WorkflowModel } from '@core/model/WorkflowModel';
import type { WorkflowSerializer } from '@core/serialization/WorkflowSerializer';

/**
 * Browser-local workflow storage.
 *
 * A stopgap until the Python backend owns persistence (tickets 07/10/16). The
 * register entry (UX-04) called it "a stopgap that can lose a user's work";
 * this module is where the three concrete ways it could are closed.
 *
 * Everything takes an injectable `Storage`, which is the whole reason this file
 * exists separately from the React hooks: the previous version called
 * `localStorage` directly at module scope and was therefore untestable in a
 * node environment, and consequently untested.
 *
 * **The three failures, and what answers each.** They are different failures
 * with different fixes, and lumping them under "persistence is a stopgap" is
 * what let all three sit unaddressed:
 *
 * 1. **A write that fails silently.** `setItem` throws on the ~5MB quota, and
 *    in Safari's private mode it throws for *every* write. The old code
 *    returned an outcome — and the only caller threw it away, so the user kept
 *    editing an unsaved document. Fixed at both ends: a typed `kind` here, and
 *    a toast at the call site (`useWorkflowSession`).
 * 2. **A corrupt payload on the next load.** The old reader returned `null`,
 *    which is indistinguishable from "nothing saved" — so the user silently
 *    got the seeded demo instead of their graph, with no idea why and no way
 *    back. Now: an explicit `corrupt` status, and the bad bytes are
 *    *quarantined* rather than deleted, because they are the only copy of that
 *    user's work.
 * 3. **A second tab clobbering the first.** Two tabs adopted one id and the
 *    last write won, recorded in the old comment as an accepted trade. It is
 *    not one: the losing tab shows the user their work while overwriting it.
 *    Closed twice over — a **claim** stops two live tabs sharing an id at all,
 *    and a **compare-and-set** on every write catches the race the claim
 *    cannot (two tabs opening in the same instant, or a claim gone stale).
 *
 * **What this is still not.** Nothing here survives clearing site data or
 * moves work between browsers. That needs server-side persistence, designed in
 * `docs/decisions/gap-register.md` under UX-04. The UI says so out loud rather
 * than implying a durability we do not have.
 */

export const STORAGE_PREFIX = 'openstategraph-workflow-';

/**
 * Where unreadable bytes go. A *different* prefix on purpose: `listWorkflows`
 * filters on `STORAGE_PREFIX`, so a quarantined entry is preserved without
 * reappearing as a workflow the user can pick and fail to open again.
 */
export const CORRUPT_PREFIX = 'openstategraph-corrupt-workflow-';

/** Where a live tab records that it is editing a workflow. */
export const CLAIM_PREFIX = 'openstategraph-claim-';

/**
 * Refuse a payload larger than this rather than letting `setItem` decide.
 *
 * Browsers give `localStorage` about 5MB *for the whole origin*, shared with
 * the theme key, the session key and every claim. Writing right up to the
 * ceiling means the next unrelated write fails instead, which reports the
 * problem against the wrong feature. Stopping at 4MB leaves headroom and turns
 * an opaque `QuotaExceededError` into a sentence naming the actual cause.
 */
export const MAX_PAYLOAD_BYTES = 4_000_000;

/**
 * How long another tab's claim is believed.
 *
 * A claim is refreshed on a heartbeat, so a tab that crashed (or a laptop that
 * slept) stops claiming within this window. Long enough that a live tab is
 * never mistaken for a dead one; short enough that a crash does not lock a
 * user out of their own workflow for a coffee break.
 */
export const CLAIM_STALE_MS = 30_000;

/** The envelope version this module writes. v2 added `writerId`. */
const ENVELOPE_VERSION = 2;

/** Just the slice of `Storage` used here, so a test can supply a Map. */
export interface KeyValueStore {
  readonly length: number;
  key(index: number): string | null;
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

export interface SavedWorkflow {
  readonly id: string;
  readonly name: string;
  readonly savedAt: string;
}

/**
 * Why a write did not happen. A single boolean was not enough: the three
 * causes need three different sentences, and "conflict" in particular must
 * *not* be retried, while "quota" is worth telling the user to act on.
 */
export type SaveFailure = 'quota' | 'too-large' | 'conflict' | 'error';

export interface SaveOutcome {
  readonly ok: boolean;
  readonly kind?: SaveFailure;
  /** A complete sentence, safe to show a user verbatim. */
  readonly reason?: string;
}

export type LoadOutcome =
  | { readonly status: 'ok'; readonly json: string; readonly savedAt: string | null }
  | { readonly status: 'missing' }
  | { readonly status: 'corrupt'; readonly reason: string };

/**
 * One tab's write identity, and the newest version of its workflow it has seen.
 *
 * Deliberately a small mutable record passed in, not module state: the whole
 * point of this file is that a test can drive two tabs against one store, and
 * a hidden per-module singleton would make that impossible again.
 */
export interface WriteGuard {
  readonly writerId: string;
  /** `savedAt` of the newest payload this tab wrote *or* restored. */
  lastSeenAt: string | null;
}

export function newWriteGuard(writerId: string = mintWriterId()): WriteGuard {
  return { writerId, lastSeenAt: null };
}

function mintWriterId(): string {
  const random = Math.random().toString(36).slice(2, 10);
  return `w-${Date.now().toString(36)}-${random}`;
}

const keyFor = (id: string): string => `${STORAGE_PREFIX}${id}`;
const claimKeyFor = (id: string): string => `${CLAIM_PREFIX}${id}`;

/** `getItem` that answers "nothing" when storage itself is unavailable. */
function read(store: KeyValueStore, key: string): string | null {
  try {
    return store.getItem(key);
  } catch {
    return null;
  }
}

/**
 * Writes a workflow.
 *
 * Returns an outcome instead of swallowing failures into a `console.error`,
 * and — the part the outcome alone never bought — refuses to write at all when
 * writing would destroy someone else's newer save.
 */
export function saveWorkflow(
  store: KeyValueStore,
  id: string,
  model: WorkflowModel,
  serializer: WorkflowSerializer,
  guard: WriteGuard,
  now: () => string = () => new Date().toISOString(),
): SaveOutcome {
  const conflict = detectConflict(store, id, guard);
  if (conflict != null) return conflict;

  let payload: string;
  const savedAt = now();
  try {
    payload = JSON.stringify({
      version: ENVELOPE_VERSION,
      savedAt,
      writerId: guard.writerId,
      workflowId: id,
      name: model.name,
      workflow: JSON.parse(serializer.toJSONString(model)),
    });
  } catch (error) {
    return {
      ok: false,
      kind: 'error',
      reason: `This workflow could not be serialised: ${messageOf(error)}`,
    };
  }

  // Checked *before* the write, not after a failure: a browser that rejects an
  // oversized value gives us `QuotaExceededError`, which reads as "your disk is
  // full" when the truth is "this one document is too big for browser storage".
  if (payload.length > MAX_PAYLOAD_BYTES) {
    return {
      ok: false,
      kind: 'too-large',
      reason:
        `This workflow is too large for browser storage ` +
        `(${Math.round(payload.length / 1000)}kB of a ${Math.round(MAX_PAYLOAD_BYTES / 1000)}kB ` +
        `limit). Save it to the backend from the Workflows panel — nothing is being autosaved.`,
    };
  }

  try {
    store.setItem(keyFor(id), payload);
  } catch (error) {
    if (isQuotaError(error)) {
      return {
        ok: false,
        kind: 'quota',
        reason:
          'Browser storage is full, so this change was NOT autosaved. ' +
          'Save to the backend from the Workflows panel, or free space by ' +
          'deleting old browser data.',
      };
    }
    return {
      ok: false,
      kind: 'error',
      reason: `This change was NOT autosaved: ${messageOf(error)}`,
    };
  }

  guard.lastSeenAt = savedAt;
  return { ok: true };
}

/**
 * Compare-and-set: has someone written a version this tab never saw?
 *
 * The rule is deliberately "newer than what *we* last saw", not "written by
 * someone else". The naive writer-identity check locks a workflow forever the
 * first time its author closes the tab, because no new tab's id ever matches
 * the stored one — the legitimate handover and the destructive race look
 * identical unless the version we restored is part of the comparison.
 */
function detectConflict(store: KeyValueStore, id: string, guard: WriteGuard): SaveOutcome | null {
  const raw = read(store, keyFor(id));
  if (raw == null) return null;

  let existing: Record<string, unknown>;
  try {
    existing = JSON.parse(raw) as Record<string, unknown>;
  } catch {
    // Unreadable bytes are not somebody's newer work; overwriting them is a
    // recovery, not a clobber.
    return null;
  }

  const writerId = existing['writerId'];
  const savedAt = existing['savedAt'];
  if (typeof writerId !== 'string' || typeof savedAt !== 'string') return null;
  if (writerId === guard.writerId) return null;
  if (guard.lastSeenAt != null && savedAt <= guard.lastSeenAt) return null;

  return {
    ok: false,
    kind: 'conflict',
    reason:
      'Another browser tab saved this workflow more recently, so this tab ' +
      'stopped autosaving rather than overwriting it. Your changes here are ' +
      'unsaved — copy them out via Export, or reload to take the other ' +
      "tab's version.",
  };
}

/**
 * Reads a workflow back as the JSON string `importJSON` expects.
 *
 * Three outcomes, not two. "Missing" and "corrupt" were one `null` before, and
 * the difference is the whole user-facing story: one is a first visit, the
 * other is lost work that deserves an explanation.
 */
export function readWorkflow(store: KeyValueStore, id: string): LoadOutcome {
  const raw = read(store, keyFor(id));
  if (raw == null) return { status: 'missing' };

  try {
    const payload = JSON.parse(raw) as Record<string, unknown>;
    if (payload['workflow'] != null) {
      const savedAt = payload['savedAt'];
      return {
        status: 'ok',
        json: JSON.stringify(payload['workflow']),
        savedAt: typeof savedAt === 'string' ? savedAt : null,
      };
    }
    // An entry written before the envelope existed is the document itself.
    if (payload['nodes'] != null || payload['edges'] != null) {
      return { status: 'ok', json: raw, savedAt: null };
    }
    return quarantine(store, id, raw, 'it contained no workflow document');
  } catch (error) {
    return quarantine(store, id, raw, `it is not readable JSON (${messageOf(error)})`);
  }
}

/**
 * Move unreadable bytes aside so the editor starts clean next time.
 *
 * Kept rather than deleted: a truncated autosave is still the only copy of
 * that graph, and a support answer of "we threw it away" is worse than a key
 * nobody looks at. Best-effort throughout — a quarantine that itself fails
 * must not be the reason the editor cannot start.
 */
function quarantine(
  store: KeyValueStore,
  id: string,
  raw: string,
  why: string,
): { status: 'corrupt'; reason: string } {
  try {
    store.setItem(`${CORRUPT_PREFIX}${id}-${Date.now()}`, raw);
  } catch {
    // No room to keep a copy. Removing it below is still the right move: the
    // alternative is an editor that fails the same way on every single load.
  }
  try {
    store.removeItem(keyFor(id));
  } catch {
    // Nothing further to do; the reader already reports `corrupt`.
  }
  return {
    status: 'corrupt',
    reason:
      `The autosaved copy of this workflow could not be read — ${why}. ` +
      'The editor has started from a blank workflow; the unreadable data was ' +
      'kept in browser storage rather than deleted.',
  };
}

/**
 * Every saved workflow, newest first.
 *
 * A single unreadable entry is skipped rather than failing the listing — one
 * bad key should not make the whole manager panel empty.
 */
export function listWorkflows(store: KeyValueStore): SavedWorkflow[] {
  const found: SavedWorkflow[] = [];
  let length: number;
  try {
    length = store.length;
  } catch {
    return [];
  }
  for (let i = 0; i < length; i += 1) {
    let key: string | null;
    try {
      key = store.key(i);
    } catch {
      continue;
    }
    if (key == null || !key.startsWith(STORAGE_PREFIX)) continue;
    const raw = read(store, key);
    if (raw == null) continue;
    try {
      const payload = JSON.parse(raw) as { name?: unknown; savedAt?: unknown };
      found.push({
        id: key.slice(STORAGE_PREFIX.length),
        name: typeof payload.name === 'string' ? payload.name : 'Untitled workflow',
        savedAt: typeof payload.savedAt === 'string' ? payload.savedAt : '',
      });
    } catch {
      continue;
    }
  }
  return found.sort((a, b) => b.savedAt.localeCompare(a.savedAt));
}

export function deleteWorkflow(store: KeyValueStore, id: string): void {
  try {
    store.removeItem(keyFor(id));
  } catch {
    // Storage unavailable; there is nothing stored to delete either.
  }
}

/**
 * Re-key a stored workflow, keeping its bytes exactly as they are.
 *
 * A move, not a copy-and-rewrite, and that distinction is the whole reason it
 * lives here rather than being spelled `read` + `save` at the call site.
 * Re-saving would stamp a new `savedAt` and this tab's `writerId` onto the
 * payload; the compare-and-set above reads both, so a rewritten entry looks to
 * the *next* page load like a write nobody has seen. Carrying the envelope
 * across untouched keeps the write guard's lineage intact through the rename.
 *
 * **Refuses when the destination is occupied.** The one thing a re-key must
 * never do is land on top of another document's draft — that is ticket 23's
 * data loss with the arrow reversed, and it would be just as silent. The
 * caller decides whether being refused matters; `false` says nothing moved.
 */
export function moveWorkflow(store: KeyValueStore, fromId: string, toId: string): boolean {
  if (fromId === toId) return false;
  const raw = read(store, keyFor(fromId));
  if (raw == null) return false;
  if (read(store, keyFor(toId)) != null) return false;
  try {
    store.setItem(keyFor(toId), raw);
  } catch {
    // No room for the copy. Leaving the original in place is the safe half of
    // a failed move: the draft is still readable under its old key.
    return false;
  }
  try {
    store.removeItem(keyFor(fromId));
  } catch {
    // The copy landed, which is what the caller asked for. A source that
    // cannot be removed is a stale row, not lost work.
  }
  return true;
}

/**
 * Re-key a stored workflow **and disown it** — `launch-readiness` 153.
 *
 * `moveWorkflow` carries the envelope across untouched, which is exactly right
 * for a rename this tab performs on its own draft: the `writerId` still names
 * the writer, and the compare-and-set goes on protecting it.
 *
 * A hand-over is the other case. The draft being carried may have been written
 * by an *earlier page load* of this same tab — a tab that opened a workflow and
 * had not typed since holds a draft whose `writerId` no live guard matches —
 * and the destination is a key freshly minted for the tab doing the carrying.
 * Left as it is, that tab's very next keystroke reads as a clobber of a newer
 * write and autosave stops, announcing another tab that does not exist.
 *
 * So the `writerId` is dropped and everything else, `savedAt` included, is kept
 * byte for byte. `detectConflict` reads an envelope with no writer as *nobody
 * owns these bytes*, which is the truth: the destination is a `wf-<timestamp>`
 * only this tab can name, so there is no second writer to protect against.
 *
 * **Refuses an occupied destination**, exactly as `moveWorkflow` does, and for
 * the same reason: landing on another document's draft is ticket 23's data loss
 * with the arrow reversed.
 */
export function handOverWorkflow(store: KeyValueStore, fromId: string, toId: string): boolean {
  if (fromId === toId) return false;
  const raw = read(store, keyFor(fromId));
  if (raw == null) return false;
  if (read(store, keyFor(toId)) != null) return false;

  let payload: string = raw;
  try {
    const envelope = JSON.parse(raw) as Record<string, unknown>;
    delete envelope['writerId'];
    envelope['workflowId'] = toId;
    payload = JSON.stringify(envelope);
  } catch {
    // Unreadable bytes are carried as they are. The reader quarantines them
    // wherever they live, and refusing to move them would strand the only copy
    // under a key nobody asks for again.
  }

  try {
    store.setItem(keyFor(toId), payload);
  } catch {
    // See `moveWorkflow`: leaving the original in place is the safe half of a
    // failed move.
    return false;
  }
  try {
    store.removeItem(keyFor(fromId));
  } catch {
    // The copy landed. A source that cannot be removed is a stale row.
  }
  return true;
}

export function mostRecentWorkflowId(store: KeyValueStore): string | null {
  return listWorkflows(store)[0]?.id ?? null;
}

/* ================================================================== *
 * Claims — how two live tabs stop sharing one workflow id
 * ================================================================== */

/**
 * Record that this tab is editing `id`, now.
 *
 * Called on adoption and then on a heartbeat, so the record answers "is a tab
 * *currently* editing this" rather than "did one ever". Best-effort: a claim
 * that cannot be written costs us the pre-emptive check, and the
 * compare-and-set in `saveWorkflow` still stops the clobber.
 */
export function claimSession(
  store: KeyValueStore,
  id: string,
  guard: WriteGuard,
  nowMs: () => number = () => Date.now(),
): void {
  try {
    store.setItem(claimKeyFor(id), JSON.stringify({ writerId: guard.writerId, at: nowMs() }));
  } catch {
    // See above.
  }
}

/** Drop this tab's claim, so the next tab adopts immediately. */
export function releaseSession(store: KeyValueStore, id: string, guard: WriteGuard): void {
  const raw = read(store, claimKeyFor(id));
  if (raw == null) return;
  try {
    const claim = JSON.parse(raw) as { writerId?: unknown };
    if (claim.writerId !== guard.writerId) return;
    store.removeItem(claimKeyFor(id));
  } catch {
    // A claim we cannot parse is not ours to remove.
  }
}

/**
 * The writer id of the tab currently editing `id`, or `null` when none is.
 *
 * Split out of `isClaimedByAnother` for `launch-readiness` 148: a second
 * reader needs the same question asked without a `WriteGuard` to compare
 * against. `discardDraftAfterDelete` is deciding whether a draft belongs to
 * *some other tab* while holding no guard of its own, and the storage sweep
 * asks it of every key at once. One parser, three callers.
 */
export function claimHolder(
  store: KeyValueStore,
  id: string,
  nowMs: () => number = () => Date.now(),
  staleAfterMs: number = CLAIM_STALE_MS,
): string | null {
  const raw = read(store, claimKeyFor(id));
  if (raw == null) return null;
  try {
    const claim = JSON.parse(raw) as { writerId?: unknown; at?: unknown };
    if (typeof claim.writerId !== 'string' || typeof claim.at !== 'number') return null;
    return nowMs() - claim.at < staleAfterMs ? claim.writerId : null;
  } catch {
    return null;
  }
}

/** True when a *different*, still-live tab holds `id`. */
export function isClaimedByAnother(
  store: KeyValueStore,
  id: string,
  guard: WriteGuard,
  nowMs: () => number = () => Date.now(),
  staleAfterMs: number = CLAIM_STALE_MS,
): boolean {
  const holder = claimHolder(store, id, nowMs, staleAfterMs);
  return holder != null && holder !== guard.writerId;
}

/**
 * Decides which workflow this tab is editing, and whether to restore it.
 *
 * Two answers, and only the first of them restores anything:
 *
 * - **This tab already had a document.** `sessionStorage` survives ⌘R and
 *   nothing else, so a session id is a statement about *this* tab and no
 *   other. It gets its document back.
 * - **This tab has never had one.** It starts blank, whatever else the origin
 *   is holding — and is told, once, that the holding is still there.
 *
 * ## What the second answer used to be, and why it changed
 *
 * It used to adopt `mostRecentId` — the newest draft in this origin's
 * `localStorage` — and restore it. That is `install-experience` 23: a bare URL
 * with no `?w=` of any kind came up holding a previous session's 13-node
 * workflow, because "no parameter" reaches here as *restore* and restore was
 * spelled "put the newest draft on screen, whoever left it". Every genuinely
 * new tab took that branch, and so did the first visit after a browser
 * restart. The first screen of the product was somebody else's document.
 *
 * The adoption was not careless. It was written against a compounding defect:
 * the save hook minted a fresh `wf-<timestamp>` whenever the session had none
 * **and** performed an unconditional initial save on mount, while a separate
 * hook imported the most recent workflow over the top — so every tab open left
 * another full copy of one graph in storage, forever. Adopting stopped that.
 *
 * What is no longer true is the middle of that chain. There is no
 * unconditional initial save and no import-over-the-top; autosave writes on
 * change. A fresh tab that mints and restores nothing writes nothing at all
 * until the user edits, and what it then writes is their new blank document —
 * not a second copy of anybody's graph. The duplication this branch existed to
 * prevent cannot happen by minting any more, which is why minting is now the
 * right answer to a question it was once the wrong answer to.
 *
 * ## Nothing is lost, and that is a claim with somewhere to check it
 *
 * The draft is not deleted, swept, or rewritten — it stops being *adopted*.
 * `recentDrafts` is how it is reached deliberately, surfaced as *Unsaved in
 * this browser* in the Workflows panel, and `notice` is what points a user at
 * it on the one page load where they would otherwise have expected their
 * document to be sitting there.
 *
 * `shouldRestore` is false for a freshly minted id: there is nothing to
 * restore, and importing over the default document would clear the undo stack
 * for nothing.
 *
 * **`isClaimed` is gone with the adoption it gated.** It existed so that a
 * workflow another live tab was editing was not adopted into a second tab; no
 * tab adopts anything now, so the parameter could only ever have been a
 * condition on a branch that no longer exists. Multi-tab ownership itself is
 * untouched — `claimSession` still records the holder, the heartbeat still
 * refreshes it, `isClaimedByAnother` still answers, and the compare-and-set in
 * `saveWorkflow` is still what actually stops a clobber.
 */
export function resolveSession(input: {
  sessionId: string | null;
  /**
   * The newest draft this browser holds, or `null`. Read to decide whether
   * there is anything to *mention* — never to decide what to open.
   */
  mostRecentId: string | null;
  mintId: () => string;
}): { id: string; shouldRestore: boolean; notice?: string } {
  if (input.sessionId != null && input.sessionId !== '') {
    return { id: input.sessionId, shouldRestore: true };
  }
  const id = input.mintId();
  if (input.mostRecentId != null && input.mostRecentId !== '') {
    return {
      id,
      shouldRestore: false,
      notice:
        'Started a blank canvas. Unsaved work from an earlier session is still ' +
        'in this browser — open it from Workflows ▸ Unsaved in this browser.',
    };
  }
  return { id, shouldRestore: false };
}

function isQuotaError(error: unknown): boolean {
  if (typeof DOMException !== 'undefined' && error instanceof DOMException) {
    if (
      error.name === 'QuotaExceededError' ||
      error.name === 'NS_ERROR_DOM_QUOTA_REACHED' ||
      error.code === 22
    ) {
      return true;
    }
  }
  return error instanceof Error && /quota|storage is full/i.test(error.message);
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : 'unknown storage error';
}
