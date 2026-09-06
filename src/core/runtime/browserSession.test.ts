import { describe, expect, it } from 'vitest';

import { browserSessionId, type SessionStore } from './browserSession';

/** A tab's `sessionStorage`, with no browser involved. */
function tab(seed: Record<string, string> = {}): SessionStore & { seen: Record<string, string> } {
  const seen = { ...seed };
  return {
    seen,
    getItem: (key) => seen[key] ?? null,
    setItem: (key, value) => {
      seen[key] = value;
    },
  };
}

describe('the sitting a run belongs to', () => {
  it('is the same value for every run in one tab', () => {
    const store = tab();

    expect(browserSessionId(store)).toBe(browserSessionId(store));
  });

  it('is not empty, which is the whole defect it exists to end', () => {
    // `memory-and-replay/45`: `session_id` reached the row as `''` on every
    // real run, so `?session_id=` matched the entire listing.
    expect(browserSessionId(tab())).not.toBe('');
  });

  it('survives a reload, because the tab did', () => {
    const store = tab();
    const first = browserSessionId(store);

    // A reload is a new call against the same `sessionStorage`.
    expect(browserSessionId(tab({ ...store.seen }))).toBe(first);
  });

  it('is a different sitting in a second tab', () => {
    // `sessionStorage` is not shared between tabs, so two tabs are two
    // sittings — which is the axis a QA engineer reproducing a report reads.
    expect(browserSessionId(tab())).not.toBe(browserSessionId(tab()));
  });

  it('is empty rather than unstable when there is nowhere to remember it', () => {
    // A private window with site data blocked. A minted-but-unpersisted id
    // would differ on every send: a filter matching one run instead of all.
    const throwing: SessionStore = {
      getItem: () => {
        throw new Error('site data blocked');
      },
      setItem: () => {},
    };

    expect(browserSessionId(throwing)).toBe('');
    expect(browserSessionId(null)).toBe('');
  });
});
