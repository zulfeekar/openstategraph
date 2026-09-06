import { describe, expect, it } from 'vitest';

import { draftIsAhead, draftIsStale } from './staleDraft';

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

describe('draftIsAhead', () => {
  it('is true only when this browser holds work newer than the file', () => {
    expect(draftIsAhead('2026-08-22T10:00:00Z', '2026-08-22T09:00:00Z')).toBe(true);
    expect(draftIsAhead('2026-08-22T09:00:00Z', '2026-08-22T10:00:00Z')).toBe(false);
    // Equal is not ahead: a save writes both, and a confirm fired by every
    // publish immediately after a save is a confirm nobody reads.
    expect(draftIsAhead('2026-08-22T10:00:00Z', '2026-08-22T10:00:00Z')).toBe(false);
  });

  it('answers false when it cannot tell, unlike draftIsStale', () => {
    // The two guard opposite losses; the defaults are opposite on purpose.
    expect(draftIsAhead(null, '2026-08-22T10:00:00Z')).toBe(false);
    expect(draftIsAhead('2026-08-22T10:00:00Z', undefined)).toBe(false);
    expect(draftIsAhead('not a date', '2026-08-22T10:00:00Z')).toBe(false);
    expect(draftIsStale(null, '2026-08-22T10:00:00Z')).toBe(false);
  });
});
