import { describe, expect, it } from 'vitest';
import { publishAffordance } from './publishAffordance';
import type { MountAddress } from '@core/model/MountAddress';

/**
 * `ship-it` 39 — *publish exists and cannot be found from where the work
 * happens*.
 *
 * The finding was never that publishing was broken. It works, and has since
 * launch-readiness 04. It lives in a panel a developer opens once, while
 * `published` is the single most consequential state a workflow has: it is
 * what puts a package in front of **customers**. So the target of these tests
 * is a developer on the canvas knowing, without hunting, whether what they are
 * editing is live — and not shipping something other than what is on screen.
 *
 * Pure and DOM-free for the reason `saveAffordance`'s tests are: vitest runs
 * `environment: 'node'` here, and copy that matters is copy worth a test.
 */
describe('publishAffordance', () => {
  const saved = (published: boolean | null, unsavedWork = false) =>
    publishAffordance({ address: null, slug: 'billing', published, unsavedWork });

  it('says Draft, and offers Publish, for a saved workflow customers cannot see', () => {
    const it_ = saved(false);
    expect(it_.status).toBe('draft');
    expect(it_.label).toBe('Draft');
    expect(it_.action).toBe('publish');
    expect(it_.actionLabel).toBe('Publish');
  });

  it('says Published, and offers Unpublish, for one they can', () => {
    const it_ = saved(true);
    expect(it_.status).toBe('published');
    expect(it_.label).toBe('Published');
    expect(it_.action).toBe('unpublish');
    expect(it_.actionLabel).toBe('Unpublish');
  });

  /**
   * The inverse that is load-bearing. Everything else here is a positive
   * assertion, and a mistake that made the control read "Published"
   * unconditionally would pass every one of them.
   */
  it('never lets an unpublished workflow read as published', () => {
    for (const state of [false, null] as const) {
      const it_ = saved(state);
      expect(it_.label).not.toBe('Published');
      expect(it_.status).not.toBe('published');
      expect(it_.action).not.toBe('unpublish');
    }
  });

  it('shows nothing at all until the runtime has said which it is', () => {
    // Not a guess and not a default. A control that reads "Draft" while the
    // backend is unreachable is inviting a Publish that goes nowhere, and a
    // control that reads "Published" is worse.
    const unknown = saved(null);
    expect(unknown.status).toBe('unknown');
    expect(unknown.label).toBeNull();
    expect(unknown.action).toBeNull();
  });

  it('marks a never-saved canvas a draft with nothing to publish, and says why', () => {
    const fresh = publishAffordance({
      address: null,
      slug: null,
      published: null,
      unsavedWork: false,
    });
    expect(fresh.status).toBe('unsaved');
    expect(fresh.label).toBe('Draft');
    expect(fresh.action).toBeNull();
    // The one thing that unblocks it is named, because the state is otherwise
    // indistinguishable from a saved draft that simply refuses to publish.
    expect(fresh.hint).toContain('Save');
  });

  it('says nothing while a mount instance is open — this is not its lifecycle', () => {
    // Editing a mount edits the *parent's* overrides (`saveAffordance` says
    // so in the same toolbar), so a Publish here would be about a third
    // document. `workflowCatalogue` already records the rule: a surface that
    // prints a lifecycle badge it cannot change invites a click that goes
    // nowhere.
    const drilled = publishAffordance({
      address: { root: 'concierge', mountPath: ['wf-music'] } satisfies MountAddress,
      slug: 'concierge',
      published: true,
      unsavedWork: false,
    });
    expect(drilled.status).toBe('instance');
    expect(drilled.label).toBeNull();
    expect(drilled.action).toBeNull();
  });

  it('treats a class address exactly as a bare slug — that is the package itself', () => {
    const asClass = publishAffordance({
      address: { root: 'billing', mountPath: [] } satisfies MountAddress,
      slug: 'billing',
      published: true,
      unsavedWork: false,
    });
    expect(asClass.status).toBe('published');
    expect(asClass.action).toBe('unpublish');
  });

  describe('the save/publish relationship, said out loud rather than implied', () => {
    /**
     * The half of the ticket that is not a badge. `POST /api/workflows/{slug}/publish`
     * flips one key in the envelope on disk and reads no document — measured,
     * `workflow_store.set_published`. So publishing a slug whose canvas holds
     * unsaved edits ships the **saved** version, quietly.
     *
     * Publishing does not save. It must not: for a mount instance Save writes
     * the *parent*, so a publish-implies-save would write a different package
     * than the one being published — and nothing on this path may write a
     * document at all. What replaces the implication is saying it.
     */
    it('names the saved package as what goes live, in both directions', () => {
      for (const published of [false, true]) {
        expect(saved(published).hint).toContain('workflows/billing/');
      }
    });

    it('asks before publishing a canvas that differs from the file', () => {
      const dirty = saved(false, true);
      expect(dirty.action).toBe('publish');
      expect(dirty.confirmation).not.toBeNull();
      expect(dirty.confirmation).toContain('billing');
      // The whole point of the sentence: what customers get is not this screen.
      expect(dirty.confirmation).toContain('not as it is on screen');
    });

    it('asks nothing when the file and the canvas agree', () => {
      expect(saved(false).confirmation).toBeNull();
      expect(saved(true).confirmation).toBeNull();
    });

    it('asks nothing before an unpublish, however dirty the canvas is', () => {
      // Taking a workflow away from customers does not depend on which
      // version is on disk, so a confirm here would be friction with no fact
      // in it. The toast still says nothing was deleted.
      expect(saved(true, true).confirmation).toBeNull();
    });
  });

  describe('the words a customer would recognise', () => {
    it('describes the effect in the customer’s terms, never the API’s', () => {
      for (const published of [false, true]) {
        const hint = saved(published).hint;
        expect(hint).toContain('chat app');
        expect(hint).not.toContain('/api/');
        expect(hint).not.toContain('surface');
      }
    });

    it('says an unpublish deletes nothing, which is the question that verb raises', () => {
      expect(saved(true).actionHint).toContain('Nothing is deleted');
    });
  });
});
