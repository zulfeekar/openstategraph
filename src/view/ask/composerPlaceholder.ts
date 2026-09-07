/**
 * What the chat box suggests you type, and why it is not a fixed sentence.
 *
 * `AskPanel` hardcoded *"Which genre earned the most revenue?"* — a Chinook
 * question — on **every** workflow (`every-workflow-green` 04). Found while
 * walking `workflow-2026`, which lists repository contents and has never heard
 * of a genre.
 *
 * A placeholder is an *example of what to type here*. One borrowed from another
 * workflow teaches the wrong thing about the graph in front of you, and it is
 * worse than none: somebody who types it gets a refusal from a workflow that
 * was never asked a fair question.
 *
 * The workflow already states its own example, and this reads it from the one
 * place that owns it: `entryQuestion(model)`, on the settled rule that **the
 * Input node's text field IS the question** — the same source the Run button
 * uses to decide what pressing it would ask. One source, two surfaces, no
 * second sentence to drift.
 */

/** When the workflow states no question of its own. Belongs to no workflow. */
export const GENERIC_COMPOSER_PLACEHOLDER = 'Ask this workflow a question';

/** A single-line control; a long entry question is shown as much as fits. */
const MAX = 80;

export function composerPlaceholder(entryQuestion: string): string {
  // One line: two `input.text` nodes join with a blank line, and this control
  // has one row.
  const oneLine = entryQuestion.replace(/\s+/g, ' ').trim();
  if (!oneLine) return GENERIC_COMPOSER_PLACEHOLDER;
  return oneLine.length <= MAX ? oneLine : `${oneLine.slice(0, MAX - 1).trimEnd()}…`;
}
