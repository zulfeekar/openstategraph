import { describe, expect, it } from 'vitest';
import type { ICompositionTerm } from './compositionVocabulary';
import { compositionPurpose, formatComposition, summarizeComposition } from './compositionSummary';

/**
 * A vocabulary local to this file, because `core/` must not know the
 * catalogue's words (reviews-2026-08-14 ticket 13).
 *
 * The assertions that read a real `workflows/<slug>/workflow.json` and expect
 * "3 agents · 1 router · 1 grader · 5 tools" moved with the words themselves,
 * to `src/nodes/censusTerms.test.ts`. They were always testing the vocabulary
 * rather than the census, and having them here is what made the table look
 * like it belonged in `core/`.
 */
const VOCABULARY: readonly ICompositionTerm[] = [
  { id: 'agent.', group: 'actor', one: 'agent', many: 'agents' },
  { id: 'route.grader', group: 'control', one: 'grader', many: 'graders', revisePort: 'revise' },
  { id: 'workflow.subgraph', group: 'held', one: 'workflow', many: 'workflows' },
  { id: 'input.', group: 'boundary', one: 'input', many: 'inputs' },
  { id: 'output.', group: 'boundary', one: 'output', many: 'outputs' },
  { id: 'annotate.', group: 'ignored', one: 'annotation', many: 'annotations' },
];

/** Every call in this file counts in the same words. */
const census = (document: unknown, claimsOutcome?: boolean) =>
  summarizeComposition(document, {
    vocabulary: VOCABULARY,
    ...(claimsOutcome ? { claimsOutcome } : {}),
  });

describe('summarizeComposition', () => {
  it('accepts a bare document as well as a saved envelope', () => {
    const document = { nodes: [{ id: 'a', type: 'agent.llm' }] };

    expect(census({ version: 3, name: 'x', document })).toEqual(census(document));
  });

  it('counts a loop where the child earns one', () => {
    const document = {
      nodes: [
        { id: 'a', type: 'agent.llm' },
        { id: 'g', type: 'route.grader' },
      ],
      edges: [{ source: { nodeId: 'g', portId: 'revise' }, target: { nodeId: 'a', portId: 'f' } }],
    };

    expect(census(document)?.note).toBe('loops until its grader passes');
  });

  it('claims no loop when the grader has no revise edge, and says why', () => {
    // This asserted `{ parts }` with **no note at all** — the behaviour ticket
    // 03 calls the defect. A Team card shows an `Expected outcome` the user
    // wrote; saying nothing beside it reads as agreement. The counts are
    // unchanged; what was silence is now a sentence.
    const document = {
      nodes: [
        { id: 'a', type: 'agent.llm' },
        { id: 'g', type: 'route.grader' },
      ],
      edges: [{ source: { nodeId: 'g', portId: 'pass' }, target: { nodeId: 'o', portId: 'x' } }],
    };
    expect(census(document, true)).toEqual({
      parts: [
        { label: 'agent', count: 1 },
        { label: 'grader', count: 1 },
      ],
      note: 'its grader never revises — nothing sends a weak answer back',
    });
  });

  it('omits inputs and outputs — they are the mount’s own ports', () => {
    const document = {
      nodes: [
        { id: 'i', type: 'input.text' },
        { id: 'o', type: 'output.formatted' },
        { id: 'a', type: 'agent.llm' },
      ],
    };
    expect(formatComposition(census(document)!)).toBe('1 agent');
  });

  it('counts nested mounts as content', () => {
    const document = {
      nodes: [
        { id: 'w', type: 'workflow.subgraph' },
        { id: 'w2', type: 'workflow.subgraph' },
        { id: 'w3', type: 'workflow.subgraph' },
      ],
    };
    // Was `1 team · 2 workflows`. `team.workflow` left the vocabulary with the
    // node type; a child document still carrying the old id has been migrated
    // by `normalize_document` before any card sees it.
    expect(formatComposition(census(document)!)).toBe('3 workflows');
  });

  it('returns null for anything without countable content', () => {
    expect(census(null)).toBeNull();
    expect(census({ nodes: [] })).toBeNull();
    expect(census({ nodes: [{ id: 'n', type: 'annotate.note' }] })).toBeNull();
    expect(census('not a document')).toBeNull();
  });
});

describe('compositionPurpose', () => {
  it('reads the package’s own one-line purpose', () => {
    expect(
      compositionPurpose({
        nodes: [],
        settings: { purpose: 'Answers questions about the Chinook database in SQL.' },
      }),
    ).toBe('Answers questions about the Chinook database in SQL.');
  });

  it('is empty when the package never wrote one — no invented summary', () => {
    // A derived sentence would have to guess, and a mount card that
    // confidently mis-describes the thing it runs is worse than a quiet one.
    expect(compositionPurpose({ nodes: [] })).toBe('');
    expect(compositionPurpose({ nodes: [], settings: { purpose: '   ' } })).toBe('');
    expect(compositionPurpose({ nodes: [], settings: { purpose: 42 } })).toBe('');
  });

  it('never throws on a malformed payload — this runs inside a card render', () => {
    expect(compositionPurpose(null)).toBe('');
    expect(compositionPurpose('nonsense')).toBe('');
    expect(compositionPurpose({ settings: null })).toBe('');
  });

  it('caps a purpose that was written as a paragraph', () => {
    const long = `${'word '.repeat(60)}end.`;
    expect(compositionPurpose({ settings: { purpose: long } }).length).toBeLessThanOrEqual(160);
  });
});

/**
 * production-ready ticket 03.
 *
 * A Team's card carries an `Expected outcome` the user wrote, and the value
 * never reaches the compiler — `_subgraph` reads only `workflow` and
 * `overrides`. Worse, a document with **no grader at all** can be mounted as a
 * Team: it still says Team, still runs, and still displays an outcome nobody
 * checks.
 *
 * The census already knew. `loops` is computed here, and a child that does not
 * loop was expressed as the *absence* of a note — silence, which is the same
 * shape as the defect. Absence of a claim is not a claim of absence, and on a
 * card nobody reads the gap.
 */
describe('a mount whose child cannot enforce its outcome says so', () => {
  const graderless = {
    nodes: [
      { id: 'in1', type: 'input.text' },
      { id: 'a1', type: 'agent.llm' },
      { id: 'out1', type: 'output.formatted' },
    ],
    edges: [
      { source: { nodeId: 'in1', portId: 'text' }, target: { nodeId: 'a1', portId: 'prompt' } },
      { source: { nodeId: 'a1', portId: 'result' }, target: { nodeId: 'out1', portId: 'result' } },
    ],
  };

  /** A grader that exists but never routes `revise` back — no loop closes. */
  const openLoop = {
    nodes: [
      { id: 'in1', type: 'input.text' },
      { id: 'a1', type: 'agent.llm' },
      { id: 'g1', type: 'route.grader' },
      { id: 'out1', type: 'output.formatted' },
    ],
    edges: [
      { source: { nodeId: 'in1', portId: 'text' }, target: { nodeId: 'a1', portId: 'prompt' } },
      { source: { nodeId: 'a1', portId: 'result' }, target: { nodeId: 'g1', portId: 'candidate' } },
      { source: { nodeId: 'g1', portId: 'pass' }, target: { nodeId: 'out1', portId: 'result' } },
    ],
  };

  it('states the gap rather than omitting the loop note', () => {
    const summary = census(graderless, true);
    expect(summary?.note).toBeDefined();
    expect(formatComposition(summary!)).toMatch(/no grader|nothing checks/i);
  });

  it('counts a grader that never revises as not closing the loop', () => {
    // The grader is present, so "no grader" would be wrong; what is missing is
    // the `revise` edge that makes it a loop.
    const summary = census(openLoop, true);
    expect(summary?.note).toBeDefined();
    expect(formatComposition(summary!)).not.toContain('loops until');
  });

  it('still says nothing of the sort for a plain subgraph mount', () => {
    // Only a Team promises an outcome, so only a Team can fail to keep one.
    // A `workflow.subgraph` mount never claimed a loop in the first place.
    expect(census(graderless)?.note).toBeUndefined();
  });
});
