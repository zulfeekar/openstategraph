import { describe, expect, it } from 'vitest';
import { applicableSuggestion, type EditorFacts } from './suggestion';

/**
 * The fence-parsing half of these tests moved to the backend with the
 * boundary — `backend/tests/test_audience_boundary.py` proves over the real
 * `/api/runs/stream` that a suggestion never rides the answer text for any
 * audience. What is left here is the half only the browser can answer: is
 * this suggestion applicable to the canvas that is actually open?
 */

const facts: EditorFacts = {
  nodeTypes: new Set(['tool.web-search', 'tool.web-fetch']),
  nodeIds: new Set(['agent-analyst', 'input-1']),
};

const valid = {
  nodeType: 'tool.web-search',
  attachTo: 'agent-analyst',
  port: 'tools',
  label: 'Web Search',
  reason: 'This workflow has no web access.',
};

describe('applicableSuggestion', () => {
  it('is null when the run carried no developer channel at all', () => {
    // The customer case — and the one this must never mistake for "an empty
    // suggestion", because the run was not entitled to one.
    expect(applicableSuggestion(null, facts)).toBeNull();
    expect(applicableSuggestion(undefined, facts)).toBeNull();
  });

  it('reads a well-formed suggestion', () => {
    expect(applicableSuggestion(valid, facts)).toEqual(valid);
  });

  it('defaults the port to the agent tool bus', () => {
    const suggestion = applicableSuggestion(
      { nodeType: 'tool.web-search', attachTo: 'agent-analyst' },
      facts,
    );
    expect(suggestion?.port).toBe('tools');
  });

  it('rejects a node type this editor does not know', () => {
    const suggestion = applicableSuggestion(
      { nodeType: 'tool.telepathy', attachTo: 'agent-analyst' },
      facts,
    );
    expect(suggestion).toBeNull();
  });

  it('rejects an attachTo that is not in the document', () => {
    const suggestion = applicableSuggestion(
      { nodeType: 'tool.web-search', attachTo: 'agent-ghost' },
      facts,
    );
    expect(suggestion).toBeNull();
  });

  it('rejects non-string fields rather than coercing them', () => {
    // A model that answers with a number where a node type belongs has not
    // named a node type, and pretending otherwise offers a button that fails.
    expect(applicableSuggestion({ nodeType: 42, attachTo: 'agent-analyst' }, facts)).toBeNull();
  });

  it('rejects an array — a suggestion is one object', () => {
    expect(applicableSuggestion([] as unknown as Record<string, unknown>, facts)).toBeNull();
  });
});
