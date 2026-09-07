import { describe, expect, it } from 'vitest';
import { allNodeDefinitions } from './portSpecs';
import type { FieldSchema } from '@core/model/contracts/fields';

/**
 * Every field in the catalogue whose content is **prose**, and the box it gets.
 *
 * Ticket 26, owner verbatim: *"in Atomic nodes I would like free fields like
 * paragraph — supported fields should be scalable and multiple lines; for
 * example the guardrail is completely messed up."*
 *
 * The list is written out rather than inferred, because "is this prose?" is a
 * judgement about the *content* and no property of the schema can answer it —
 * a routing branch name and a routing rule are both strings. Writing it down
 * is what makes the sweep reviewable and what makes a regression visible: a
 * new field on this list that ships as `text` fails here rather than reaching
 * someone's card as a one-line slot.
 *
 * Deliberately **not** exhaustive over the catalogue. A field absent from this
 * list is a field nobody has claimed is prose, which is the honest default —
 * `subreddit`, `to`, `segment` and the branch identifiers are all short values
 * that would be worse in a growing box.
 */
const PROSE: ReadonlyArray<readonly [type: string, key: string]> = [
  ['input.text', 'prompt'],
  ['input.markdown', 'instruction'],
  ['input.skill', 'skillDescription'],
  ['input.skill', 'instruction'],
  ['agent.llm', 'systemPrompt'],
  ['agent.llm', 'rubric'],
  ['route.classifier', 'rules'],
  ['route.grader', 'criteria'],
  ['route.grader', 'criterion'],
  ['human.approval', 'message'],
  ['guard.policy', 'blockedMessage'],
  ['guard.policy', 'detector'],
  ['orchestrate.supervisor', 'rules'],
  ['orchestrate.worker', 'role'],
  ['workflow.subgraph', 'outcome'],
  ['workflow.subgraph', 'overrides'],
  ['annotate.note', 'body'],
  ['annotate.group', 'notes'],
];

/** Every field a definition declares, including the ones inside a row. */
function fieldsOf(fields: readonly FieldSchema[]): FieldSchema[] {
  return fields.flatMap((field) =>
    field.kind === 'repeatable-group' ? [field, ...fieldsOf(field.fields)] : [field],
  );
}

describe('a paragraph is declared as a paragraph', () => {
  const catalogue = new Map(
    allNodeDefinitions().map((definition) => [definition.id, fieldsOf(definition.fields ?? [])]),
  );

  it.each(PROSE)('%s.%s grows with what is written in it', (type, key) => {
    const field = catalogue.get(type)?.find((candidate) => candidate.key === key);
    expect(field, `${type} has no field ${key}`).toBeDefined();
    // One kind, not two. `textarea` *is* the paragraph kind — see
    // `TextAreaFieldSchema`, which records why a second `paragraph` kind
    // beside it would have been one piece of knowledge with two names.
    expect(field?.kind).toBe('textarea');
  });

  it('gives every paragraph a ceiling it declared itself', () => {
    // The bounds used to be a flat `max-height: 180px` in the card's
    // stylesheet — a number that gave a system prompt and a two-word note the
    // same nine lines, and that no schema could see or change.
    const unbounded = PROSE.filter(([type, key]) => {
      const field = catalogue.get(type)?.find((candidate) => candidate.key === key);
      return field?.kind === 'textarea' && field.maxRows === undefined;
    });
    expect(unbounded).toEqual([]);
  });

  it('keeps a short value out of a paragraph box', () => {
    // The other half of the sweep, and the reason it is a list rather than a
    // rule: a growing box for a slug or a subreddit is the same mistake in the
    // other direction.
    const short = [
      ['route.classifier', 'fallback'],
      ['annotate.group', 'title'],
      ['input.skill', 'skillName'],
    ] as const;
    for (const [type, key] of short) {
      const field = catalogue.get(type)?.find((candidate) => candidate.key === key);
      expect(field?.kind, `${type}.${key}`).not.toBe('textarea');
    }
  });
});
