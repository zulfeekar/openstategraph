import { describe, expect, it } from 'vitest';
import {
  deleteConfirmation,
  deletedMessage,
  duplicateNameConfirmation,
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

describe('duplicateNameConfirmation', () => {
  it('names the workflow, the slug already holding it, and what happens next', () => {
    const text = duplicateNameConfirmation('AI Workflow', ['ai-workflow']);

    expect(text).toContain('AI Workflow');
    expect(text).toContain('ai-workflow');
    // The offer the ticket asked for: rename, rather than a silent second one.
    expect(text).toContain('rename');
  });

  it('counts them when a name already belongs to more than one', () => {
    const text = duplicateNameConfirmation('AI Workflow', ['ai-workflow', 'ai-workflow-2']);

    expect(text).toContain('2 packages');
    expect(text).toContain('ai-workflow-2');
  });
});

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
  it('says what changed: draft, then visible to the chat app', () => {
    const text = publishedMessage('Support Triage');
    expect(text).toContain('Support Triage');
    expect(text).toContain('draft');
    // Plain words, the same ones the toolbar badge uses (ship-it 52) — never
    // the internal surface names the badge was corrected away from.
    expect(text).toContain('chat app');
    expect(text).not.toContain('/chat picker');
    expect(text).not.toContain('Auto routing');
    // Publishing never rebuilds routing knowledge as a side effect, and the
    // one moment somebody cares is this one.
    expect(text).toMatch(/knowledge/i);
  });
});

describe('unpublishedMessage', () => {
  it('says the workflow survives and only the chat app surface changed', () => {
    const text = unpublishedMessage('Support Triage');
    expect(text).toContain('draft');
    expect(text).toContain('chat app');
    expect(text).not.toContain('/chat picker');
    // The fear this sentence exists to answer: unpublish is not delete.
    expect(text).toMatch(/nothing is deleted|files are untouched|folder is untouched/i);
  });
});
