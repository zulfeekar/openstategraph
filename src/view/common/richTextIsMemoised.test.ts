import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

/**
 * `RichText` is memoised, and its props stay comparable — `the-cost-of-one-more/20`.
 *
 * A **proxy**, and it opens by saying so. The claim that matters is *an
 * unchanged step does not re-parse its Markdown on the next commit*, and this
 * suite runs in `node` with no DOM (`vite.config.ts`), so it cannot mount a
 * component and count renders. What it can do is fail if the two properties
 * the claim rests on are removed, and both are visible in the source: the
 * component is wrapped in `memo`, and every prop it takes is a primitive, so
 * `memo`'s default shallow comparison is an exact one.
 *
 * The second half is the one worth guarding. `memo` on a component taking an
 * object or a callback is a memo that never hits — or worse, one that hits
 * when it should not. Adding `components={...}` or an `onClick` here would
 * quietly turn this from a fix into a bug, and nothing else would notice.
 *
 * What it cost to find: a CPU profile of a 700-frame run spent 56% of the
 * whole burst inside `react-markdown`, ×3.68 per doubling of the frame count,
 * because the run trace renders one `RichText` per step and every commit
 * re-rendered all of them. With the memo the same profile spends 0.4%.
 */

const SOURCE = readFileSync(join(import.meta.dirname, 'RichText.tsx'), 'utf-8');

describe('the one component that parses Markdown does not re-parse unchanged text', () => {
  it('is wrapped in memo', () => {
    expect(SOURCE).toMatch(/export const RichText = memo\(/);
    expect(SOURCE).toMatch(/^import \{ memo \} from 'react';$/m);
  });

  it('takes only primitives, so the shallow comparison is an exact one', () => {
    const props =
      /export const RichText = memo\(function RichText\([\s\S]*?\}: \{([\s\S]*?)\}\)/.exec(SOURCE);
    expect(props, 'the props type is no longer where this test can read it').not.toBeNull();
    const declared = (props?.[1] ?? '')
      .split(';')
      .map((line) => line.trim())
      .filter((line) => line.length > 0);

    expect(declared).toEqual(['text: string', 'className?: string']);
  });
});
