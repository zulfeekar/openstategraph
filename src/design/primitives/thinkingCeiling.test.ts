import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { THINKING_MAX_HEIGHT } from './Thinking';

/**
 * `launch-readiness/140`. The 420 px ceiling is the owner's number and it is
 * load-bearing: a card on the canvas measures its own height and reports it to
 * the paper adapter, so an unbounded stack resizes the node and moves the
 * canvas under somebody who is mid-sentence.
 *
 * Pinned here rather than described in a comment, for the reason CLAUDE.md
 * gives twice: a number in prose has no way to fail. The customer chat is a
 * separate implementation of the same rule (`api/static/chat.html`), so it is
 * asserted against the same constant.
 */
describe('the thinking stack ceiling', () => {
  it('is 420 px', () => {
    expect(THINKING_MAX_HEIGHT).toBe(420);
  });

  it('is applied inline, so the stylesheet cannot silently disagree', () => {
    const css = readFileSync(new URL('./Thinking.css', import.meta.url), 'utf8');
    // A declaration, not the word — the comment above it names the property.
    expect(css).not.toMatch(/^\s*max-height:/m);
  });

  it('is the same ceiling the customer chat draws', () => {
    const chat = readFileSync(
      new URL('../../../backend/openstategraph/api/static/chat.html', import.meta.url),
      'utf8',
    );
    expect(chat).toMatch(new RegExp(`max-height: ${THINKING_MAX_HEIGHT}px`));
  });

  it('scrolls rather than clipping, on both surfaces', () => {
    const css = readFileSync(new URL('./Thinking.css', import.meta.url), 'utf8');
    expect(css).toMatch(/overflow-y: auto/);
    const chat = readFileSync(
      new URL('../../../backend/openstategraph/api/static/chat.html', import.meta.url),
      'utf8',
    );
    expect(chat).toMatch(/div\.thinking \{[\s\S]*?overflow-y: auto/);
  });
});
