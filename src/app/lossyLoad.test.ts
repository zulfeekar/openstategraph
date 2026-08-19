import { describe, expect, it } from 'vitest';

import { loadWasFaithful } from './lossyLoad';

/**
 * `every-workflow-green` 22 — opening a hand-written workflow deleted four of
 * its twelve edges from the file on disk.
 */
describe('loadWasFaithful', () => {
  it('is true for a clean load, which may be autosaved over', () => {
    expect(loadWasFaithful({ ok: true })).toBe(true);
  });

  it('is false when the serializer dropped a link', () => {
    expect(
      loadWasFaithful({ ok: true, message: 'Dropped a link to a port that no longer exists' }),
    ).toBe(false);
  });

  it('is false for any warning at all, not only dropped links', () => {
    // An unknown node type, a coerced field — every one of them means the
    // model is not what the file says, and none may be written back.
    expect(loadWasFaithful({ ok: true, message: 'Node "x" has an unknown type' })).toBe(false);
  });

  it('is false for a failed load', () => {
    expect(loadWasFaithful({ ok: false, message: 'not json' })).toBe(false);
  });
});
