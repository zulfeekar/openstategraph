import { describe, expect, it } from 'vitest';
import { knowledgeBindingNote } from './knowledgeBindingCopy';

/**
 * The claim under test is not the prose, it is the *promise*: whatever the card
 * says, a user must be able to tell from it whether deleting the node changes
 * anything — and the answer must be the true one (ticket 09).
 */
describe('the Knowledge card explains its own effect', () => {
  it('says the binding is automatic once there are topics', () => {
    const note = knowledgeBindingNote(3);

    expect(note).toContain('3 topics');
    expect(note).toContain('automatic');
    // The question a user actually has, answered in the card rather than in
    // `prebuilt_knowledge.py`.
    expect(note).toContain('Removing this card does not unbind it');
  });

  it('counts one topic in the singular', () => {
    expect(knowledgeBindingNote(1)).toContain('1 topic —');
  });

  it('says the opposite when there is nothing to look up', () => {
    // With an empty `knowledge/`, `ambient_knowledge_tool` returns None: no
    // agent has the tool, and the card claiming otherwise would be the same
    // defect pointing the other way.
    const note = knowledgeBindingNote(0);

    expect(note).toContain('Nothing to look up yet');
    expect(note).toContain('not what binds it');
  });

  it('does not claim the folder is empty when it could not look', () => {
    // An unsaved draft has no slug, so the card cannot fetch topics. It showed
    // "Nothing to look up yet" for a package with twelve topics on disk —
    // found in the browser, and the same untruth pointing the other way.
    const note = knowledgeBindingNote(null);

    expect(note).toContain('Save this workflow to a folder first');
    expect(note).not.toContain('Nothing to look up');
  });

  it('never implies the card itself is the wiring', () => {
    for (const count of [null, 0, 1, 7]) {
      const note = knowledgeBindingNote(count);
      expect(note).not.toMatch(/connect|wire (it|this) up|attach this/i);
    }
  });
});
