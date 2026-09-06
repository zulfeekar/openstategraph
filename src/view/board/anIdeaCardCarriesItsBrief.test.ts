import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * `osg-agent-experience/25`. A card filed from a conversation carries a brief
 * the patrol's own cards do not have — the plain-English want and the check
 * that settles it — and the board is where a person reads it. A brief written
 * at filing time that nothing renders is a brief that was not worth writing.
 *
 * ## Why this reads the source rather than mounting the card
 *
 * The same reason `aBoardHeaderOutranksItsCards.test.ts` gives: the claims
 * here are facts about two files, not about a render. Whether the story is
 * drawn *conditionally* is the load-bearing half — a card that renders
 * `{card.story}` unguarded draws an empty element on all seven patrol cards
 * and would still pass a "the story appears" mount — and whether the two new
 * rules paint in tokens is a fact about a stylesheet, which no mount sees.
 *
 * ## The absent half is the asserted half
 *
 * Every seam in this feature keeps one rule: a missing field is an **absent
 * prop**, never an empty string, so nothing draws a label with nothing after
 * it. `kanbanCardMapping.test.ts` asserts it at the mapper; this asserts the
 * card actually depends on it.
 */

const REPO = new URL('../../../', import.meta.url);
const read = (path: string) => readFileSync(fileURLToPath(new URL(path, REPO)), 'utf8');

const card = read('src/view/board/PatrolCard.tsx');
const styles = read('src/view/board/PatrolBoard.css');

describe('the card draws the brief', () => {
  it('renders the story', () => {
    expect(card).toMatch(/\{card\.story\}/);
  });

  it('renders what done means', () => {
    expect(card).toMatch(/\{card\.doneWhen\}/);
  });

  it('names the two fields it draws them into, so the stylesheet can find them', () => {
    expect(card).toContain('patrol-card__story');
    expect(card).toContain('patrol-card__done-when');
    expect(card).toContain('patrol-card__agent');
  });

  it('draws each of them only when the card has one', () => {
    // The guard, not merely the reference: an unguarded `{card.story}` draws
    // an empty element on every patrol card and would satisfy the assertions
    // above unchanged.
    for (const field of ['story', 'doneWhen', 'agentModel']) {
      expect(card, `${field} is rendered unconditionally`).toMatch(
        new RegExp(`card\\.${field}\\s*\\?`),
      );
    }
  });

  it('shows the model and the effort together, so neither reads as a whole answer', () => {
    expect(card).toMatch(/card\.agentEffort/);
  });
});

describe('the two new rules paint in tokens', () => {
  it('declares them', () => {
    expect(styles).toContain('.patrol-card__story');
    expect(styles).toContain('.patrol-card__done-when');
    expect(styles).toContain('.patrol-card__agent');
  });

  it('mints no colour, size or font of its own', () => {
    // The board's standing rule — the card decides no colour. Every value in
    // the three new blocks is a `var(--…)`, so a hex or a raw px in any of
    // them is the drift this catches.
    const blocks = [
      ...styles.matchAll(/\.patrol-card__(?:story|done-when|agent)(?![\w-])[^{]*\{([^}]*)\}/g),
    ];
    expect(blocks.length).toBe(3);
    for (const [, body] of blocks) {
      expect(body, `raw value in ${body}`).not.toMatch(/#[0-9a-f]{3}|:\s*\d+px/i);
    }
  });
});
