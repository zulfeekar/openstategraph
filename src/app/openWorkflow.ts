import { recordOpened } from './lastOpened';
import { CURRENT_SLUG_KEY } from './workflowFileWatch';

/**
 * Which saved workflow this tab has open — **and its URL** (ticket 20).
 *
 * Before this module the answer lived in `sessionStorage` alone, which made a
 * workflow unlinkable: a developer could not send a colleague to one, could
 * not bookmark one, and a reload landed wherever the autosave happened to be.
 * The address bar is where "which document am I looking at" belongs, so the
 * two are written together, here, once. Every writer of the open slug goes
 * through this module; readers that only need the slug (`AskPanel`,
 * `KnowledgeBody`, the drill trail) keep reading `sessionStorage` directly,
 * because the URL is a *projection* of that value, never a second source of it.
 *
 * ## What the URL carries: the slug, and nothing else
 *
 * A deep link names a document on the backend. It deliberately does **not**
 * carry:
 *
 * - **A chat thread.** Ticket 17 refused to persist an Ask thread across a
 *   reload, because the transcript is not persisted either and restoring the
 *   id alone drops a developer into a conversation whose earlier turns exist
 *   on the server and nowhere on screen — an answer with an invisible
 *   antecedent. A shared link would make that worse, not better: the
 *   recipient would inherit *someone else's* invisible antecedent.
 * - **The viewport or the selection.** A link should open the workflow, not
 *   the sender's scroll position; and syncing a pan into the URL would rewrite
 *   the address on every mouse move.
 * - **The document.** The file on disk is the source of truth. A URL carrying
 *   a graph would be a second one, immediately stale, and unbounded in length.
 *
 * ## Why `?w=` and not `/w/<slug>`
 *
 * A path segment needs a history fallback from whatever serves the editor —
 * the Vite dev server, a static host, a reverse proxy — and a deep link that
 * 404s when opened cold is not a deep link. A query parameter needs nothing
 * from any of them, and is exactly as shareable.
 *
 * ## Why `replaceState` and never `pushState`
 *
 * The editor holds one mutable document, not a stack of pages. A Back button
 * that swapped the open workflow out from under unsaved edits would be a
 * data-loss affordance dressed as navigation, so opening a workflow leaves no
 * history entry — Back returns to wherever the developer came from, which is
 * the behaviour a link recipient expects.
 */
export const WORKFLOW_URL_PARAM = 'w';

/**
 * The slug a URL asks for, or `null`. Pure — `location.search` is passed in,
 * so this is testable without a DOM.
 *
 * Anything empty or whitespace-only is `null` rather than an empty slug: a
 * bare `?w=` is a broken link, and treating it as a workflow named "" would
 * ask the backend about the workflows root itself.
 */
export function readSlugFromSearch(search: string): string | null {
  const value = new URLSearchParams(search).get(WORKFLOW_URL_PARAM);
  const slug = value?.trim() ?? '';
  return slug === '' ? null : slug;
}

/**
 * `href` with the workflow parameter set to `slug`, or removed when `null`.
 *
 * Every other parameter is preserved: the address bar is shared with whatever
 * else a deployment puts there, and silently dropping someone's query string
 * because we rewrote the URL is the kind of thing nobody notices until it
 * breaks something else.
 */
export function urlWithSlug(href: string, slug: string | null): string {
  const url = new URL(href, 'http://editor.invalid');
  if (slug === null) url.searchParams.delete(WORKFLOW_URL_PARAM);
  else url.searchParams.set(WORKFLOW_URL_PARAM, slug);
  return `${url.pathname}${url.search}${url.hash}`;
}

/**
 * Listeners for "this tab now has a different workflow open".
 *
 * Added for ticket 23. The open slug had exactly one consumer shape — read it
 * when you need it — which is fine for a value that only ever moves at
 * startup. It moves mid-session too (the Workflows panel's Load, a drill-in,
 * the first Save of a new document), and the autosave key has to move with it:
 * a tab that opened workflow B while still writing its draft under workflow
 * A's key is the data loss this ticket is about, wearing a different hat.
 *
 * A `Set` of plain callbacks rather than a storage event: `sessionStorage`
 * fires no event in the tab that wrote it, which is the only tab that cares.
 */
const slugListeners = new Set<(slug: string | null) => void>();

/** Subscribe to open-slug changes. Returns the unsubscribe. */
export function subscribeOpenSlug(listener: (slug: string | null) => void): () => void {
  slugListeners.add(listener);
  return () => slugListeners.delete(listener);
}

/** The open workflow's slug, or `null` when this tab is on an unsaved one. */
export function getOpenSlug(): string | null {
  try {
    return sessionStorage.getItem(CURRENT_SLUG_KEY);
  } catch {
    return null; // sessionStorage throws in restricted contexts
  }
}

/**
 * Record `slug` as this tab's open workflow, in storage and in the address bar.
 *
 * Called after a load or a save succeeds — never before. A URL naming a
 * workflow the editor failed to open would be a link that lies, and worse, one
 * a reload would keep trying to honour.
 *
 * **And the one place "this browser has opened it" is written**
 * (`install-experience` 28). Every path that makes a slug this tab's document
 * ends here — the Workflows panel's load, a save that mints a slug, a deep
 * link — so the arrival list's second clock is stamped once rather than at
 * three call sites where a fourth would forget. It is deliberately after the
 * success this function already represents: an open that failed is not an
 * open, and ordering the list by attempts would put the workflow that is
 * broken at the top of it.
 */
export function setOpenSlug(slug: string): void {
  recordOpened(slug);
  try {
    sessionStorage.setItem(CURRENT_SLUG_KEY, slug);
  } catch {
    // Storage unavailable — the URL below still names the workflow, which is
    // the more durable half of the two anyway.
  }
  syncUrl(slug);
  announce(slug);
}

/** Forget the open workflow: a new, never-saved document has no URL. */
export function clearOpenSlug(): void {
  try {
    sessionStorage.removeItem(CURRENT_SLUG_KEY);
  } catch {
    // Nothing to forget if we could not read it in the first place.
  }
  syncUrl(null);
  announce(null);
}

/**
 * Notified after storage and the URL, never before: a listener that re-keys
 * autosave must not act on a slug this module has not finished adopting. One
 * listener throwing must not stop the others being told.
 */
/**
 * Tell the subscribers what this tab's draft is now keyed on — ticket 42.
 *
 * The subject is the **address**, not the slug, and the two coincide for a
 * package: `formatMountAddress` of a class address is the bare slug, so every
 * existing autosave key is byte-identical and nothing needs migrating. An
 * instance gets its own key (`concierge/wf-music`), which is what keeps a
 * merged instance document from being autosaved over the package's own draft
 * and restored, silently, the next time anyone opens the class.
 *
 * Exported so `openAddress` can announce through the same channel rather than
 * standing up a second one — one listener set, one ordering guarantee.
 */
export function announceOpenSubject(subject: string | null): void {
  announce(subject);
}

function announce(slug: string | null): void {
  for (const listener of [...slugListeners]) {
    try {
      listener(slug);
    } catch {
      // A subscriber's failure is its own; the slug has still moved.
    }
  }
}

function syncUrl(slug: string | null): void {
  if (typeof window === 'undefined' || !window.history?.replaceState) return;
  const next = urlWithSlug(window.location.href, slug);
  if (next === `${window.location.pathname}${window.location.search}${window.location.hash}`) {
    return; // Nothing moved; do not churn the history entry.
  }
  window.history.replaceState(window.history.state, '', next);
}

/**
 * What a page load should do about the URL, decided before anything is fetched.
 *
 * The interesting case is a reload of a tab that already has the workflow
 * open, and it is the one a naive "URL wins, always" rule gets wrong. This
 * tab's autosave holds the developer's *unsaved edits to that same workflow*;
 * refetching the file over them would quietly discard work every time someone
 * pressed reload — trading ticket 20's data loss for a new one. So:
 *
 * - **URL names the workflow this tab already has open** → `restore`. Same
 *   document, newer copy; the file watch already warns if the disk moved.
 * - **URL names a different workflow, or this tab has none** → `fetch`. A
 *   shared link, a bookmark, a second tab. Browser storage must not be
 *   restored over it, and the autosave session must be a *fresh* one so
 *   loading the link cannot overwrite another tab's autosaved graph.
 * - **No `w=` at all** → `restore`, the editor's existing behaviour, and the
 *   caller writes the open slug back into the URL so it is copyable.
 *
 * ## …unless there is no draft to restore (ticket 49)
 *
 * The first rule above assumes its own premise: it declines to refetch because
 * "this tab's autosave holds unsaved edits to that very workflow". When it does
 * not, the reasoning has nothing left in it — and the branch still fired,
 * because nobody had ever asked whether the draft was there. A missing draft
 * therefore restored *nothing at all*, leaving the blank default document on
 * screen for a slug the backend could serve in full. That is ticket 49's
 * blocker, and it is not an edge case: it is the state of every tab
 * immediately after its first Save.
 *
 * So `hasDraft` is part of the decision rather than a detail of carrying it
 * out. **A missing draft is never an empty canvas** — the fallback is the
 * document the URL names, always. Omitting the field keeps the old behaviour
 * for the one caller that genuinely has no storage question to ask.
 *
 * ## …and the branch ticket 49 did not cover (`production-ready` 71)
 *
 * That rule was written into the *first* case and gated on `urlSlug !== null`,
 * so the third one — **no `w=` at all** — kept restoring a draft that was not
 * there. The canvas stayed blank while `sessionStorage` went on naming a real
 * package, and that pairing is what let an empty document be written over a
 * 13-node workflow with no Save pressed.
 *
 * The fallback is the same one, and the sentence above did not need changing:
 * a missing draft is never an empty canvas. Here the document to fall back to
 * is the one the *open slug* names rather than the one the URL names, because
 * that is the only claim in play — and it is the same document the caller was
 * about to write back into the URL anyway.
 */
export function resolveOpenRequest(input: {
  urlSlug: string | null;
  openSlug: string | null;
  /** Whether this browser holds a draft of the workflow already open here. */
  hasDraft?: boolean;
}): { readonly action: 'fetch'; readonly slug: string } | { readonly action: 'restore' } {
  if (input.urlSlug !== null && input.urlSlug !== input.openSlug) {
    return { action: 'fetch', slug: input.urlSlug };
  }
  if (input.urlSlug !== null && input.hasDraft === false) {
    return { action: 'fetch', slug: input.urlSlug };
  }
  if (input.urlSlug === null && input.openSlug !== null && input.hasDraft === false) {
    return { action: 'fetch', slug: input.openSlug };
  }
  return { action: 'restore' };
}
