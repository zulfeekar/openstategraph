import { describe, expect, it } from 'vitest';

import { restoredDraftNotice } from './restoredDraftNotice';

/**
 * `every-workflow-green` 25 — a warm reload put this browser's older copy on
 * screen over a newer file and said nothing.
 */
describe('restoredDraftNotice', () => {
  it('names the workflow, so the sentence is about something', () => {
    expect(restoredDraftNotice('ops-desk')).toContain('ops-desk');
  });

  it('says which of the two the user is looking at', () => {
    const notice = restoredDraftNotice('ops-desk');
    expect(notice).toMatch(/unsaved edits/i);
    expect(notice).toMatch(/not the saved file/i);
  });

  it('warns that the file may have moved on', () => {
    // The half that cost the time: the draft winning is fine, not knowing is not.
    expect(restoredDraftNotice('ops-desk')).toMatch(/changed elsewhere/i);
  });

  it('says nothing when there is no workflow open', () => {
    expect(restoredDraftNotice(null)).toBe('');
    expect(restoredDraftNotice('')).toBe('');
    expect(restoredDraftNotice('   ')).toBe('');
  });
});
