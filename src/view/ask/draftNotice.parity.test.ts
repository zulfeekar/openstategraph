/**
 * The editor and `/chat` mark an unsettled reply with the same sentence.
 *
 * `every-workflow-green/45`. One fact — a grader has still to judge this text
 * — reaches a reader through two doors, and this repository has already paid
 * for the version of that where each door spells it for itself
 * (`graderVerdictLine.parity.test.ts`: four inputs, two answers, and a
 * substring tripwire green through all of them).
 *
 * The sentence is six words with no branching, so it needs no generator — but
 * it does need a test, because "somebody will notice" is what the drift it
 * replaces was relying on. Editing one spelling and not the other turns this
 * red.
 */
import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

import { DRAFT_NOTICE } from './draftNotice';

const PAGE = new URL('../../../backend/openstategraph/api/static/chat.html', import.meta.url);

describe('both surfaces say the same thing about a draft', () => {
  const page = readFileSync(PAGE, 'utf-8');

  it('the customer page writes the editor’s sentence', () => {
    expect(page).toContain(`"${DRAFT_NOTICE}"`);
  });

  it('and writes it once, into a region announced once', () => {
    // `role="status"` on the notice and not on the text: the notice never
    // changes, so a screen reader announces the state a single time, while a
    // live region around the streaming text would announce every token.
    expect(page).toContain('class="draft-notice" role="status"');
    expect(page.match(/Draft — not checked yet/g) ?? []).toHaveLength(1);
  });

  it('and hides the whole region until a marked frame arrives', () => {
    // Absence of the flag means *no grader is downstream*, never "checked".
    // A region that started visible would be a label on every answer.
    expect(page).toContain('<div class="draft" hidden>');
  });

  it('and lets nobody copy an unsettled figure out of it', () => {
    const rule = page.slice(page.indexOf('.draft:not([hidden])'));
    expect(rule.slice(0, rule.indexOf('}'))).toContain('user-select: none');
  });
});
