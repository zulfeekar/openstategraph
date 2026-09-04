import { describe, expect, it } from 'vitest';

import { senderLabel } from './senderLabel';

describe('the name above the workflow’s first bubble', () => {
  it('is the document’s own name', () => {
    expect(senderLabel('Support Triage')).toBe('Support Triage');
  });

  it('trims, so a stray space in the name box is not a stray space in the thread', () => {
    expect(senderLabel('  Ops Desk  ')).toBe('Ops Desk');
  });

  it('falls back to the word the top bar shows when the document has no name', () => {
    // Not an empty label: a bubble with nothing above it is unattributed,
    // which is the defect this ticket is about.
    expect(senderLabel('')).toBe('Untitled');
    expect(senderLabel('   ')).toBe('Untitled');
    expect(senderLabel('Untitled')).toBe('Untitled');
  });
});
