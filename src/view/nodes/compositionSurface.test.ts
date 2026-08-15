import { describe, expect, it } from 'vitest';
import type { ICompositionTerm } from '@core/runtime/compositionVocabulary';
import { compositionSurface, type MountDocumentState } from './compositionSurface';

const VOCABULARY: readonly ICompositionTerm[] = [
  { id: 'agent.llm', group: 'actor', one: 'agent', many: 'agents' },
];

const READY: MountDocumentState = {
  status: 'ready',
  document: {
    nodes: [{ id: 'a', type: 'agent.llm' }],
    settings: { purpose: 'Answers questions about the catalogue.' },
  },
};

/**
 * Every state the fetch can land in, named. The Open verb is asserted against
 * all of them because the regression was exactly this: the verb lived inside
 * the census, and every state but one dropped the census.
 */
const EVERY_STATE: readonly MountDocumentState[] = [
  { status: 'loading' },
  READY,
  { status: 'ready', document: { nodes: [] } },
  { status: 'missing' },
  { status: 'unreachable' },
];

describe('compositionSurface', () => {
  it('offers the open verb in every state a configured mount can be in', () => {
    for (const state of EVERY_STATE) {
      const surface = compositionSurface({ slug: 'chinook-assistant', state });
      expect(surface, `state ${state.status}`).not.toBeNull();
      expect(surface?.open, `open verb missing while ${state.status}`).toBe(true);
    }
  });

  it('shows nothing at all until a package is named', () => {
    expect(compositionSurface({ slug: '', state: READY })).toBeNull();
    expect(compositionSurface({ slug: '   ', state: { status: 'missing' } })).toBeNull();
  });

  it('reads the census and the purpose from a resolved document', () => {
    const surface = compositionSurface({
      slug: 'chinook-assistant',
      state: READY,
      vocabulary: VOCABULARY,
    });
    expect(surface?.census).toBe('1 agent');
    expect(surface?.purpose).toBe('Answers questions about the catalogue.');
    expect(surface?.peekable).toBe(true);
    expect(surface?.note).toBeNull();
  });

  it('says why the census is absent rather than rendering nothing', () => {
    expect(compositionSurface({ slug: 'x', state: { status: 'loading' } })?.note).toBe(
      'reading x…',
    );
    expect(compositionSurface({ slug: 'x', state: { status: 'missing' } })?.note).toBe(
      'unknown workflow: x',
    );
    expect(compositionSurface({ slug: 'x', state: { status: 'unreachable' } })?.note).toBe(
      'could not reach the runtime to read x',
    );
    expect(
      compositionSurface({ slug: 'x', state: { status: 'ready', document: { nodes: [] } } })?.note,
    ).toBe('x is empty');
  });

  it('never offers a peek of a document it could not read', () => {
    for (const state of EVERY_STATE.filter((entry) => entry !== READY)) {
      expect(compositionSurface({ slug: 'x', state })?.peekable, state.status).toBe(false);
    }
  });

  it('counts this mount overrides from its own data, whatever the fetch did', () => {
    for (const state of EVERY_STATE) {
      const surface = compositionSurface({
        slug: 'x',
        state,
        overrides: '{"grader1": {"criteria": "- stricter"}, "agent1": {"model": "x"}}',
      });
      expect(surface?.overridden, state.status).toBe(2);
    }
  });

  it('stays silent about overrides it cannot parse', () => {
    expect(compositionSurface({ slug: 'x', state: READY, overrides: '{oops' })?.overridden).toBe(0);
    expect(compositionSurface({ slug: 'x', state: READY, overrides: '[1,2]' })?.overridden).toBe(0);
    expect(compositionSurface({ slug: 'x', state: READY })?.overridden).toBe(0);
  });

  it('earns the loop note from the child document rather than asserting it', () => {
    const looping = compositionSurface({
      slug: 'x',
      state: {
        status: 'ready',
        document: {
          nodes: [
            { id: 'g', type: 'route.grader' },
            { id: 'a', type: 'agent.llm' },
          ],
          edges: [{ source: { nodeId: 'g', portId: 'revise' } }],
        },
      },
      vocabulary: [
        ...VOCABULARY,
        {
          id: 'route.grader',
          group: 'control',
          one: 'grader',
          many: 'graders',
          revisePort: 'revise',
        },
      ],
    });
    expect(looping?.census).toContain('loops until its grader passes');
  });
});
