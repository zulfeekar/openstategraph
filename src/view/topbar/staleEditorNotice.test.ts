import { describe, expect, it } from 'vitest';
import { staleEditorNotice } from './staleEditorNotice';

/**
 * `the-cost-of-one-more/16`. The three states, and the one that is the point.
 */
describe('the stale-editor notice', () => {
  it('says so when the served bundle predates the source it was built from', () => {
    const notice = staleEditorNotice(true);

    expect(notice).not.toBeNull();
    expect(notice?.label).toBe('Editor is stale');
  });

  it('names the action, because a warning naming no action is one nobody acts on', () => {
    expect(staleEditorNotice(true)?.hint).toContain('npm run build');
  });

  /**
   * The editor's own sentence, not the backend's forwarded — `18`'s rule 1,
   * and `13`'s finding before it. It happens to be true here for free: only
   * the boolean is on the wire, and `STALE_EDITOR_WARNING` never leaves the
   * server. What this pins is that the sentence is addressed to somebody
   * looking at this editor rather than to an API caller.
   */
  it('speaks to the person looking at the page, not to an API caller', () => {
    const hint = staleEditorNotice(true)?.hint ?? '';

    expect(hint).toMatch(/reload/i);
    expect(hint).not.toMatch(/\/api\//);
    expect(hint).not.toMatch(/\bPOST\b|\bGET\b/);
  });

  it('says nothing at all when the bundle is current', () => {
    expect(staleEditorNotice(false)).toBeNull();
  });

  /**
   * **The third state, and the recurring defect it exists to refuse.**
   *
   * `null` is the backend's *cannot tell* — an installed wheel with no `src/`
   * beside it, or a fresh clone with no `dist/` built yet
   * (`editor_freshness.py`). It renders exactly what `false` renders, and
   * that is deliberate rather than a collapse of two states into one output:
   * neither renders the word **current**. This is a warning, not a readout —
   * it has no slot to leave a `—` in, and a permanent toolbar chip saying
   * "nothing to report" is noise. What `52`'s standard forbids is showing a
   * measurement that was never taken; saying nothing shows none.
   */
  it('says nothing when the server cannot tell, and never claims the bundle is current', () => {
    expect(staleEditorNotice(null)).toBeNull();

    // The claim that must not exist anywhere in this module's vocabulary:
    // there is no state in which this surface reports freshness.
    for (const state of [true, false, null] as const) {
      const notice = staleEditorNotice(state);
      expect(`${notice?.label ?? ''} ${notice?.hint ?? ''}`).not.toMatch(/\bcurrent\b|\bfresh\b/i);
    }
  });
});
