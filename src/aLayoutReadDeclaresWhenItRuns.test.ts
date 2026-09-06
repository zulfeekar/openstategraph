import { readdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';
import { describe, expect, it } from 'vitest';

/**
 * No effect reads layout without saying when it runs — `the-cost-of-one-more/22`.
 *
 * A **proxy**, and it opens by saying so, because the claim that matters is
 * about a running browser and this suite runs in `node` with no DOM
 * (`vite.config.ts`). What it can do is fail on the shape, and the shape is
 * exact: a `useEffect` with **no dependency array** runs after every render of
 * the component for every reason its parents render, and a
 * `getBoundingClientRect` inside one forces a synchronous layout of whatever
 * the document currently holds. The two together cost what the *document*
 * costs, on a schedule nobody chose.
 *
 * That is not a hypothetical. `20`'s CPU profile of a 700-frame burst through
 * the real editor put `getBoundingClientRect` at **19.7% of the entire burst**,
 * second only to Markdown parsing, growing ×3.65 per doubling of the frame
 * count — and the call stack named exactly one caller: `Minimap.tsx`'s coverage
 * effect, reached through `commitPassiveMountOnFiber`. It grew because the run
 * trace was adding rows to the document on every frame, not because the minimap
 * was doing more.
 *
 * **The census is deliberately narrow, and the narrowness is the reason it can
 * stay at zero.** It fires only where both halves are present — a layout read,
 * *and* no dependency array. An effect that reads layout on a declared
 * dependency is fine and common; an effect with no dependency array that
 * touches no layout is cheap. Widening it to either half alone would produce
 * failures nobody could act on, and a gate that fails wrongly gets suppressed
 * and then measures nothing.
 *
 * **What it cannot see**, recorded rather than implied: an effect whose
 * dependency array is *wrong* — too narrow, so the measurement goes stale, or
 * containing a value rebuilt on every render, so it fires every time anyway.
 * The second is exactly what a naive fix here would have produced (`rects` is
 * `model.nodes().map(...)`), and the only thing standing against it is that the
 * value is a `useMemo` keyed on the model's own version. No parse can tell a
 * correct dependency array from a plausible one.
 */

const SRC = fileURLToPath(new URL('.', import.meta.url));

/** Reads that force the browser to lay the document out before answering. */
const FORCES_LAYOUT =
  /getBoundingClientRect|getClientRects|offsetWidth|offsetHeight|offsetTop|offsetLeft|clientWidth|clientHeight|scrollHeight|scrollWidth|getComputedStyle/;

/** Every effect in the app that reads layout and does not say when it runs. */
function undeclaredLayoutReads(): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(SRC, { recursive: true, encoding: 'utf8' })) {
    const relative = entry.split('\\').join('/');
    if (!/\.tsx?$/.test(relative) || /\.(test|spec)\.tsx?$/.test(relative)) continue;
    if (relative.endsWith('.d.ts')) continue;
    const text = readFileSync(SRC + relative, 'utf8');
    if (!FORCES_LAYOUT.test(text)) continue;
    const source = ts.createSourceFile(relative, text, ts.ScriptTarget.Latest, true);
    const walk = (node: ts.Node): void => {
      if (
        ts.isCallExpression(node) &&
        /^use(Effect|LayoutEffect)$/.test(node.expression.getText(source)) &&
        node.arguments.length < 2 &&
        FORCES_LAYOUT.test(node.arguments[0]?.getText(source) ?? '')
      ) {
        const line = source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1;
        found.push(`${relative}:${line}`);
      }
      node.forEachChild(walk);
    };
    source.forEachChild(walk);
  }
  return found;
}

describe('an effect that forces a layout declares what it depends on', () => {
  it('has no instances left in the app', () => {
    expect(undeclaredLayoutReads()).toEqual([]);
  });
});
