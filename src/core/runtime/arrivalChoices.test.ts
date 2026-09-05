import { describe, expect, it } from 'vitest';
import { arrivalChoices, packageLocation } from './arrivalChoices';
import type { WorkflowSummary } from './WorkflowFileClient';

/**
 * `install-experience` 28 — the order a project's workflows are offered in.
 *
 * The ticket's words are *"most recently opened or edited first"*, and that is
 * two clocks rather than one. **Edited** is `savedAt`, which the backend reads
 * off the package on disk and every browser sees alike. **Opened** is this
 * browser's own record, which nobody else has and which a private window does
 * not keep. Neither dominates the other and the row says which one placed it,
 * because a list sorted by a fact the reader cannot see is a list they cannot
 * argue with.
 */

const row = (over: Partial<WorkflowSummary> & { slug: string }): WorkflowSummary => ({
  name: over.slug,
  savedAt: '',
  nodeCount: 0,
  edgeCount: 0,
  published: true,
  hidden: false,
  findings: [],
  digest: '',
  ...over,
});

describe('arrivalChoices', () => {
  it('orders by the later of the two clocks, not by either one alone', () => {
    const rows = [
      // Edited long ago, opened minutes ago — the one you were last in.
      row({ slug: 'lens-qa', savedAt: '2026-08-01T00:00:00Z' }),
      // Never opened here, edited this morning — the freshest thing on disk.
      row({ slug: 'concierge', savedAt: '2026-08-31T09:00:00Z' }),
      // Neither: on disk, untouched, unopened.
      row({ slug: 'archive', savedAt: '2026-07-01T00:00:00Z' }),
    ];

    const ordered = arrivalChoices(rows, { 'lens-qa': '2026-08-31T10:00:00Z' });

    expect(ordered.map((choice) => choice.slug)).toEqual(['lens-qa', 'concierge', 'archive']);
  });

  it('says which clock placed each row', () => {
    const rows = [
      row({ slug: 'lens-qa', savedAt: '2026-08-01T00:00:00Z' }),
      row({ slug: 'concierge', savedAt: '2026-08-31T09:00:00Z' }),
      row({ slug: 'never-seen' }),
    ];

    const by = new Map(
      arrivalChoices(rows, { 'lens-qa': '2026-08-31T10:00:00Z' }).map((c) => [c.slug, c]),
    );

    expect(by.get('lens-qa')?.from).toBe('opened');
    expect(by.get('concierge')?.from).toBe('edited');
    // Neither clock has anything to say, and the row admits it rather than
    // claiming the epoch.
    expect(by.get('never-seen')?.from).toBe('never');
    expect(by.get('never-seen')?.at).toBe('');
  });

  it('falls back to the disk clock alone when this browser remembers nothing', () => {
    // The private-window case, and the throwing-storage case, and the
    // brand-new-browser case: they all arrive here as an empty map, and the
    // answer must be an order rather than an error.
    const rows = [
      row({ slug: 'a', savedAt: '2026-08-01T00:00:00Z' }),
      row({ slug: 'b', savedAt: '2026-08-30T00:00:00Z' }),
    ];

    expect(arrivalChoices(rows, {}).map((c) => c.slug)).toEqual(['b', 'a']);
  });

  it('is deterministic when two rows carry the same instant', () => {
    const rows = [
      row({ slug: 'zebra', savedAt: '2026-08-01T00:00:00Z' }),
      row({ slug: 'alpha', savedAt: '2026-08-01T00:00:00Z' }),
    ];

    expect(arrivalChoices(rows, {}).map((c) => c.slug)).toEqual(['alpha', 'zebra']);
  });

  it('ignores an opened stamp for a package that is no longer there', () => {
    // A deleted package leaves its stamp behind. It must not conjure a row.
    const ordered = arrivalChoices([row({ slug: 'a', savedAt: '2026-08-01T00:00:00Z' })], {
      deleted: '2026-08-31T00:00:00Z',
    });

    expect(ordered.map((c) => c.slug)).toEqual(['a']);
  });

  it('survives a timestamp that is not a date', () => {
    // Hand-edited storage, a truncated write, a backend that changed format:
    // an unreadable stamp is *no* stamp, never a crash and never a row that
    // sorts to the top because `NaN` compared oddly.
    const rows = [
      row({ slug: 'good', savedAt: '2026-08-01T00:00:00Z' }),
      row({ slug: 'junk', savedAt: 'not-a-date' }),
    ];

    const ordered = arrivalChoices(rows, { junk: 'also-not-a-date' });
    expect(ordered.map((c) => c.slug)).toEqual(['good', 'junk']);
    expect(ordered[1]?.from).toBe('never');
  });

  it('carries where the package lives, because that is the question a list of names cannot answer', () => {
    const [choice] = arrivalChoices([row({ slug: 'lens-qa', name: 'Lens QA' })], {});
    expect(choice?.location).toBe(packageLocation('lens-qa'));
    expect(choice?.location).toContain('lens-qa');
  });

  it('keeps a hidden package in the list and marks it', () => {
    // The same decision `WorkflowSummary.hidden` records: the editor's own
    // surface shows a hidden package and says so, rather than pretending a
    // directory on disk is not there.
    const [choice] = arrivalChoices([row({ slug: 'workflow-architect', hidden: true })], {});
    expect(choice?.hidden).toBe(true);
  });
});
