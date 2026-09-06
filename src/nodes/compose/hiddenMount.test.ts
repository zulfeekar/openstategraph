import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import {
  resolveOptions,
  type ComboboxFieldSchema,
  type FieldOption,
} from '@core/model/contracts/fields';
import { provideMountAncestry, type MountAncestryReader } from '@core/runtime/mountAncestry';
import { HIDDEN_PACKAGE_MARK, workflowCatalogue } from '@core/runtime/workflowCatalogue';
import { subgraphNode } from './SubgraphNode';

/**
 * The mount combobox marks a package no customer surface advertises —
 * production-ready ticket 57.
 *
 * `GET /api/workflows?surface=editor` returns hidden packages on purpose
 * (`concierge` mounts `workflow-architect`, so filtering them would make a
 * shipped composition undrawable) and sets `hidden` on each row "so the UI can
 * mark one rather than pretend it is not there". Nothing did, so `concierge`
 * and `workflow-architect` were indistinguishable here from `chinook-assistant`.
 *
 * The Packages palette is the other consumer of exactly these rows, it marks
 * them from the same constant, and its half is pinned in
 * `view/palette/packageRows.test.ts`. The two are deliberately consistent and
 * must stay that way.
 */
let restore: MountAncestryReader | null = null;

afterEach(() => {
  if (restore) provideMountAncestry(restore);
  restore = null;
  workflowCatalogue.set([]);
});

function standingIn(...ancestry: string[]): void {
  const previous = provideMountAncestry(() => ancestry);
  restore ??= previous;
}

function suggestions(): readonly FieldOption[] {
  return resolveOptions(
    subgraphNode.fields.find((schema) => schema.key === 'workflow') as ComboboxFieldSchema,
    {},
  );
}

describe('the workflow combobox', () => {
  // The catalogue is a module singleton, so each test reinstalls its rows.
  beforeEach(() => {
    workflowCatalogue.set([
      { slug: 'chinook-assistant', name: 'Chinook Assistant', hidden: false },
      { slug: 'concierge', name: 'Concierge', hidden: true },
      { slug: 'workflow-architect', name: 'Workflow Architect', hidden: true },
    ]);
  });

  it('marks a hidden package, so a developer knows it is not advertised', () => {
    const hidden = suggestions().find((option) => option.value === 'workflow-architect');
    expect(hidden?.label).toContain(HIDDEN_PACKAGE_MARK);
  });

  it('leaves an ordinary package unmarked', () => {
    const ordinary = suggestions().find((option) => option.value === 'chinook-assistant');
    expect(ordinary?.label).toBe('Chinook Assistant · chinook-assistant');
  });

  it('still offers it — the mark is not a filter', () => {
    // `concierge` mounts `workflow-architect`, which is hidden. Dropping hidden
    // packages from the suggestions would make a composition we ship
    // undrawable in the very picker that exists to stop mount slugs being
    // typed by hand (ticket 05).
    expect(suggestions().map((option) => option.value)).toEqual([
      'chinook-assistant',
      'concierge',
      'workflow-architect',
    ]);
  });

  it('is never `disabled` for being hidden, which would delete the row', () => {
    // A datalist drops a disabled option from its suggestions rather than
    // greying it — the finding ticket 42 recorded at this same field.
    expect(suggestions().every((option) => option.disabled === undefined)).toBe(true);
  });

  it('carries both marks at once, because they answer different questions', () => {
    // `concierge` is hidden *and*, from inside itself, a mount that would not
    // compile. One says no customer surface advertises the package; the other
    // says this mount is refused. A reader needs both.
    standingIn('concierge');
    const self = suggestions().find((option) => option.value === 'concierge');
    expect(self?.label).toContain(HIDDEN_PACKAGE_MARK);
    expect(self?.label).toContain('would include itself');
  });
});

describe('the word itself', () => {
  const source = readFileSync(fileURLToPath(new URL('./SubgraphNode.ts', import.meta.url)), 'utf8');

  it('comes from the catalogue rather than being spelled here', () => {
    // The palette prints the same word on the same rows. Two string literals
    // would agree today and drift on the first reword.
    expect(source).toContain('HIDDEN_PACKAGE_MARK');
  });
});
