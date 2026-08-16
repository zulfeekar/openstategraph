import { describe, expect, it } from 'vitest';
import { progressLine } from './progressLine';

/**
 * The editor's half of production-ready 50/56: the backend grew producers for
 * the `progress` frame, and the editor grew the branch that shows one. This
 * pins the only part of that branch that can be silently wrong.
 */
describe('the live progress line', () => {
  it('shows both numbers when the step knows both', () => {
    expect(progressLine({ message: 'Read invoices', current: 40, total: 100 })).toBe(
      'Read invoices (40/100)',
    );
  });

  it('shows the count alone when nothing knows the total', () => {
    // The common shape for a paging tool: it knows it is on page three and
    // will find out how many there are by running out.
    expect(progressLine({ message: 'Paging', current: 3, total: null })).toBe('Paging (3)');
  });

  it('says nothing about counts when neither is known', () => {
    // Never "(0/0)". `null` means *no claim*, not zero — a bar rendered from
    // an invented pair would say a job had not started when it is halfway.
    expect(
      progressLine({ message: 'Calling search_docs on docs', current: null, total: null }),
    ).toBe('Calling search_docs on docs');
  });

  it('drops a total that has no count beside it', () => {
    // "of 12" alone adds nothing the message did not already carry, and a
    // bare "(12)" would be read as progress rather than as the size of it.
    expect(progressLine({ message: 'Fetching', current: null, total: 12 })).toBe('Fetching');
  });
});
