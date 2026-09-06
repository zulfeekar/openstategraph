import { describe, expect, it } from 'vitest';

import { DRAFT_NOTICE, showsDraft } from './draftNotice';

/** A turn with nothing happening, narrowed per case. */
const settled = { draft: '', running: false, answer: '', awaitingApproval: false };

describe('the mark on an unsettled reply', () => {
  it('says it is a draft and that it has not been checked', () => {
    // Both halves, because either alone is a different and weaker claim:
    // "Draft" alone does not say a check is coming, and "not checked yet"
    // alone does not say the text may be replaced.
    expect(DRAFT_NOTICE.toLowerCase()).toContain('draft');
    expect(DRAFT_NOTICE.toLowerCase()).toContain('not checked yet');
  });

  it('names no actor', () => {
    // `/chat` says "our reviewer" and the editor says "the grader"; a sentence
    // picking either would have to be written twice. See the module docstring.
    for (const word of ['grader', 'reviewer', 'agent', 'model']) {
      expect(DRAFT_NOTICE.toLowerCase()).not.toContain(word);
    }
  });

  it('is short enough to read without stopping', () => {
    expect(DRAFT_NOTICE.split(/\s+/)).toHaveLength(5);
  });
});

describe('when the mark is on screen', () => {
  it('is not, for a workflow that produced no draft text', () => {
    // The no-flicker property, and it is an emptiness rather than a rule: an
    // ungraded workflow's frames carry no flag, so nothing accumulates here,
    // so nothing appears and nothing vanishes on an ordinary answer.
    expect(showsDraft({ ...settled, running: true })).toBe(false);
  });

  it('is, while the reply it belongs to is still streaming', () => {
    expect(showsDraft({ ...settled, draft: 'total sales of $96,699.19', running: true })).toBe(
      true,
    );
  });

  it('is not, once a settled answer has taken its place', () => {
    // Replaced, not appended — the ticket's second "done when".
    expect(showsDraft({ ...settled, draft: 'total sales of $96,699.19', answer: '$826.65' })).toBe(
      false,
    );
  });

  it('survives a turn that settled without publishing anything', () => {
    // The draft is then all the reader has, and hiding it would leave a turn
    // showing no model output at all — `settledThinking`'s rule, and the same
    // reasoning applies to the buffer beside it.
    expect(showsDraft({ ...settled, draft: 'half an answer' })).toBe(true);
  });

  it('yields to a human gate, whose card is already showing the text', () => {
    expect(showsDraft({ ...settled, draft: 'half an answer', awaitingApproval: true })).toBe(false);
  });
});
