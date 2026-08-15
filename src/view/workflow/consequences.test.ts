import { describe, expect, it } from 'vitest';
import {
  deleteConfirmation,
  deletedMessage,
  publishedMessage,
  unpublishedMessage,
} from './consequences';

/**
 * Ticket 06 — "deleting says what is lost, publishing says what changed".
 *
 * The copy lives here rather than inline in `WorkflowManager` for one reason:
 * these sentences are the *feature*. A confirm that says only "this cannot be
 * undone" has not told anyone what it is about to remove, and a publish toast
 * that does not name `/chat` leaves the rule the lifecycle exists for
 * invisible. Tested strings are strings somebody has to keep true.
 */

describe('deleteConfirmation', () => {
  it('names the workflow and the folder that goes with it', () => {
    const text = deleteConfirmation('Support Triage', false);
    expect(text).toContain('Support Triage');
    // The document is the least of it — tools, tests and knowledge are files
    // in the same package and they go too.
    expect(text).toContain('folder');
    expect(text).toContain('tools');
    expect(text).toContain('cannot be undone');
  });

  it('adds the consequence a published workflow has and a draft does not', () => {
    expect(deleteConfirmation('Concierge', true)).toContain('/chat');
    expect(deleteConfirmation('Concierge', false)).not.toContain('/chat');
  });
});

describe('deletedMessage', () => {
  it('reports the removal in the same terms the confirm used', () => {
    const text = deletedMessage('Support Triage');
    expect(text).toContain('Support Triage');
    expect(text).toContain('folder');
  });
});

describe('publishedMessage', () => {
  it('says what changed: draft, then visible in /chat', () => {
    const text = publishedMessage('Support Triage');
    expect(text).toContain('Support Triage');
    expect(text).toContain('draft');
    expect(text).toContain('/chat');
    // Publishing never rebuilds routing knowledge as a side effect, and the
    // one moment somebody cares is this one.
    expect(text).toMatch(/knowledge/i);
  });
});

describe('unpublishedMessage', () => {
  it('says the workflow survives and only the /chat surface changed', () => {
    const text = unpublishedMessage('Support Triage');
    expect(text).toContain('draft');
    expect(text).toContain('/chat');
    // The fear this sentence exists to answer: unpublish is not delete.
    expect(text).toMatch(/nothing is deleted|files are untouched|folder is untouched/i);
  });
});
