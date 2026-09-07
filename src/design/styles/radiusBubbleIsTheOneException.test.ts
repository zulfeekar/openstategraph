import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * `--radius-bubble` is the design system's one recorded corner-radius
 * exception — `stable-beta-public/11`.
 *
 * `tokens.css`'s own comment states the rule: every `--radius-*` in the
 * product resolves to `--osg-radius`, the authored `0px` — "Flat, 0 radius,
 * one accent." — except `--radius-full`, which is not a corner radius at all
 * (it draws circles). `--radius-bubble` is the second exception and the
 * first that IS a corner radius: a chat bubble is a speech shape, not a
 * card, and the owner asked to round bubbles only, everything else staying
 * square.
 *
 * A recorded exception needs an instrument the same way every other one in
 * this codebase does (`WorkflowModel`'s public-surface exception, the
 * module-size ceiling's per-file numbers): a bare comment describes, a test
 * pins. This one pins both halves — the exception is real, and it is the
 * *only* one.
 */
const read = (relative: string) =>
  readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf8');

const TOKENS_CSS = read('./tokens.css');
const CHAT_HTML = read('../../../backend/openstategraph/api/static/chat.html');

/** The value a `--name: value;` declaration resolves to, at :root scope. */
function rootValue(css: string, name: string): string | undefined {
  const m = css.match(new RegExp(`${name}:\\s*([^;]+);`));
  return m?.[1]?.trim();
}

const SIX_FLAT_NAMES = [
  '--radius-xs',
  '--radius-sm',
  '--radius-md',
  '--radius-lg',
  '--radius-xl',
  '--radius-2xl',
] as const;

describe('the six ordinary radius names stay the authored flat zero', () => {
  it.each(SIX_FLAT_NAMES)('%s still resolves to var(--osg-radius)', (name) => {
    expect(rootValue(TOKENS_CSS, name)).toBe('var(--osg-radius)');
  });
});

describe('`--radius-bubble` is the one exception, in `tokens.css`', () => {
  it('is declared', () => {
    expect(rootValue(TOKENS_CSS, '--radius-bubble')).toBeDefined();
  });

  it('is not the flat alias — a literal, non-zero corner radius', () => {
    const value = rootValue(TOKENS_CSS, '--radius-bubble');
    expect(value).not.toBe('var(--osg-radius)');
    expect(value).toMatch(/^\d+(\.\d+)?px$/);
    expect(parseFloat(value ?? '0')).toBeGreaterThan(0);
  });
});

describe('the customer page restates the same number, by name', () => {
  it('declares `--radius-bubble` in its own `:root`', () => {
    expect(rootValue(CHAT_HTML, '--radius-bubble')).toBeDefined();
  });

  it('agrees with `tokens.css` on the value — one number, written twice', () => {
    expect(rootValue(CHAT_HTML, '--radius-bubble')).toBe(rootValue(TOKENS_CSS, '--radius-bubble'));
  });
});
