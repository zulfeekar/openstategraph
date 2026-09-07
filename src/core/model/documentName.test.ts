import { describe, expect, it } from 'vitest';
import { UNNAMED_DOCUMENT, isUnnamedDocument } from './documentName';

/**
 * `say-it-on-the-surface/09` — the name a new document wears before it has one.
 *
 * The default was `AI Workflow` from the first commit of `Workbench`, and the
 * owner read it as a title: *"one has to save this workflow first, and then the
 * top bar 'AI Workflow' is misleading — a user would think it's saved."* Two
 * surfaces in one screen told opposite stories, because the mount card in the
 * same view refuses to open on the grounds that this workflow is not saved.
 *
 * The naming is load-bearing rather than cosmetic, and the reason is one file
 * away: `workflow_store.mint` slugifies the name at first save and **freezes
 * it**, because a slug that moves renames a directory. So the default decides
 * a folder name the user can never change — and `AI Workflow` mints
 * `ai-workflow` from three words nobody chose. That is `03`'s defect exactly:
 * a required identifier derived from something never introduced to the person
 * who has to live with it.
 */
describe('the name a document has before anybody names it', () => {
  it('does not read as a title a person typed', () => {
    // The whole defect in one assertion. `AI Workflow` is a plausible name for
    // a workflow about AI, which is what made it indistinguishable at a glance
    // from a saved document's name.
    expect(UNNAMED_DOCUMENT).toBe('Untitled');
  });

  it('is a name, not a state word', () => {
    // **Why `Untitled` and not `Unsaved`.** The top bar's document slot is a
    // *name* slot: it answers "which document is this". A state word there
    // answers a different question and abandons the first — two tabs holding
    // two drafts would both read `Unsaved`, and neither would say which is
    // which.
    //
    // The state is already carried, twice, by things that own it: the dot on
    // Save (`saveAffordance.marker === 'unsaved'`) means *no folder on the
    // backend*, and the `Draft` badge means *customers cannot see this*. A
    // third state word in the name slot would be the third signal this ticket
    // was told not to add. `Untitled` is orthogonal to both: it means *no name
    // yet*, which is the one fact neither of them carries and the one the next
    // save is about to freeze into a directory.
    expect(UNNAMED_DOCUMENT).not.toMatch(/saved|draft/i);
  });

  it('recognises the unnamed state regardless of surrounding space', () => {
    expect(isUnnamedDocument(UNNAMED_DOCUMENT)).toBe(true);
    expect(isUnnamedDocument('  Untitled  ')).toBe(true);
    expect(isUnnamedDocument('')).toBe(true);
    expect(isUnnamedDocument('   ')).toBe(true);
  });

  it('leaves a name somebody chose alone', () => {
    expect(isUnnamedDocument('Chinook Assistant')).toBe(false);
    // Including the one it used to ship with: a person who genuinely wants a
    // workflow called `AI Workflow` has named it, and nothing may treat that
    // as an absence.
    expect(isUnnamedDocument('AI Workflow')).toBe(false);
    expect(isUnnamedDocument('Untitled draft')).toBe(false);
  });
});
