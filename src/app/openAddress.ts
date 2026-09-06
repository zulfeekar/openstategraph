import {
  formatMountAddress,
  isInstance,
  parseMountAddress,
  addressEquals,
  type MountAddress,
} from '@core/model/MountAddress';
import { CURRENT_SLUG_KEY } from './workflowFileWatch';
import { WORKFLOW_URL_PARAM, announceOpenSubject, subscribeOpenSlug } from './openWorkflow';

/**
 * Which *instance* this tab has open, in storage and in the address bar.
 *
 * Ticket 42, and the address half of `openWorkflow` rather than a replacement
 * for it: `?w=concierge` still names a document and behaves exactly as before,
 * while `?w=concierge/wf-music` names one mount of `chinook-assistant` — the
 * instance whose `data.overrides` are its own. Old links keep working because
 * a bare slug is simply an address with an empty mount path.
 *
 * ## The storage split, and why it is not one key
 *
 * `CURRENT_SLUG_KEY` is read **raw**, by six unrelated call sites — the Ask
 * panel, the SQL schema body, the knowledge body, the palette, the mount card
 * and the file watch — and every one of them substitutes it into
 * `/api/workflows/{slug}/…`. That is deliberate and documented in
 * `openWorkflow`: readers that only need the slug do not go through a module.
 *
 * Those questions are all questions about the **package**: what tools it
 * ships, what its knowledge holds, what its SQL source is. None of them
 * changes per mount. So `CURRENT_SLUG_KEY` keeps meaning *the class slug of
 * whatever is on screen* — `chinook-assistant`, even while the instance
 * `concierge/wf-music` is displayed — and all six keep asking the right
 * question with no change at all. Writing an address into that key would have
 * made every one of them request `/api/workflows/concierge/wf-music/…`, which
 * the backend rejects outright.
 *
 * The address lives in its own key, read only by code that knows what an
 * instance is.
 */
export const OPEN_ADDRESS_KEY = 'openstategraph.open-address';

/**
 * The address a URL asks for, or `null` — for no parameter, a blank one, or
 * text that cannot be an address.
 *
 * Unparseable is `null` rather than a best effort, for the reason
 * `MountAddress` refuses rather than repairs: a repaired address is a link
 * that quietly opens a different instance than the one it names.
 */
export function readAddressFromSearch(search: string): MountAddress | null {
  const raw = new URLSearchParams(search).get(WORKFLOW_URL_PARAM)?.trim() ?? '';
  return raw === '' ? null : parseMountAddress(raw);
}

/** `href` with the workflow parameter set to `address`, or removed for `null`. */
export function urlWithAddress(href: string, address: MountAddress | null): string {
  const url = new URL(href, 'http://editor.invalid');
  if (address === null) url.searchParams.delete(WORKFLOW_URL_PARAM);
  else url.searchParams.set(WORKFLOW_URL_PARAM, formatMountAddress(address));
  return `${url.pathname}${url.search}${url.hash}`;
}

/** The instance this tab has open, or `null`. */
export function getOpenAddress(): MountAddress | null {
  try {
    const raw = sessionStorage.getItem(OPEN_ADDRESS_KEY);
    return raw ? parseMountAddress(raw) : null;
  } catch {
    return null; // sessionStorage throws in restricted contexts
  }
}

/**
 * Record the open instance: the address in its own key, and the **class slug**
 * in the key every existing reader already uses.
 *
 * `classSlug` is passed rather than derived because only the backend knows it
 * — the address names a chain of mount ids, and which package sits at the end
 * of that chain is exactly what the mounts endpoint answers.
 */
export function setOpenAddress(address: MountAddress, classSlug: string): void {
  try {
    sessionStorage.setItem(CURRENT_SLUG_KEY, classSlug);
    sessionStorage.setItem(OPEN_ADDRESS_KEY, formatMountAddress(address));
  } catch {
    // Storage unavailable — the URL below still names the instance, which is
    // the more durable half of the two anyway.
  }
  syncUrl(address);
  // The autosave key follows the **address**, not the class slug. For a
  // package the two are the same string, so no existing draft moves; for an
  // instance it is what stops a merged document being written under
  // `slug-chinook-assistant` and restored, silently, the next time anyone
  // opens the class. That contamination is ticket 23's shape, and it would
  // have been found months later as a corrupted package.
  announceOpenSubject(formatMountAddress(address));
}

/**
 * The name a startup hook compares a URL's `?w=` against.
 *
 * Two hooks decide, on every page load, which of them owns the document:
 * `WorkbenchContext` through `resolveOpenRequest` (slugs) and
 * `useDeepLinkedWorkflow` through `resolveAddressRequest` (addresses). The two
 * resolvers agree — `openAddress.test.ts` walks them — but agreement only
 * holds while they are asked about the *same* name, and for a mount they were
 * not. `CURRENT_SLUG_KEY` deliberately holds the **class** slug
 * (`chinook-assistant`) while the URL and `OPEN_ADDRESS_KEY` hold the
 * **address** (`concierge/wf-music`); the storage split above says so at
 * length, and it is right. Reading the class slug as if it were the URL's
 * subject is what was wrong.
 *
 * The two are never equal for an instance, so the slug hook called every
 * reload of an open mount a fresh arrival while the address hook called it a
 * reload. Each declined the work it believed the other was doing and the
 * canvas came up empty — 0 nodes, no answer card, which is how
 * `production-ready` 07 was reported ("a mount's answer is not rendered").
 *
 * The fallback to the class slug is not a compromise: for a package the two
 * keys hold the same string, and a tab predating `OPEN_ADDRESS_KEY` has only
 * the one.
 */
export function openSubject(input: {
  openAddress: string | null;
  classSlug: string | null;
}): string | null {
  return input.openAddress ?? input.classSlug;
}

/** Forget the open instance: a new, never-saved document has no address. */
export function clearOpenAddress(): void {
  try {
    sessionStorage.removeItem(OPEN_ADDRESS_KEY);
  } catch {
    // Nothing to forget if it could not be read in the first place.
  }
}

/**
 * What a page load should do, decided before anything is fetched — the
 * address-aware form of `resolveOpenRequest`.
 *
 * The comparison is between **addresses**, and that is the whole point.
 * `concierge/wf-music` and `concierge/wf-other` are both the
 * `chinook-assistant` package, so a slug comparison would call the second a
 * reload of the first and leave the wrong instance's overrides on screen. The
 * unsaved-edits rule it inherits is unchanged: a reload of the address already
 * open restores this tab's autosave rather than refetching over it — and so is
 * ticket 49's correction to it, that "restore this tab's autosave" is only a
 * decision worth making when there *is* one. With no draft, the fallback is the
 * document the address names, never a blank canvas. `resolveOpenRequest` states
 * the case at length; the two must answer alike, and
 * `openAddress.test.ts` pins that they do.
 */
export function resolveAddressRequest(input: {
  urlAddress: MountAddress | null;
  openAddress: MountAddress | null;
  /** Whether this browser holds a draft of the address already open here. */
  hasDraft?: boolean;
}): { readonly action: 'fetch'; readonly address: MountAddress } | { readonly action: 'restore' } {
  const { urlAddress, openAddress } = input;
  if (urlAddress !== null && (openAddress === null || !addressEquals(urlAddress, openAddress))) {
    return { action: 'fetch', address: urlAddress };
  }
  if (urlAddress !== null && input.hasDraft === false) {
    return { action: 'fetch', address: urlAddress };
  }
  // No parameter, a package already claimed here, and no draft of it — the
  // same fallback, for the branch ticket 49 left out (`production-ready` 71).
  // Its twin in `resolveOpenRequest` carries the reasoning; the two must
  // answer alike and `openAddress.test.ts` pins that they do.
  if (urlAddress === null && openAddress !== null && input.hasDraft === false) {
    return { action: 'fetch', address: openAddress };
  }
  return { action: 'restore' };
}

/**
 * Subscribe to "this tab is now displaying a different address".
 *
 * A thin projection of `subscribeOpenSlug`'s channel: the subject announced is
 * the address string, so a listener that cares about the *address* rereads it
 * from storage rather than parsing the announcement. One channel, one ordering
 * guarantee — storage and the URL are both settled before anyone is told.
 */
export function subscribeOpenAddress(listener: () => void): () => void {
  return subscribeOpenSlug(() => listener());
}

/** Whether the tab is displaying a mount rather than a document. */
export function isInstanceOpen(): boolean {
  const address = getOpenAddress();
  return address !== null && isInstance(address);
}

function syncUrl(address: MountAddress | null): void {
  if (typeof window === 'undefined' || !window.history?.replaceState) return;
  const next = urlWithAddress(window.location.href, address);
  if (next === `${window.location.pathname}${window.location.search}${window.location.hash}`) {
    return; // Nothing moved; do not churn the history entry.
  }
  window.history.replaceState(window.history.state, '', next);
}
