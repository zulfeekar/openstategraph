import { describe, expect, it } from 'vitest';

import { draftIsStale } from './staleDraft';

/**
 * `every-workflow-green` 25 — the editor showed a cached draft over a newer
 * file, silently, and three correct fixes appeared to do nothing.
 */
describe('draftIsStale', () => {
  const EARLY = '2026-08-19T10:00:00.000Z';
  const LATE = '2026-08-19T12:00:00.000Z';

  it('is stale when the file was saved after the draft was taken', () => {
    expect(draftIsStale(EARLY, LATE)).toBe(true);
  });

  it('is not stale when the draft is the newer of the two', () => {
    // A person's unsaved work. Losing this was the original complaint.
    expect(draftIsStale(LATE, EARLY)).toBe(false);
  });

  it('is not stale when they are the same moment', () => {
    expect(draftIsStale(EARLY, EARLY)).toBe(false);
  });

  it('keeps the draft when either timestamp is missing', () => {
    // Cannot-tell must not throw away edits — that is the worse failure.
    expect(draftIsStale(null, LATE)).toBe(false);
    expect(draftIsStale(EARLY, undefined)).toBe(false);
    expect(draftIsStale(null, null)).toBe(false);
  });

  it('keeps the draft when a timestamp is unparseable', () => {
    expect(draftIsStale('not a date', LATE)).toBe(false);
    expect(draftIsStale(EARLY, 'not a date')).toBe(false);
  });
});
