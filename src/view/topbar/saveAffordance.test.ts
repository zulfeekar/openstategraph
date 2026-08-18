import { describe, expect, it } from 'vitest';
import { parseMountAddress } from '@core/model/MountAddress';
import { saveAffordance } from './saveAffordance';

/**
 * `say-it-on-the-surface` 01 — the toolbar's Save says which of the three acts
 * it is about to perform.
 *
 * The defect was never only that Save was hard to find. Autosave is
 * browser-local, so "somewhere" and "on disk" are different facts and nothing
 * on screen distinguished them; and `saveWorkflow` writes the **parent** when
 * an instance is open, so a button that said a flat "Save" would have been
 * making a promise it does not keep. These pin the three sentences.
 */
describe('saveAffordance', () => {
  it('marks a document that has no folder on the backend yet', () => {
    const save = saveAffordance(null, null);
    expect(save.unsaved).toBe(true);
    expect(save.label).toBe('Save');
    // The half a user cannot otherwise discover: autosave is this browser only.
    expect(save.hint).toContain('this browser only');
    expect(save.hint).toContain('workflows/<slug>/');
  });

  it('names the folder it will overwrite once a slug is held', () => {
    const save = saveAffordance(null, 'chinook-assistant');
    expect(save.unsaved).toBe(false);
    expect(save.hint).toContain('workflows/chinook-assistant/');
  });

  it('never says a plain "Save" while an instance is open', () => {
    // The bytes go to the parent as overrides. A button reading "Save" here
    // would claim it wrote the document on screen, which is the exact
    // scope-confusion `production-ready` 17 is about.
    const address = parseMountAddress('concierge/wf-architect');
    expect(address).not.toBeNull();
    const save = saveAffordance(address, 'concierge');
    expect(save.label).toBe('Save mount');
    expect(save.hint).toContain('overrides on concierge');
    expect(save.hint).toContain('the mounted package itself is not changed');
    // Not "unsaved": the parent exists, so there is nothing to warn about.
    expect(save.unsaved).toBe(false);
  });
});
