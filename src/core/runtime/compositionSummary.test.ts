import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { formatComposition, summarizeComposition } from './compositionSummary';

/** The real saved team, read from disk — a hand-written fixture would drift
 * from the document the card actually receives. */
const readWorkflow = (slug: string): unknown =>
  JSON.parse(
    readFileSync(fileURLToPath(new URL(`../../../workflows/${slug}/workflow.json`, import.meta.url)), 'utf8'),
  );

describe('summarizeComposition', () => {
  it('counts the real page-metrics-team into the atomic vocabulary', () => {
    const summary = summarizeComposition(readWorkflow('page-metrics-team'), 'team');
    expect(summary).not.toBeNull();
    expect(formatComposition(summary!)).toBe(
      '1 supervisor · 1 worker · 1 grader · 1 function · 3 tools — loops until its grader passes',
    );
  });

  it('accepts a bare document as well as a saved envelope', () => {
    const envelope = readWorkflow('page-metrics-team') as { document: unknown };
    expect(summarizeComposition(envelope.document, 'team')).toEqual(
      summarizeComposition(envelope, 'team'),
    );
  });

  it('claims no loop for a subgraph mount, even one containing a grader', () => {
    const summary = summarizeComposition(readWorkflow('page-metrics-team'), 'subgraph');
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
    expect(summarizeComposition({ nodes: [{ id: 'n', type: 'annotate.note' }] }, 'team')).toBeNull();
    expect(summarizeComposition('not a document', 'subgraph')).toBeNull();
  });
});
