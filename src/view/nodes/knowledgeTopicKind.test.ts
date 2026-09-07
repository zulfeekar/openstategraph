import { describe, expect, it } from 'vitest';
import { topicKind } from './knowledgeTopicKind';

/**
 * The Done-when, as three assertions: a reader can tell, without opening a
 * file, which topics route, which explain, and which a human owns (ticket 13).
 */
describe('topicKind', () => {
  it('calls a hand-claimed doc yours, and says what that promises', () => {
    const kind = topicKind({ generated: false, source: '' });

    expect(kind.label).toBe('yours');
    expect(kind.title).toContain('No builder will overwrite it');
  });

  it('calls a workflow pointer a route', () => {
    for (const source of ['root', 'project']) {
      expect(topicKind({ generated: true, source }).label).toBe('routes');
    }
  });

  it('calls a subject topic an explanation', () => {
    for (const source of ['sql', 'explorer', 'codebase']) {
      expect(topicKind({ generated: true, source }).label).toBe('explains');
    }
  });

  it('keeps the marker vocabulary in the tooltip rather than losing it', () => {
    // "Do not invent new source names in the UI" — the badge answers the
    // question, the hover names the builder that answered it.
    expect(topicKind({ generated: true, source: 'explorer' }).title).toContain('"explorer"');
  });

  it('shows an unknown builder as itself instead of guessing', () => {
    // A source this list has not heard of is a *new builder*, not a concept
    // topic. Falling through as its own name is honest; picking one of the
    // three words for it would be a stale list telling a confident lie.
    expect(topicKind({ generated: true, source: 'newthing' }).label).toBe('newthing');
  });

  it('has something to say about a legacy marker with no source', () => {
    const kind = topicKind({ generated: true, source: '' });

    expect(kind.label).toBe('generated');
    expect(kind.title).toContain('did not record which');
  });
});
