import { describe, expect, it } from 'vitest';
import { packageRows } from './packageRows';

const CATALOGUE = [
  { slug: 'chinook-assistant', name: 'Chinook Assistant' },
  { slug: 'concierge', name: 'Concierge (gateway)' },
  { slug: 'morning-brief', name: 'Morning Brief' },
];

describe('the Packages palette rows', () => {
  it('lists every saved package, in the catalogue’s own order', () => {
    expect(packageRows(CATALOGUE, [], '').map((row) => row.slug)).toEqual([
      'chinook-assistant',
      'concierge',
      'morning-brief',
    ]);
  });

  it('is droppable when nothing above the open document names it', () => {
    expect(
      packageRows(CATALOGUE, ['something-else'], '').every((row) => row.refusal === null),
    ).toBe(true);
  });

  describe('a package already above this document', () => {
    it('is listed rather than hidden — the row a reader is hunting for stays', () => {
      const rows = packageRows(CATALOGUE, ['concierge'], '');
      expect(rows.map((row) => row.slug)).toContain('concierge');
    });

    it('refuses in the compiler’s own sentence, chain included', () => {
      const rows = packageRows(CATALOGUE, ['concierge'], '');
      expect(rows.find((row) => row.slug === 'concierge')?.refusal).toBe(
        "Workflow 'concierge' includes itself through its subgraphs (concierge -> concierge); " +
          'a subgraph cycle can never terminate',
      );
    });

    it('refuses a drill ancestor too, not only the document on screen', () => {
      const rows = packageRows(CATALOGUE, ['concierge', 'chinook-assistant'], '');
      expect(rows.find((row) => row.slug === 'concierge')?.refusal).toBe(
        "Workflow 'concierge' includes itself through its subgraphs " +
          '(concierge -> chinook-assistant -> concierge); a subgraph cycle can never terminate',
      );
      expect(rows.find((row) => row.slug === 'morning-brief')?.refusal).toBeNull();
    });
  });

  describe('search', () => {
    it('matches the name', () => {
      expect(packageRows(CATALOGUE, [], 'Morning').map((row) => row.slug)).toEqual([
        'morning-brief',
      ]);
    });

    it('matches the slug, which is what a developer actually remembers', () => {
      expect(packageRows(CATALOGUE, [], 'chinook').map((row) => row.slug)).toEqual([
        'chinook-assistant',
      ]);
    });

    it('ignores case and surrounding space', () => {
      expect(packageRows(CATALOGUE, [], '  CONCIERGE ').map((row) => row.slug)).toEqual([
        'concierge',
      ]);
    });

    it('keeps a refused row visible in results, so the reason is still readable', () => {
      const rows = packageRows(CATALOGUE, ['concierge'], 'concierge');
      expect(rows).toHaveLength(1);
      expect(rows[0]?.refusal).not.toBeNull();
    });
  });
});
