import { describe, expect, it } from 'vitest';
import { composerPlaceholder, GENERIC_COMPOSER_PLACEHOLDER } from './composerPlaceholder';

/**
 * The chat box suggested a question this workflow cannot answer
 * (`every-workflow-green` 04).
 *
 * `AskPanel` hardcoded `"Which genre earned the most revenue?"` — a Chinook
 * question — as the composer's placeholder on **every** workflow. Found while
 * walking `workflow-2026`, which lists repository contents and has never heard
 * of a genre.
 *
 * A placeholder is an example of what to type here. One that belongs to a
 * different workflow teaches the wrong thing about the workflow in front of
 * you, and it is worse than none: a reader who types it gets a refusal from a
 * graph that was never asked a fair question.
 *
 * The workflow already states its own example. `entryQuestion(model)` reads the
 * `input.text` node's `prompt`, on the owner's settled rule that **the Input
 * node's text field IS the question** — the same source the Run button uses to
 * decide what pressing it would ask. One source, two surfaces.
 */
describe('the composer placeholder', () => {
  it('offers the workflow’s own entry question', () => {
    expect(composerPlaceholder('show me the repo list')).toBe('show me the repo list');
  });

  it('falls back when the workflow states no question', () => {
    // A blank Input node is legitimate — a workflow whose question always
    // comes from the chat. It gets a prompt that belongs to no workflow in
    // particular rather than to somebody else's.
    expect(composerPlaceholder('')).toBe(GENERIC_COMPOSER_PLACEHOLDER);
    expect(composerPlaceholder('   ')).toBe(GENERIC_COMPOSER_PLACEHOLDER);
  });

  it('never suggests a question from another workflow', () => {
    // The literal that shipped. Named here so re-introducing it is a red test
    // rather than a thing somebody notices in a screenshot months later.
    expect(GENERIC_COMPOSER_PLACEHOLDER).not.toMatch(/genre|revenue/i);
    expect(composerPlaceholder('')).not.toMatch(/genre|revenue/i);
  });

  it('collapses a multi-line entry question onto one line', () => {
    // Two `input.text` nodes join with a blank line (`entryQuestion`), and a
    // placeholder is one line of a single-line control.
    expect(composerPlaceholder('first line\n\nsecond line')).toBe('first line second line');
  });

  it('trims a very long question rather than overflowing the control', () => {
    const long = 'x'.repeat(200);
    const out = composerPlaceholder(long);
    expect(out.length).toBeLessThanOrEqual(80);
    expect(out.endsWith('…')).toBe(true);
  });
});
