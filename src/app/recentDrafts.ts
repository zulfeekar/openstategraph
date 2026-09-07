import { listWorkflows, type KeyValueStore } from './workflowStore';
import { slugOfDraftId } from './workflowDrafts';

/**
 * The unsaved work this browser is holding, offered back **on purpose**.
 *
 * ## Why this module exists at all
 *
 * `install-experience` 23. Until it, a page load with no `?w=` adopted the
 * newest draft in `localStorage` and put it on the canvas — so a bare URL
 * opened a previous session's 13-node workflow, and the first screen of the
 * product was somebody else's document. The adoption had to go.
 *
 * But the adoption was also the **only** way back to a `wf-<timestamp>`
 * scratch draft. A draft keyed `slug-<slug>` has an identity and is reachable
 * by opening its workflow, where `restoreDraftFor` prefers it over the file; a
 * scratch draft never had one, nothing listed it, and removing the implicit
 * adoption without this would have turned a wrong default into lost work.
 *
 * So the rule the ticket asks for is two-sided and both sides are here: a
 * draft is **never** restored because a tab happened to open, and it is
 * **always** reachable because a user asked for it by name.
 *
 * ## Why `slug` is on the row rather than resolved by the caller
 *
 * Because the two kinds of draft are reopened through different paths and the
 * difference is not cosmetic. A package's draft is reopened by *loading the
 * package* — the file arrives first, registering the workflow's capabilities,
 * and only then does the draft supersede it. Restoring those bytes straight
 * onto the canvas instead would skip the registration and silently drop every
 * workflow-scoped node in the document. A scratch draft has no file to load,
 * so for it the bytes are the whole story.
 */
export interface RecentDraft {
  /** The storage id the bytes live under. */
  readonly id: string;
  /** The document's own name, as it was last autosaved. */
  readonly name: string;
  /** ISO timestamp of the last autosave, or `''` when the entry carried none. */
  readonly savedAt: string;
  /** The package this draft belongs to, or `null` for a scratch draft. */
  readonly slug: string | null;
}

/**
 * Every draft this browser holds, newest first.
 *
 * A thin projection of `listWorkflows` rather than a second reader of the same
 * keys: one module already knows how a draft is stored, skips an unreadable
 * entry instead of failing the listing, and keeps quarantined bytes out. What
 * is added is the one fact a reopen needs and the storage layer has no opinion
 * about — which package, if any, the draft belongs to.
 */
export function listRecentDrafts(store: KeyValueStore): readonly RecentDraft[] {
  return listWorkflows(store).map((saved) => ({
    id: saved.id,
    name: saved.name,
    savedAt: saved.savedAt,
    slug: slugOfDraftId(saved.id),
  }));
}
