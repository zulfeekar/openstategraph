import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { DIALOG_SIZES, dialogClassName } from './dialogSize';

/**
 * `kanban-patrol/06`. The board needs four readable columns and every modal in
 * this product is `width: min(520px, 100%)`, so a width variant had to exist.
 *
 * **The regression this file is written to catch is not the variant. It is the
 * default moving.** The tempting one-line change is to widen `.dialog` itself
 * and let the five existing callers inherit it; that ships a credentials form
 * and a keyboard-shortcut list at 90% of the viewport and nothing in the suite
 * says a word. So the pin is on the *default*, and on the census of who opts
 * out of it — derived by walking every `<Dialog` in `src/`, never listed, for
 * the reason `layerBoundaries.test.ts` gives about lists of paths: a list
 * covers the callers somebody already thought about.
 *
 * The variant is a **layout** prop on the shared component rather than a fork.
 * `Dialog` uniquely gets three things right — Escape, a focus trap that wraps
 * at both ends, and a backdrop that closes only on a press *and* release of
 * its own — and a one-off large modal would have to re-earn all three.
 *
 * `dialogClassName` is a plain function in a plain `.ts` module rather than a
 * `clsx(...)` expression read back as source, because a source regex over JSX
 * is a rule about whatever prettier last did to the line. The suite runs in
 * `node` (`vite.config.ts`, on purpose), so a pure function is the one part of
 * a component this repository can actually execute.
 */

const HERE = fileURLToPath(new URL('.', import.meta.url));
const SRC = fileURLToPath(new URL('..', import.meta.url));

const read = (path: string): string => readFileSync(path, 'utf8');

/** The declaration block of a class selector, by exact selector text. */
function ruleFor(css: string, selector: string): string {
  const at = css.indexOf(`\n${selector} {`);
  expect(at, `no rule for ${selector}`).toBeGreaterThan(-1);
  const open = css.indexOf('{', at);
  const close = css.indexOf('}', open);
  return css.slice(open + 1, close);
}

/** The value of a declared property inside a block, `var()` and all. */
function declared(block: string, property: string): string | undefined {
  const match = new RegExp(`(?:^|;|\\n)\\s*${property}\\s*:\\s*([^;}]+)`).exec(block);
  return match?.[1]?.trim();
}

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return sources(path);
    if (!path.endsWith('.tsx')) return [];
    return [path];
  });
}

/** Every `<Dialog …>` rendered in the app, with the text of its opening tag. */
function dialogUses(): Array<{ file: string; opening: string }> {
  const uses: Array<{ file: string; opening: string }> = [];
  for (const path of sources(SRC)) {
    const text = read(path);
    let from = text.indexOf('<Dialog');
    while (from !== -1) {
      // `<DialogProps>` and friends are not renders.
      if (/^<Dialog[\s/>]/.test(text.slice(from))) {
        const close = text.indexOf('>', from);
        uses.push({
          file: path.slice(SRC.length),
          opening: close === -1 ? text.slice(from, from + 400) : text.slice(from, close + 1),
        });
      }
      from = text.indexOf('<Dialog', from + 1);
    }
  }
  return uses;
}

describe('a dialog is 520px wide unless it says otherwise', () => {
  const OVERLAYS = read(join(HERE, 'overlays.css'));

  it('still spends exactly the width every existing modal was drawn against', () => {
    // The literal, character for character. `min(520px, 100%)` is the number
    // five shipped surfaces were laid out to, and a variant that moved it
    // would be a restyle of the whole product wearing a new prop.
    expect(declared(ruleFor(OVERLAYS, '.dialog'), 'width')).toBe('min(520px, 100%)');
  });

  it('states the large size in a rule of its own, so the default is untouched', () => {
    const large = ruleFor(OVERLAYS, '.dialog--large');
    // 90% of the viewport in both dimensions — the owner's requirement, and
    // the reason the variant exists at all.
    expect(declared(large, 'width')).toContain('90vw');
    expect(declared(large, 'height')).toContain('90vh');
    // `.dialog` caps at `min(640px, 100%)`; a variant that only widened would
    // be a wide 640px box, not a board.
    expect(declared(large, 'max-height')).toContain('90vh');
  });

  it('names both sizes and nothing else', () => {
    expect([...DIALOG_SIZES]).toEqual(['default', 'large']);
  });

  it('adds no class at all for the default, which is what makes it the default', () => {
    expect(dialogClassName('default')).toBe('dialog');
    expect(dialogClassName('large')).toBe('dialog dialog--large');
  });
});

describe('the callers that were here first', () => {
  const uses = dialogUses();

  it('finds every Dialog in the app, so the census cannot go quiet', () => {
    // The guard on the walker. `kanban-patrol/06`'s own brief named three
    // callers; there are five — `KnowledgeBody` and `AccessibilityCheck` are
    // the two nobody counted, and they are exactly the kind a hand-written
    // list would have missed.
    expect(uses.map((use) => use.file).sort()).toEqual(
      [
        'nodes/KnowledgeBody.tsx',
        'overlays/AccessibilityCheck.tsx',
        'overlays/ArrivalDialog.tsx',
        'overlays/CredentialsDialog.tsx',
        'overlays/McpServersDialog.tsx',
        // `osg-agent-experience/68` — the choice a reload owes the user when
        // the file moved under its draft. At the default: two sentences and
        // two buttons, which is the narrowest thing in this list.
        'overlays/RestoredDraftDialog.tsx',
        'board/PatrolBoard.tsx',
        // `stable-beta-public/03` slice 5 — the spend breakdown, at the
        // default: three tables of figures, drawn against the same 520px
        // every other modal here is.
        'spend/SpendDialog.tsx',
      ].sort(),
    );
  });

  it('leaves every one of them at the default, and the board is the only opt-in', () => {
    const opted = uses.filter((use) => /\bsize=/.test(use.opening)).map((use) => use.file);
    expect(opted).toEqual(['board/PatrolBoard.tsx']);
  });
});
