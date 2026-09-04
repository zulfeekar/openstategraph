import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * One conversation grammar, written twice — `stable-beta-public/10`.
 *
 * The editor's chat panel and the customer page (`/chat`) are two different
 * assets by construction: `AskPanel.css` is bundled and reads the design
 * tokens from the app's stylesheet, while `chat.html` is a standalone file
 * served straight off the backend and restates the token *values* in its own
 * `:root` so it needs no build step. That is deliberate and is not what this
 * test objects to.
 *
 * What it pins is the layer above the values: the four decisions that make a
 * message read as a message rather than as a form field — how round a bubble
 * is, how much room its text has, how far apart two bubbles from the same
 * side sit, and how far apart the two sides sit. Before this ticket the
 * customer page had none of them: a question was a right-aligned box and an
 * answer a full-width bordered rectangle, on both surfaces, and each surface
 * had arrived there separately.
 *
 * So both files declare the grammar as `--chat-*` custom properties naming
 * the tokens they resolve to, and this test reads both files as text and
 * asserts the names and the token expressions agree. Text, not a rendered
 * DOM, for the reason `verticalRhythm.test.ts` gives beside the same
 * stylesheet: the grammar is a decision the stylesheets made, not a rendering
 * a browser has to reproduce to check.
 *
 * The assertion that the values are `var(--…)` references matters as much as
 * the agreement. Two files could agree on `9px` and still have broken the
 * rule the ticket names — no raw value — and the day the design system moves
 * a radius, agreement on a literal is agreement on the wrong number.
 */
const read = (relative: string) =>
  readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf8');

const ASK_PANEL_CSS = read('./AskPanel.css');
const CHAT_HTML = read('../../../backend/openstategraph/api/static/chat.html');

/**
 * Every `--chat-*` declaration in a file, by name.
 *
 * Deliberately selector-agnostic. The two files hang the grammar on different
 * elements — `.ask__thread` in the panel, `#log` in the standalone page —
 * because they have different containers, and insisting on one selector name
 * would pin the thing that legitimately differs while leaving the thing that
 * must not differ unchecked.
 */
function chatGrammar(source: string): Record<string, string> {
  const found: Record<string, string> = {};
  for (const match of source.matchAll(/(--chat-[a-z-]+):\s*([^;]+);/g)) {
    found[match[1] ?? ''] = (match[2] ?? '').trim();
  }
  return found;
}

/** The four decisions the ticket names. */
const GRAMMAR = [
  '--chat-bubble-radius',
  '--chat-bubble-padding',
  '--chat-gap-group',
  '--chat-gap-side',
] as const;

describe('the editor panel and the customer chat page share one conversation grammar', () => {
  const editor = chatGrammar(ASK_PANEL_CSS);
  const customer = chatGrammar(CHAT_HTML);

  it.each(GRAMMAR)('%s resolves to the same tokens on both surfaces', (name) => {
    expect(editor[name], `AskPanel.css declares ${name}`).toBeDefined();
    expect(customer[name], `chat.html declares ${name}`).toBeDefined();
    expect(customer[name]).toBe(editor[name]);
  });

  it.each(GRAMMAR)('%s is written as tokens, never as raw values', (name) => {
    for (const [file, value] of [
      ['AskPanel.css', editor[name]],
      ['chat.html', customer[name]],
    ] as const) {
      expect(value, `${file} declares ${name}`).toBeDefined();
      // Every space-separated part is a `var(--…)` reference. `padding` is two
      // of them, which is why this is a per-part check and not one regex over
      // the whole declaration.
      for (const part of (value ?? '').split(/\s+/)) {
        expect(part, `${file}'s ${name} part`).toMatch(/^var\(--[a-z0-9-]+\)$/);
      }
    }
  });
});
