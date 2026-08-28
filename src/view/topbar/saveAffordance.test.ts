import { describe, expect, it } from 'vitest';
import { parseMountAddress } from '@core/model/MountAddress';
import { IN_TOUCH, type WatchReach } from '@app/workflowFileWatch';
import { saveAffordance } from './saveAffordance';

const blind: WatchReach = { consecutiveFailures: 3, blind: true };

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

/**
 * `say-it-on-the-surface/07` — the third thing Save has to be honest about.
 *
 * "Save to workflows/<slug>/ on the backend, overwriting what is there" is a
 * confident sentence about a folder nothing has been able to see for the last
 * three polls. The ticket asks that the affordance *reflect reality*; it
 * explicitly does not ask for Save to be taken away, because saving while the
 * backend is briefly unreachable is a normal thing a person does.
 */
describe('saveAffordance while the watch cannot reach the backend', () => {
  it('stops claiming to know what is in the folder', () => {
    const save = saveAffordance(null, 'chinook-assistant', blind);
    expect(save.unreachable).toBe(true);
    expect(save.hint).toContain('Cannot reach the backend');
    expect(save.hint).not.toContain('overwriting what is there');
    // It still names the folder — the address is not in doubt, only its state.
    expect(save.hint).toContain('workflows/chinook-assistant/');
  });

  it('does not take Save away', () => {
    // Not disabled on a guess: the word is unchanged, and a queued or retried
    // save is exactly what a person expects to still work through a blip.
    const save = saveAffordance(null, 'chinook-assistant', blind);
    expect(save.label).toBe('Save');
    expect(saveAffordance(null, null, blind).label).toBe('Save');
  });

  it('says it about a document with no folder too', () => {
    const save = saveAffordance(null, null, blind);
    expect(save.unsaved).toBe(true);
    expect(save.unreachable).toBe(true);
    expect(save.hint).toContain('Cannot reach the backend');
  });

  it('says nothing extra while the watch is in touch', () => {
    const save = saveAffordance(null, 'chinook-assistant', IN_TOUCH);
    expect(save.unreachable).toBe(false);
    expect(save.hint).not.toContain('Cannot reach');
  });

  it('marks at most one thing, and unreachable is the one nothing else says', () => {
    // The dot on Save already means "no folder yet". Two dots on one button
    // is a worse answer than one, so the marker is a single state and the
    // invisible fact wins — `unsaved` is also legible from the hint and from
    // an empty address bar.
    expect(saveAffordance(null, null, blind).marker).toBe('unreachable');
    expect(saveAffordance(null, null, IN_TOUCH).marker).toBe('unsaved');
    expect(saveAffordance(null, 'chinook-assistant', IN_TOUCH).marker).toBeNull();
  });
});
