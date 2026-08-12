import type { Workbench } from './Workbench';
import { readWorkflow, type KeyValueStore } from './workflowStore';
import { registerNodeTypesForRawDocument } from '@nodes/workflowScoped';

/**
 * A browser-local draft **per workflow**, instead of one per tab.
 *
 * ## The defect
 *
 * Autosave keyed its entry on a synthetic `wf-<timestamp>` id belonging to the
 * *tab*, not to the document. So opening a second workflow — a normal thing to
 * do mid-edit, and something the Workflows panel actively invites — pointed
 * that one key at a different document and the previous draft became
 * unreachable. No prompt, no warning, no undo entry, no diagnostic: the only
 * feedback was a neutral *"Opened: Chinook Assistant"* toast.
 *
 * The Workflows panel's promise made it worse by being precise:
 *
 * > Edits autosave to **this browser only** — they are not on the backend and
 * > will not follow you to another browser, another machine, or survive
 * > clearing site data.
 *
 * Every way of losing work named there is a different browser, a different
 * machine, or clearing site data. Opening a second workflow in the same tab is
 * none of those, and it lost work anyway. A plain reload preserved the draft,
 * which is what made the behaviour so hard to predict.
 *
 * ## The fix, and why it is keying rather than prompting
 *
 * The ticket allowed either. A prompt only covers the paths the editor can
 * intercept — it cannot appear for the address-bar navigation that found this,
 * because the page is already gone. Keying the draft on the slug covers every
 * path at once and asks the user nothing: your unsaved edits to *this*
 * workflow are still there when you come back to *this* workflow.
 *
 * Two collaborating parts, and both are needed:
 *
 * 1. **`draftIdForSlug`** — the autosave key follows the open slug
 *    (`useWorkflowSession` re-keys through `subscribeOpenSlug`), so editing
 *    workflow B can never overwrite workflow A's draft.
 * 2. **`restoreDraftFor`** — opening a workflow prefers this browser's newer
 *    draft over the file, and says so.
 */

/**
 * The storage id a slug's draft lives under.
 *
 * Prefixed rather than bare so it can never collide with a `wf-<timestamp>` id
 * minted before this existed, and so `listWorkflows` still shows both.
 */
export function draftIdForSlug(slug: string): string {
  return `slug-${slug}`;
}

/**
 * When this browser's draft of `slug` was written, or `null` if there is none.
 *
 * This is the **write guard's baseline**, and forgetting it is not cosmetic.
 * `saveWorkflow` refuses to write when the stored payload is newer than the
 * version this tab last saw — a compare-and-set that stops one tab clobbering
 * another's work. With a per-tab key that question never arose, because the
 * key was fresh every time. With a per-slug key it arises on every navigation:
 * the draft in storage was written by the *previous page load*, which had a
 * different `writerId` and a later `savedAt`, so an unbaselined tab declares a
 * conflict against itself and stops autosaving — announcing that another tab
 * saved more recently when no other tab exists.
 *
 * A tab that is about to load a draft has, by any honest reading, *seen* it.
 * Call this whenever the autosave key adopts a slug.
 */
export function draftSavedAt(slug: string, store: KeyValueStore = browserStore()): string | null {
  const draft = readWorkflow(store, draftIdForSlug(slug));
  return draft.status === 'ok' ? draft.savedAt : null;
}

export interface DraftRestoreOutcome {
  /** True when the draft differed from the file and was loaded instead. */
  readonly restored: boolean;
}

/**
 * Loads this browser's draft of `slug` over the document currently in the
 * model, when there is one and it differs.
 *
 * **Call it immediately after importing the file, never instead of.** The file
 * import is what registers the workflow's capabilities and establishes the
 * canonical text to compare against; this only decides whether the user's own
 * unsaved version supersedes it.
 *
 * **Comparison is by canonical bytes, not by timestamp.** Both documents are
 * put through the same serializer, so the question asked is "does this draft
 * actually differ from what is on disk" rather than "which clock is ahead" —
 * and a draft written by a browser whose clock is wrong cannot silently win or
 * silently lose. A draft equal to the file is not a restore at all; it is the
 * ordinary case after a save, and it must stay silent.
 */
export function restoreDraftFor(
  slug: string,
  workbench: Workbench,
  store: KeyValueStore = browserStore(),
): DraftRestoreOutcome {
  const draft = readWorkflow(store, draftIdForSlug(slug));
  // `corrupt` is reported by the reader, which quarantines the bytes; the file
  // the editor just loaded stays, which is the right recovery.
  if (draft.status !== 'ok') return { restored: false };

  const fromFile = workbench.controller.document.exportJSON();

  let parsed: unknown;
  try {
    parsed = JSON.parse(draft.json);
  } catch {
    return { restored: false };
  }

  // Same ordering requirement as every other import path: a workflow-scoped
  // type has to be registered before its nodes can be created as themselves.
  registerNodeTypesForRawDocument(parsed, workbench.registry, workbench.engine.executors);
  const outcome = workbench.controller.document.importJSON(draft.json);
  if (!outcome.ok) {
    // An unreadable draft must not cost the user the file they asked for.
    workbench.controller.document.importJSON(fromFile);
    return { restored: false };
  }

  if (workbench.controller.document.exportJSON() === fromFile) return { restored: false };
  return { restored: true };
}

/**
 * `localStorage`, or a store that holds nothing when there is none.
 *
 * The default rather than a required argument because every real caller wants
 * browser storage, and the one context that has none — a test or any non-DOM
 * host — wants "this browser has no drafts", which is exactly true and is not
 * an error to report. A null object says that in one place instead of a
 * `typeof localStorage` check at each call site.
 */
function browserStore(): KeyValueStore {
  if (typeof localStorage !== 'undefined') return localStorage;
  return {
    length: 0,
    key: () => null,
    getItem: () => null,
    setItem: () => {},
    removeItem: () => {},
  };
}
