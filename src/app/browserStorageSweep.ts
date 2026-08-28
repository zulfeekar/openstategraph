import {
  CLAIM_PREFIX,
  CLAIM_STALE_MS,
  CORRUPT_PREFIX,
  STORAGE_PREFIX,
  type KeyValueStore,
} from './workflowStore';
import { slugOfDraftId } from './workflowDrafts';

/**
 * A bounded sweep of this origin's `localStorage` — **`launch-readiness` 96**.
 *
 * ## What was true, and why it stayed true
 *
 * Three families grew and nothing ever removed an entry: quarantined corrupt
 * snapshots (written on every unreadable draft, on a prefix `listWorkflows`
 * deliberately ignores, so nobody ever saw one), per-slug drafts for workflows
 * that no longer exist on the backend, and claim records left behind by tabs
 * that crashed. The only reader any of them had was a `QuotaExceededError`,
 * which reports the problem against whatever write happened to be next.
 *
 * The ticket did not ship a fix because it needed a judgement it was not
 * positioned to make: *how long is an orphaned draft worth keeping, given it
 * may be the only copy of someone's work.* That judgement is made here, and
 * the shape of it is the important part:
 *
 * > **Nothing is dropped for being old alone.** Age is only ever the *second*
 * > condition. The first is always a positive statement that the entry has
 * > stopped being anybody's work — its workflow is gone from the backend, or
 * > its bytes were already unreadable, or its claim is one the reader already
 * > ignores.
 *
 * So a draft of a workflow that still exists is never swept, however old: that
 * is unsaved work and its age says nothing about its value. A draft whose slug
 * the backend no longer holds is swept — but only after `ORPHAN_TTL_MS`, and
 * only if no live tab is still editing it.
 *
 * ## Why a live claim is consulted here as well as in `discardDraftAfterDelete`
 *
 * The same reason, and it is `launch-readiness` 148: `localStorage` belongs to
 * the origin and *every* tab shares it, so any code that removes a key is
 * acting on every tab at once. A claim record younger than `CLAIM_STALE_MS` is
 * the one signal this origin has that a draft is somebody's live work rather
 * than a leftover, and both removers must read it.
 *
 * ## Not a scheduler
 *
 * Run opportunistically, from the one place that holds an authoritative answer
 * to *"which slugs does the backend have"* — the Workflows panel's list
 * refresh. `knownSlugs: null` means the question could not be asked, and then
 * no slug-keyed draft is touched at all.
 */

export const DAY_MS = 24 * 60 * 60 * 1000;

/**
 * How long an entry that has stopped being anybody's work is still kept.
 *
 * Thirty days rather than a week because the loss it risks is asymmetric: a
 * swept draft is gone, while an unswept one costs a few kilobytes of a ~5MB
 * budget. Long enough that a delete-by-mistake, a holiday, or a package
 * restored from git all land inside it.
 */
export const ORPHAN_TTL_MS = 30 * DAY_MS;

/**
 * How many recent corrupt snapshots are kept at all.
 *
 * A cap as well as an age, because the failure that writes these is usually a
 * repeating one — a document that will not parse is re-quarantined on every
 * load, and a hundred copies of one broken graph is not a hundred pieces of
 * work. The newest are kept: they are the ones a support answer would want.
 */
export const CORRUPT_SNAPSHOT_CAP = 10;

/** One `localStorage` row, read into the shape the decision needs. */
export interface StoredEntry {
  readonly key: string;
  /** The `savedAt` inside a workflow envelope, when it has one. */
  readonly savedAt: string | null;
  /** The `at` inside a claim record, when it is one. */
  readonly claimedAtMs: number | null;
  /** Size of the stored value, for the usage line the panel shows. */
  readonly bytes: number;
}

export interface SweepOptions {
  readonly nowMs: number;
  /**
   * The slugs the backend currently holds, or `null` when this sweep could not
   * ask. `null` is not "none" — with no listing, no slug-keyed draft is
   * orphaned and none is touched.
   */
  readonly knownSlugs: ReadonlySet<string> | null;
}

export interface SweepReport {
  /** Keys this sweep decided to remove. */
  readonly drop: readonly string[];
  /** Bytes still held after the sweep, across every family. */
  readonly bytesHeld: number;
  /** Drafts still held. */
  readonly draftsHeld: number;
  /** Corrupt snapshots still held. */
  readonly corruptHeld: number;
}

/** The draft id a claim key names, or `null` when the key is not a claim. */
function claimedDraftId(key: string): string | null {
  return key.startsWith(CLAIM_PREFIX) ? key.slice(CLAIM_PREFIX.length) : null;
}

/** The draft id a workflow key names, or `null` when the key is not one. */
function draftIdOf(key: string): string | null {
  if (key.startsWith(CORRUPT_PREFIX)) return null;
  return key.startsWith(STORAGE_PREFIX) ? key.slice(STORAGE_PREFIX.length) : null;
}

/**
 * When a corrupt snapshot was quarantined, from its own key.
 *
 * `quarantine()` appends `-<Date.now()>`, so the age of these entries needs no
 * bookkeeping of its own — which is the only reason an age rule for them is
 * safe to apply to snapshots written before this module existed.
 */
function quarantinedAtMs(key: string): number | null {
  const match = /-(\d+)$/.exec(key);
  return match ? Number(match[1]) : null;
}

function olderThan(savedAt: string | null, ttlMs: number, nowMs: number): boolean {
  if (savedAt == null) return false; // cannot tell — and cannot-tell keeps the draft
  const at = Date.parse(savedAt);
  if (Number.isNaN(at)) return false;
  return nowMs - at > ttlMs;
}

/**
 * What this origin's storage should lose, and what it is left holding.
 *
 * Pure, and deliberately so — `say-it-on-the-surface` 07's shape. Every rule
 * below is a data decision that a test can drive at any clock, which matters
 * more here than anywhere: the cases that must **not** fire are the ones a
 * browser will not reproduce on demand.
 */
export function decideStorageSweep(
  entries: readonly StoredEntry[],
  options: SweepOptions,
): SweepReport {
  const liveDraftIds = new Set<string>();
  for (const entry of entries) {
    const id = claimedDraftId(entry.key);
    if (id == null || entry.claimedAtMs == null) continue;
    if (options.nowMs - entry.claimedAtMs < CLAIM_STALE_MS) liveDraftIds.add(id);
  }

  const drop = new Set<string>();

  for (const entry of entries) {
    // A claim past its window is one every reader already ignores, so removing
    // it loses nothing at all — the only family swept with no age judgement.
    const claimId = claimedDraftId(entry.key);
    if (claimId != null) {
      if (entry.claimedAtMs == null || !liveDraftIds.has(claimId)) drop.add(entry.key);
      continue;
    }

    const draftId = draftIdOf(entry.key);
    if (draftId == null) continue;
    if (liveDraftIds.has(draftId)) continue;
    if (!olderThan(entry.savedAt, ORPHAN_TTL_MS, options.nowMs)) continue;

    const slug = slugOfDraftId(draftId);
    if (slug == null) {
      // A `wf-<timestamp>` scratch draft: it never had a slug, so no backend
      // listing can make it an orphan or rescue it from being one. Age and a
      // live claim are the only facts available, and both have been checked.
      drop.add(entry.key);
      continue;
    }
    // A slug-keyed draft is only ever swept for being an orphan. With no
    // listing, nothing is known to be orphaned.
    if (options.knownSlugs != null && !options.knownSlugs.has(slug)) drop.add(entry.key);
  }

  const corrupt = entries
    .filter((entry) => entry.key.startsWith(CORRUPT_PREFIX))
    .map((entry) => ({ entry, atMs: quarantinedAtMs(entry.key) }))
    .sort((a, b) => (b.atMs ?? 0) - (a.atMs ?? 0));
  corrupt.forEach(({ entry, atMs }, index) => {
    const stale = atMs != null && options.nowMs - atMs > ORPHAN_TTL_MS;
    if (stale || index >= CORRUPT_SNAPSHOT_CAP) drop.add(entry.key);
  });

  let bytesHeld = 0;
  let draftsHeld = 0;
  let corruptHeld = 0;
  for (const entry of entries) {
    if (drop.has(entry.key)) continue;
    if (entry.key.startsWith(CORRUPT_PREFIX)) {
      corruptHeld += 1;
    } else if (draftIdOf(entry.key) != null) {
      draftsHeld += 1;
    } else if (claimedDraftId(entry.key) == null) {
      continue; // not one of ours; not counted and never dropped
    }
    bytesHeld += entry.bytes;
  }

  return { drop: [...drop], bytesHeld, draftsHeld, corruptHeld };
}

/**
 * Read this origin's rows into `StoredEntry`s.
 *
 * Best-effort at every step: a store that throws (Safari private mode, a
 * browser set to block site data) answers "there is nothing here", which is a
 * correct answer and not an error to report.
 */
export function readStorageEntries(store: KeyValueStore): StoredEntry[] {
  const entries: StoredEntry[] = [];
  let length: number;
  try {
    length = store.length;
  } catch {
    return entries;
  }
  for (let i = 0; i < length; i += 1) {
    let key: string | null;
    let raw: string | null;
    try {
      key = store.key(i);
      raw = key == null ? null : store.getItem(key);
    } catch {
      continue;
    }
    if (key == null || raw == null) continue;

    let savedAt: string | null = null;
    let claimedAtMs: number | null = null;
    try {
      const payload = JSON.parse(raw) as { savedAt?: unknown; at?: unknown };
      if (typeof payload.savedAt === 'string') savedAt = payload.savedAt;
      if (typeof payload.at === 'number') claimedAtMs = payload.at;
    } catch {
      // Unreadable bytes still have a key and a size, and both are what the
      // corrupt-snapshot rules read. Nothing else here needs the contents.
    }
    entries.push({ key, savedAt, claimedAtMs, bytes: key.length + raw.length });
  }
  return entries;
}

/** Decide, then remove. Returns what was decided, for the panel to report. */
export function sweepBrowserStorage(store: KeyValueStore, options: SweepOptions): SweepReport {
  const report = decideStorageSweep(readStorageEntries(store), options);
  for (const key of report.drop) {
    try {
      store.removeItem(key);
    } catch {
      // Nothing further to do; the entry is simply still there next time.
    }
  }
  return report;
}
