import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { compositionPurpose, formatComposition, summarizeComposition } from './compositionSummary';

/** A real saved package, read from disk — a hand-written fixture would drift
 * from the document the card actually receives. `chinook-assistant` is the one
 * visible example: a router in front of three agents, the SQL tools and web
 * tools they hold between them, and the grader that closes the analyst's retry
 * loop. It is what the gateway mounts, so it is exactly the document a mount
 * card is handed. (It used to be the smaller `chinook-nl-to-sql`; ticket 10
 * collapsed the two, which is why the counted figures below changed.) */
const readWorkflow = (slug: string): unknown =>
  JSON.parse(
    readFileSync(
      fileURLToPath(new URL(`../../../workflows/${slug}/workflow.json`, import.meta.url)),
      'utf8',
    ),
  );

describe('summarizeComposition', () => {
  it('counts the real mounted example into the atomic vocabulary', () => {
    const summary = summarizeComposition(readWorkflow('chinook-assistant'));
    expect(summary).not.toBeNull();
    expect(formatComposition(summary!)).toBe(
      '3 agents · 1 router · 1 grader · 5 tools — loops until its grader passes',
    );
  });

  it('accepts a bare document as well as a saved envelope', () => {
    const envelope = readWorkflow('chinook-assistant') as { document: unknown };
    expect(summarizeComposition(envelope.document)).toEqual(summarizeComposition(envelope));
  });

  it('reports the loop it finds, whoever is mounting', () => {
    // This asserted the opposite: that a `subgraph`-kind mount never claims a
    // loop even when its child plainly has one, because only a Team was
    // allowed to say so. Since schema v3 there is one mount type (ticket 16),
    // and the claim is earned from the *document* rather than granted by the
    // card — so withholding it here would be hiding a true and useful fact.
    const summary = summarizeComposition(readWorkflow('chinook-assistant'));
    expect(summary?.note).toBe('loops until its grader passes');
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
    expect(summarizeComposition(document, { claimsOutcome: true })).toEqual({
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
    expect(formatComposition(summarizeComposition(document)!)).toBe('1 agent');
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
    expect(formatComposition(summarizeComposition(document)!)).toBe('3 workflows');
  });

  it('returns null for anything without countable content', () => {
    expect(summarizeComposition(null)).toBeNull();
    expect(summarizeComposition({ nodes: [] })).toBeNull();
    expect(summarizeComposition({ nodes: [{ id: 'n', type: 'annotate.note' }] })).toBeNull();
    expect(summarizeComposition('not a document')).toBeNull();
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
    const summary = summarizeComposition(graderless, { claimsOutcome: true });
    expect(summary?.note).toBeDefined();
    expect(formatComposition(summary!)).toMatch(/no grader|nothing checks/i);
  });

  it('counts a grader that never revises as not closing the loop', () => {
    // The grader is present, so "no grader" would be wrong; what is missing is
    // the `revise` edge that makes it a loop.
    const summary = summarizeComposition(openLoop, { claimsOutcome: true });
    expect(summary?.note).toBeDefined();
    expect(formatComposition(summary!)).not.toContain('loops until');
  });

  it('still says nothing of the sort for a plain subgraph mount', () => {
    // Only a Team promises an outcome, so only a Team can fail to keep one.
    // A `workflow.subgraph` mount never claimed a loop in the first place.
    expect(summarizeComposition(graderless)?.note).toBeUndefined();
  });

  it('leaves a real looping team exactly as it was', () => {
    const summary = summarizeComposition(readWorkflow('chinook-assistant'));
    expect(formatComposition(summary!)).toContain('loops until its grader passes');
  });
});
