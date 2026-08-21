import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { packageRows } from './packageRows';

/** `concierge` is hidden on disk, and is the fixture for both marks at once. */
const CATALOGUE = [
  { slug: 'chinook-assistant', name: 'Chinook Assistant', hidden: false },
  { slug: 'concierge', name: 'Concierge (gateway)', hidden: true },
  { slug: 'morning-brief', name: 'Morning Brief', hidden: false },
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

    it('refuses the gesture, in the conditional, chain included', () => {
      // `workflow-gallery` 65: this row used to carry the *compiler's*
      // sentence, "Workflow 'concierge' mounts itself" — an accusation about
      // a document that, on the first screen after `new`, contains no mount
      // node at all. The row is right to grey; only the tense was wrong.
      const rows = packageRows(CATALOGUE, ['concierge'], '');
      expect(rows.find((row) => row.slug === 'concierge')?.refusal).toBe(
        "Mounting 'concierge' here would make it mount itself " +
          '(concierge -> concierge); a mount cycle can never terminate',
      );
    });

    it('refuses a drill ancestor too, not only the document on screen', () => {
      const rows = packageRows(CATALOGUE, ['concierge', 'chinook-assistant'], '');
      expect(rows.find((row) => row.slug === 'concierge')?.refusal).toBe(
        "Mounting 'concierge' here would make it mount itself " +
          '(concierge -> chinook-assistant -> concierge); a mount cycle can never terminate',
      );
      expect(rows.find((row) => row.slug === 'morning-brief')?.refusal).toBeNull();
    });
  });

  describe('a package no customer surface advertises', () => {
    /**
     * production-ready ticket 57. The row already knew — `WorkflowSummary.hidden`
     * reaches the catalogue, and the backend sends it on the editor surface
     * precisely "so the UI can mark one rather than pretend it is not there".
     * Nothing read it, so `concierge` and `workflow-architect` sat here looking
     * exactly like a package a developer can advertise.
     */
    it('is listed, because the editor surface owns it and a mount needs it', () => {
      expect(packageRows(CATALOGUE, [], '').map((row) => row.slug)).toContain('concierge');
    });

    it('carries the flag to the row, which is where the palette reads it', () => {
      const rows = packageRows(CATALOGUE, [], '');
      expect(rows.find((row) => row.slug === 'concierge')?.hidden).toBe(true);
      expect(rows.find((row) => row.slug === 'morning-brief')?.hidden).toBe(false);
    });

    it('keeps the two marks independent — hidden is not a refusal', () => {
      // They answer different questions, and `concierge` is routinely both:
      // hidden says no customer surface advertises the package, a refusal says
      // this particular mount would not compile. Collapsing them would grey out
      // a package that is perfectly legal to mount.
      const free = packageRows(CATALOGUE, [], '').find((row) => row.slug === 'concierge');
      expect(free?.hidden).toBe(true);
      expect(free?.refusal).toBeNull();

      const refused = packageRows(CATALOGUE, ['concierge'], '').find(
        (row) => row.slug === 'concierge',
      );
      expect(refused?.hidden).toBe(true);
      expect(refused?.refusal).not.toBeNull();
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

/**
 * consistency-sweep ticket 10, second nit: the refused row *looked* disabled,
 * `button.disabled` was `false`, and dragging it was cancelled in silence —
 * the canvas panned and nothing happened, which reads as a broken palette
 * rather than as a rule. A source assertion, for the reason
 * `mcpPanelSurface.test.ts` records: there is no seam in a `node` environment
 * that would catch a handler quietly returning.
 */
describe('a hidden package row', () => {
  const palette = readFileSync(fileURLToPath(new URL('./Palette.tsx', import.meta.url)), 'utf8');

  it('wears the mark beside its name', () => {
    expect(palette).toMatch(/row\.hidden \?[\s\S]{0,200}HIDDEN_PACKAGE_MARK/);
  });

  it('takes the word from the catalogue rather than spelling it here', () => {
    // The mount combobox marks the same rows, and the two are deliberately
    // consistent with each other (ticket 11, ticket 42). One exported word is
    // what keeps them that way — two string literals would agree today and
    // drift on the first reword.
    expect(palette).toMatch(
      /import \{[^}]*HIDDEN_PACKAGE_MARK[^}]*\} from '@core\/runtime\/workflowCatalogue'/s,
    );
  });

  it('explains itself on hover, which is the only room a palette row has', () => {
    expect(palette).toContain('HIDDEN_PACKAGE_NOTE');
  });
});

describe('a refused package row', () => {
  const palette = readFileSync(fileURLToPath(new URL('./Palette.tsx', import.meta.url)), 'utf8');

  it('says why, once, on the gesture that was refused', () => {
    expect(palette).toContain('onRefuse');
    expect(palette).toMatch(/if \(row\.refusal\) onRefuse\(row\.refusal\)/);
    // **Every** gesture that could have placed this row. Dragging was the
    // silent one; clicking used to run `onActivate` regardless of the refusal.
    // Since `say-it-on-the-surface` 04 a click no longer places anything, so
    // the click handler's only remaining job is to speak the refusal — and
    // the keyboard, which is now the placement path, must speak it too, or
    // the rule would be enforced for the mouse and not for Tab+Enter.
    expect(palette).toMatch(/onClick=\{\(event\) => \{\s*if \(refused\) refuse\(event\);/);
    expect(palette).toMatch(/onKeyDown=\{onKeyboardActivate\(\(\) => \{\s*if \(refused\)/);
    expect(palette).toMatch(/if \(refused\) \{\s*refuse\(event\);/);
  });

  it('is not `disabled`, because that would swallow the explanation', () => {
    // A disabled button fires no mouse events, so the hover text — the
    // compiler's own sentence, and the best thing on the row — would go too.
    expect(palette).toContain('aria-disabled={refused}');
    expect(palette).not.toMatch(/<button[^>]*\n\s*disabled=\{refused\}/);
  });
});

/**
 * `workflow-gallery` 65 — the first screen after `openstategraph new`.
 *
 * A scaffolded package is both the document on screen *and* the only row in
 * the Packages section, which is the coincidence this rule needed: its slug is
 * on its own ancestry trail, so its own row refuses, and the refusal it used to
 * carry was the compiler's diagnosis of a cycle — printed in the row body, not
 * hidden behind a hover — about a document containing no mount node whatsoever.
 * The product's most common starting point accused itself of being broken.
 *
 * The row still greys, because dropping it there genuinely would not compile.
 * What it must never do again is assert something about the graph as drawn.
 *
 * Every shipped template is walked, because the sighting named `routed-qa` and
 * "is this template special?" was one of the open questions. None of them is.
 */
describe('a freshly scaffolded package, open in the editor', () => {
  const templatesDir = fileURLToPath(
    new URL('../../../backend/openstategraph/templates/', import.meta.url),
  );
  const slugs = readdirSync(templatesDir, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && !entry.name.startsWith('__'))
    .map((entry) => entry.name);

  it('walks every shipped template, so none can be special by being absent', () => {
    expect(slugs).toContain('routed-qa');
    expect(slugs.length).toBeGreaterThanOrEqual(3);
  });

  for (const template of slugs) {
    describe(`scaffolded from ${template}`, () => {
      const raw = JSON.parse(
        readFileSync(`${templatesDir}${template}/workflow.json`, 'utf8'),
      ) as Record<string, unknown>;
      // A saved package wraps its document; a template on disk does not.
      const document = (raw.document ?? raw) as { nodes: { type: string }[] };
      const slug = `${template}-demo`;
      const row = packageRows([{ slug, name: 'Routed Demo', hidden: false }], [slug], '')[0];

      it('draws no mount node of its own — nothing here mounts anything', () => {
        expect(document.nodes.some((node) => node.type === 'workflow.subgraph')).toBe(false);
      });

      it('is greyed, because dropping it into itself would not compile', () => {
        expect(row?.refusal).not.toBeNull();
      });

      it('is never told that it mounts itself', () => {
        expect(row?.refusal).not.toContain(`Workflow '${slug}' mounts itself`);
        expect(row?.refusal).not.toMatch(/\bmounts itself\b/);
      });

      it('is told what the gesture would do, with the path and the reason', () => {
        expect(row?.refusal).toBe(
          `Mounting '${slug}' here would make it mount itself ` +
            `(${slug} -> ${slug}); a mount cycle can never terminate`,
        );
      });
    });
  }
});
