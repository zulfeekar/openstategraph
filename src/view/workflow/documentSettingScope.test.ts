import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { DOCUMENT_LOCKED_IN_INSTANCE, documentSettingScope } from './documentSettingScope';
import { STEP_BUDGET_HINT } from './stepBudget';

/**
 * `workflow-gallery` 70 — the boxes an instance was going to refuse anyway.
 *
 * Reproduced before this file existed, at `http://…/?w=delegate-by-mount/mount-sql`:
 * both **Name** and **Step budget** were enabled, both accepted a full string,
 * and both *kept showing it* after blur while a toast said the change had not
 * been applied and the toolbar still read `SQL QA`. Three surfaces, two of
 * them lying.
 *
 * The rule is asserted here rather than through a render because vitest runs
 * `environment: 'node'` — the same reason `stepBudget.ts` is a plain module.
 * The inverse halves are the load-bearing ones: outside an instance nothing
 * is locked, and this rule knows nothing about a *node's* fields, which stay
 * editable in a mount because that is exactly what an override is.
 */
describe('a document-level box inside an instance', () => {
  it('is locked, with a reason, while a mount is displayed', () => {
    const scope = documentSettingScope({ root: 'delegate-by-mount', mountPath: ['mount-sql'] });
    expect(scope.locked).toBe(true);
    expect(scope.reason).toBe(DOCUMENT_LOCKED_IN_INSTANCE);
  });

  it('is not locked in a document, which is where these settings live', () => {
    expect(documentSettingScope({ root: 'delegate-by-mount', mountPath: [] })).toEqual({
      locked: false,
    });
  });

  it('is not locked before any workflow has been opened', () => {
    expect(documentSettingScope(null)).toEqual({ locked: false });
  });

  it('is locked at any depth, because every level below the root is an instance', () => {
    expect(documentSettingScope({ root: 'nested', mountPath: ['mount-a', 'mount-b'] }).locked).toBe(
      true,
    );
  });
});

/**
 * The copy, pinned — it is the whole fix. A disabled box with no sentence is
 * a second silent refusal.
 */
describe('what the locked boxes say', () => {
  it('names where the setting does live, and does not merely say no', () => {
    expect(DOCUMENT_LOCKED_IN_INSTANCE).toMatch(/package/i);
    expect(DOCUMENT_LOCKED_IN_INSTANCE).toMatch(/every mount/i);
  });

  it('does not print a slug, which is a name the reader never chose', () => {
    expect(DOCUMENT_LOCKED_IN_INSTANCE).not.toMatch(/slug/i);
    expect(DOCUMENT_LOCKED_IN_INSTANCE).not.toMatch(/delegate-by-mount|<slug>/);
  });

  it('keeps the lexicon: instance and mount, never "subworkflow" or "child"', () => {
    expect(DOCUMENT_LOCKED_IN_INSTANCE).not.toMatch(/subworkflow|sub-workflow|child workflow/i);
  });

  it('is a different sentence from the step budget hint it replaces', () => {
    expect(DOCUMENT_LOCKED_IN_INSTANCE).not.toBe(STEP_BUDGET_HINT);
  });
});

/**
 * The wiring, asserted at the only layer available.
 *
 * The rule above would stay green against an `Inspector.tsx` that computed it
 * and then rendered both boxes enabled anyway — which is precisely the bug 70
 * reports, so a test that cannot see the `disabled` attribute is a test of
 * itself. vitest runs `environment: 'node'` with no jsdom, so there is no
 * render to assert on and this reads the component's source instead.
 *
 * `6a8154f` is the commit that paid for asserting on bytes a formatter can
 * move, so nothing here depends on line breaks or indentation: the source is
 * collapsed to single spaces first, and every needle is a JSX attribute or an
 * identifier, which Prettier has nowhere to put but where it is.
 */
describe('the Document section actually applies the rule', () => {
  const source = readFileSync(
    new URL('../inspector/Inspector.tsx', import.meta.url),
    'utf8',
  ).replace(/\s+/g, ' ');

  it('reads the rule from this module rather than deciding for itself', () => {
    expect(source).toContain("from '@view/workflow/documentSettingScope'");
    expect(source).toContain('documentSettingScope(getOpenAddress())');
  });

  it('hands the lock to both document boxes', () => {
    expect(source).toContain(
      '<WorkflowNameInput name={workbench.model.name} locked={documents.locked} />',
    );
    expect(source).toContain(
      '<StepBudgetInput settings={workbench.model.settings} locked={documents.locked} />',
    );
  });

  it('disables the input in each of them, which is the fix itself', () => {
    for (const component of ['function WorkflowNameInput', 'function StepBudgetInput']) {
      const start = source.indexOf(component);
      expect(start, `${component} is gone`).toBeGreaterThan(-1);
      const body = source.slice(start, start + 900);
      expect(body, `${component} no longer disables its input`).toContain('disabled={locked}');
    }
  });

  it('shows the reason, so a greyed box is not a second silent refusal', () => {
    expect(source).toContain('{documents.reason}');
  });
});
