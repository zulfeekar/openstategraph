import { describe, expect, it } from 'vitest';
import {
  clearOpenSlug,
  readSlugFromSearch,
  resolveOpenRequest,
  setOpenSlug,
  subscribeOpenSlug,
  urlWithSlug,
} from './openWorkflow';

/**
 * Ticket 20 — the editor had no URL routing at all, so a workflow could not be
 * linked, bookmarked, or reopened by reload. Everything here is the decision
 * half of that, kept pure so it is testable without a DOM.
 */
describe('readSlugFromSearch', () => {
  it('reads the workflow parameter', () => {
    expect(readSlugFromSearch('?w=chinook-assistant')).toBe('chinook-assistant');
  });

  it('is null when there is no workflow parameter', () => {
    expect(readSlugFromSearch('')).toBeNull();
    expect(readSlugFromSearch('?theme=dark')).toBeNull();
  });

  it('treats a bare or blank parameter as no link, not as an empty slug', () => {
    // An empty slug would ask the backend about the workflows root itself.
    expect(readSlugFromSearch('?w=')).toBeNull();
    expect(readSlugFromSearch('?w=%20')).toBeNull();
  });
});

describe('urlWithSlug', () => {
  it('adds the parameter to a bare URL', () => {
    expect(urlWithSlug('http://localhost:5273/', 'my-workflow')).toBe('/?w=my-workflow');
  });

  it('replaces an existing one rather than appending a second', () => {
    expect(urlWithSlug('http://localhost:5273/?w=old', 'new')).toBe('/?w=new');
  });

  it('removes it for a workflow that is not on the backend yet', () => {
    expect(urlWithSlug('http://localhost:5273/?w=old', null)).toBe('/');
  });

  it('leaves every other parameter and the hash alone', () => {
    // The address bar is shared; quietly dropping somebody's query string
    // because we rewrote the URL breaks things nobody connects back to this.
    expect(urlWithSlug('http://localhost:5273/?debug=1&w=old#n1', 'new')).toBe(
      '/?debug=1&w=new#n1',
    );
  });
});

describe('resolveOpenRequest', () => {
  it('fetches the workflow a link names', () => {
    expect(resolveOpenRequest({ urlSlug: 'shared-flow', openSlug: null })).toEqual({
      action: 'fetch',
      slug: 'shared-flow',
    });
  });

  it('fetches when the link names a different workflow than this tab has open', () => {
    expect(resolveOpenRequest({ urlSlug: 'other', openSlug: 'mine' })).toEqual({
      action: 'fetch',
      slug: 'other',
    });
  });

  it('restores rather than refetching when the link names the open workflow', () => {
    // The reload case, and the one a "URL always wins" rule gets wrong: this
    // tab's autosave holds unsaved edits to that same workflow, and fetching
    // the file over them would discard work on every press of reload.
    expect(resolveOpenRequest({ urlSlug: 'mine', openSlug: 'mine' })).toEqual({
      action: 'restore',
    });
  });

  it('restores when there is no link at all', () => {
    expect(resolveOpenRequest({ urlSlug: null, openSlug: 'mine' })).toEqual({ action: 'restore' });
    expect(resolveOpenRequest({ urlSlug: null, openSlug: null })).toEqual({ action: 'restore' });
  });
});

/**
 * Ticket 23 — the autosave key has to follow the open workflow.
 *
 * Reading the slug on demand is enough for a value that only moves at
 * startup. It moves mid-session too, and a tab that opened workflow B while
 * still autosaving under workflow A's key destroyed A's draft on the next
 * keystroke. `sessionStorage` fires no storage event in the tab that wrote it,
 * which is the only tab that cares — hence a plain subscription.
 */
describe('subscribeOpenSlug', () => {
  it('tells a subscriber which workflow is now open', () => {
    const seen: (string | null)[] = [];
    const off = subscribeOpenSlug((slug) => seen.push(slug));

    setOpenSlug('concierge');
    clearOpenSlug();
    off();
    setOpenSlug('after-unsubscribe');

    expect(seen).toEqual(['concierge', null]);
  });

  it('tells every subscriber even when one of them throws', () => {
    const seen: (string | null)[] = [];
    const offBad = subscribeOpenSlug(() => {
      throw new Error('a subscriber is not the slug’s problem');
    });
    const offGood = subscribeOpenSlug((slug) => seen.push(slug));

    expect(() => setOpenSlug('chinook-assistant')).not.toThrow();
    expect(seen).toEqual(['chinook-assistant']);

    offBad();
    offGood();
  });
});
