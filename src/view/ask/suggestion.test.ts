import { describe, expect, it } from 'vitest';
import { parseSuggestion, type EditorFacts } from './suggestion';

const facts: EditorFacts = {
  nodeTypes: new Set(['tool.web-search', 'tool.web-fetch']),
  nodeIds: new Set(['agent-analyst', 'input-1']),
};

const fence = (body: string) => `Sorry, I cannot.\n\n\`\`\`suggestion\n${body}\n\`\`\`\n`;

const valid = JSON.stringify({
  nodeType: 'tool.web-search',
  attachTo: 'agent-analyst',
  port: 'tools',
  label: 'Web Search',
  reason: 'This workflow has no web access.',
});

describe('parseSuggestion', () => {
  it('returns the answer untouched when there is no fence', () => {
    const parsed = parseSuggestion('Rock earned the most.', facts);
    expect(parsed.suggestion).toBeNull();
    expect(parsed.text).toBe('Rock earned the most.');
  });

  it('reads a well-formed suggestion', () => {
    const parsed = parseSuggestion(fence(valid), facts);
    expect(parsed.suggestion).toEqual({
      nodeType: 'tool.web-search',
      attachTo: 'agent-analyst',
      port: 'tools',
      label: 'Web Search',
      reason: 'This workflow has no web access.',
    });
  });

  it('strips the fence from the rendered prose', () => {
    const parsed = parseSuggestion(fence(valid), facts);
    expect(parsed.text).toBe('Sorry, I cannot.');
  });

  it('defaults the port to the agent tool bus', () => {
    const parsed = parseSuggestion(
      fence(JSON.stringify({ nodeType: 'tool.web-search', attachTo: 'agent-analyst' })),
      facts,
    );
    expect(parsed.suggestion?.port).toBe('tools');
  });

  it('rejects a node type this editor does not know', () => {
    const parsed = parseSuggestion(
      fence(JSON.stringify({ nodeType: 'tool.telepathy', attachTo: 'agent-analyst' })),
      facts,
    );
    expect(parsed.suggestion).toBeNull();
  });

  it('rejects an attachTo that is not in the document', () => {
    const parsed = parseSuggestion(
      fence(JSON.stringify({ nodeType: 'tool.web-search', attachTo: 'agent-ghost' })),
      facts,
    );
    expect(parsed.suggestion).toBeNull();
  });

  it('leaves an unusable fence visible rather than swallowing it', () => {
    const answer = fence(JSON.stringify({ nodeType: 'tool.telepathy', attachTo: 'nope' }));
    expect(parseSuggestion(answer, facts).text).toBe(answer);
  });

  it('rejects malformed JSON without throwing', () => {
    const parsed = parseSuggestion(fence('{not json'), facts);
    expect(parsed.suggestion).toBeNull();
  });

  it('rejects a JSON array — a suggestion is one object', () => {
    const parsed = parseSuggestion(fence('[]'), facts);
    expect(parsed.suggestion).toBeNull();
  });

  it('honours only the first fence when a model emits several', () => {
    const second = JSON.stringify({ nodeType: 'tool.web-fetch', attachTo: 'agent-analyst' });
    const parsed = parseSuggestion(`${fence(valid)}\n${fence(second)}`, facts);
    expect(parsed.suggestion?.nodeType).toBe('tool.web-search');
  });
});
