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
    const summary = summarizeComposition(readWorkflow('chinook-assistant'), 'team');
    expect(summary).not.toBeNull();
    expect(formatComposition(summary!)).toBe(
      '3 agents · 1 router · 1 grader · 5 tools — loops until its grader passes',
    );
  });

  it('accepts a bare document as well as a saved envelope', () => {
    const envelope = readWorkflow('chinook-assistant') as { document: unknown };
    expect(summarizeComposition(envelope.document, 'team')).toEqual(
      summarizeComposition(envelope, 'team'),
    );
  });

  it('claims no loop for a subgraph mount, even one containing a grader', () => {
    const summary = summarizeComposition(readWorkflow('chinook-assistant'), 'subgraph');
    expect(summary?.note).toBeUndefined();
    expect(formatComposition(summary!)).not.toContain('loops');
  });

  it('claims no loop when the grader has no revise edge', () => {
    const document = {
      nodes: [
        { id: 'a', type: 'agent.llm' },
        { id: 'g', type: 'route.grader' },
      ],
      edges: [{ source: { nodeId: 'g', portId: 'pass' }, target: { nodeId: 'o', portId: 'x' } }],
    };
    expect(summarizeComposition(document, 'team')).toEqual({
      parts: [
        { label: 'agent', count: 1 },
        { label: 'grader', count: 1 },
      ],
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
    expect(formatComposition(summarizeComposition(document, 'subgraph')!)).toBe('1 agent');
  });

  it('counts nested mounts as content', () => {
    const document = {
      nodes: [
        { id: 't', type: 'team.workflow' },
        { id: 'w', type: 'workflow.subgraph' },
        { id: 'w2', type: 'workflow.subgraph' },
      ],
    };
    expect(formatComposition(summarizeComposition(document, 'subgraph')!)).toBe(
      '1 team · 2 workflows',
    );
  });

  it('returns null for anything without countable content', () => {
    expect(summarizeComposition(null, 'team')).toBeNull();
    expect(summarizeComposition({ nodes: [] }, 'team')).toBeNull();
    expect(
      summarizeComposition({ nodes: [{ id: 'n', type: 'annotate.note' }] }, 'team'),
    ).toBeNull();
    expect(summarizeComposition('not a document', 'subgraph')).toBeNull();
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
