import { afterEach, describe, expect, it } from 'vitest';
import {
  resolveOptions,
  validateFields,
  type ComboboxFieldSchema,
} from '@core/model/contracts/fields';
import { provideMountAncestry, type MountAncestryReader } from '@core/runtime/mountAncestry';
import { workflowCatalogue } from '@core/runtime/workflowCatalogue';
import { subgraphNode } from './SubgraphNode';

/**
 * The editor's half of the self-inclusion refusal (organisms-first-class 42).
 *
 * The compiler already refuses this — `node_runtime.py::_subgraph` and
 * `api/mount_resolution.py`, both proven — and stays the authority. What is
 * asserted here is that the editor says the **same sentence** first, and that
 * it says it through the field schema, so the card and the inspector both show
 * it without either one implementing the rule.
 */
let restore: MountAncestryReader | null = null;

afterEach(() => {
  if (restore) provideMountAncestry(restore);
  restore = null;
});

function standingIn(...ancestry: string[]): void {
  const previous = provideMountAncestry(() => ancestry);
  restore ??= previous;
}

/** What the card and the inspector would show under this mount's slug. */
function slugError(workflow: string): string | undefined {
  return validateFields(subgraphNode.fields, { workflow, outcome: '', overrides: '' })['workflow'];
}

describe('the workflow combobox refuses a mount that would include itself', () => {
  it('refuses the open document with the compiler’s own words', () => {
    standingIn('concierge');
    expect(slugError('concierge')).toBe(
      "Workflow 'concierge' mounts itself " +
        '(concierge -> concierge); a mount cycle can never terminate',
    );
  });

  it('refuses an ancestor you drilled through, not just the document on screen', () => {
    standingIn('concierge', 'chinook-assistant');
    expect(slugError('concierge')).toContain('mounts itself ');
    expect(slugError('concierge')).toContain('(concierge -> chinook-assistant -> concierge)');
  });

  it('allows any package that is not on the trail', () => {
    standingIn('concierge', 'chinook-assistant');
    expect(slugError('sql-analyst')).toBeUndefined();
  });

  it('keeps a forward reference legal — free text is deliberate', () => {
    standingIn('concierge');
    expect(slugError('not-built-yet')).toBeUndefined();
  });

  it('says nothing about an empty slug', () => {
    standingIn('concierge');
    expect(slugError('')).toBeUndefined();
  });

  it('refuses nothing at all when no ancestry is installed', () => {
    // The default. A `core/` test, a worker, or the editor before bootstrap
    // must not invent a refusal the compiler would not make.
    expect(slugError('concierge')).toBeUndefined();
  });

  it('is declared on the schema, so card and inspector cannot disagree', () => {
    const field = subgraphNode.fields.find((schema) => schema.key === 'workflow');
    expect(field?.kind).toBe('combobox');
    expect(field?.validate).toBeTypeOf('function');
  });

  it('marks an ancestor in the suggestions rather than waiting to punish the pick', () => {
    workflowCatalogue.set([
      { slug: 'concierge', name: 'Concierge' },
      { slug: 'sql-analyst', name: 'SQL Analyst' },
    ]);
    standingIn('concierge');
    const options = resolveOptions(
      subgraphNode.fields.find((schema) => schema.key === 'workflow') as ComboboxFieldSchema,
      {},
    );
    const self = options.find((option) => option.value === 'concierge');
    const other = options.find((option) => option.value === 'sql-analyst');
    expect(self?.label).toContain('would include itself');
    // Still listed, and never `disabled`: a datalist drops a disabled option
    // from its suggestions rather than greying it, so the flag would delete the
    // one entry a reader is hunting for and say nothing about why.
    expect(options).toHaveLength(2);
    expect(self?.disabled).toBeUndefined();
    expect(other?.label).not.toContain('would include itself');
    expect(other?.disabled).toBeUndefined();
    workflowCatalogue.set([]);
  });
});
