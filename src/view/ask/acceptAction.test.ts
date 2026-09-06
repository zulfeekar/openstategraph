import { describe, expect, it } from 'vitest';
import { acceptAction } from './acceptAction';

const recipient = { key: 'to', label: 'Recipient', required: true } as const;
const subject = { key: 'subject', label: 'Subject' } as const;

describe('what the accept button on a capability card promises', () => {
  it('promises a re-run when the node it adds can actually run', () => {
    const action = acceptAction('Web Search', [subject], { subject: '' });

    expect(action.label).toBe('Add & re-run');
    expect(action.note).toBeNull();
    expect(action.willRun).toBe(true);
  });

  it('names the field instead of promising a run it will not start', () => {
    const action = acceptAction('Email Send', [recipient, subject], { to: '', subject: '' });

    expect(action.willRun).toBe(false);
    // The label is the promise, and it must be the one that is kept: the node
    // is added and the recipient is still yours to type.
    expect(action.label).toBe('Add & set Recipient');
    expect(action.label).not.toContain('re-run');
    expect(action.note).toContain('Recipient');
    expect(action.note).toContain('Email Send');
  });

  it('says a run does not follow, on the card, before the press', () => {
    const action = acceptAction('Email Send', [recipient], {});

    expect(action.note).toMatch(/ask again|then ask/i);
  });

  it('lists several missing fields the way a sentence does', () => {
    const action = acceptAction('Email Send', [recipient, { ...subject, required: true }], {});

    expect(action.label).toBe('Add & set Recipient and Subject');
  });

  it('treats a field the type already fills as ready', () => {
    const action = acceptAction('Email Send', [recipient], { to: 'ops@example.com' });

    expect(action.willRun).toBe(true);
    expect(action.label).toBe('Add & re-run');
  });
});
