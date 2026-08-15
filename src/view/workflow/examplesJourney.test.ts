import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { EMPTY_CANVAS_EXAMPLES } from '@view/canvas/emptyStateCopy';
import {
  EXAMPLES_HINT_ACTION,
  EXAMPLES_ROUTE,
  examplesHintText,
  examplesShelfToggleLabel,
} from './examplesJourney';

/**
 * production-ready ticket 23 — "with the UI/UX + doc it is not clear how to
 * load the 20 examples and what to do."
 *
 * The defect was a journey, not a string, so these tests hold the journey
 * together: every surface points at the same route, says the same three verbs,
 * and none of them hardcodes a count that `index.json` can change underneath.
 */
const read = (relative: string) =>
  readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf8');

describe('the examples shelf header', () => {
  it('invites rather than merely counting', () => {
    const label = examplesShelfToggleLabel(23, false);
    expect(label).toContain('23 examples');
    expect(label).toMatch(/copy one/);
    expect(label).toMatch(/yours/);
  });

  it('reads as English when there is exactly one', () => {
    expect(examplesShelfToggleLabel(1, false)).toBe('1 example — copy it to make it yours');
  });

  it('stops inviting once the shelf is open, where the invitation is answered', () => {
    expect(examplesShelfToggleLabel(23, true)).toBe('Hide the examples');
  });
});

describe('the first-run hint', () => {
  it('says all three verbs in order: browse, copy, yours', () => {
    const text = examplesHintText(23);
    expect(text.toLowerCase().indexOf('browse')).toBeLessThan(text.toLowerCase().indexOf('copy'));
    expect(text.toLowerCase().indexOf('copy')).toBeLessThan(text.toLowerCase().indexOf('yours'));
  });

  it('names the route the same way every other surface does', () => {
    expect(examplesHintText(23)).toContain(EXAMPLES_ROUTE);
    expect(EMPTY_CANVAS_EXAMPLES).toContain(EXAMPLES_ROUTE);
  });

  it('never says "load", because taking one is a copy that severs', () => {
    for (const copy of [examplesHintText(23), EMPTY_CANVAS_EXAMPLES, EXAMPLES_HINT_ACTION]) {
      expect(copy).not.toMatch(/\bload\b/i);
    }
  });

  it('agrees with itself about the number', () => {
    expect(examplesHintText(1)).toContain('1 worked example ');
    expect(examplesHintText(23)).toContain('23 worked examples');
  });
});

describe('the docs walk the same journey (ticket 23, fourth leg)', () => {
  const gettingStarted = read('../../../docs/getting-started.md');
  const shipped: number = JSON.parse(read('../../../backend/openstategraph/examples/index.json'))
    .examples.length;

  it('walks copy-an-example in the editor, by the controls it actually has', () => {
    expect(gettingStarted).toContain('## 4b. Or don’t draw one — copy a worked example');
    for (const control of ['**Workflows**', '**Examples**', '**Copy**', '**Saved Workflows**']) {
      expect(gettingStarted).toContain(control);
    }
  });

  it('walks the same journey on the command line', () => {
    expect(gettingStarted).toContain('openstategraph examples list');
    expect(gettingStarted).toContain('openstategraph examples copy evaluator-optimizer');
  });

  it('says the three verbs out loud', () => {
    expect(gettingStarted).toContain('**Browse → copy → it is yours.**');
  });

  it('quotes the shelf button by the words the shelf really shows', () => {
    // A doc that walks a user to a control by a caption the UI does not use is
    // a doc that sends them looking for something that is not there.
    expect(gettingStarted).toContain(examplesShelfToggleLabel(shipped, false));
  });

  it('counts the gallery correctly, in both docs that state a number', () => {
    // Prose here has claimed twenty, twenty-one and twenty-two against 23 —
    // three separate drifts, none of which anything caught. `index.json` is
    // the only thing that knows, so it is the thing asserted against.
    expect(shipped).toBeGreaterThan(0);
    expect(gettingStarted).toContain(`**${shipped}** finished packages`);
    expect(read('../../../docs/adoption.md')).toContain(
      `${capitalise(inWords(shipped))} finished packages ship in the wheel`,
    );
  });
});

/** Only wide enough for the counts a gallery of this size can have. */
function inWords(n: number): string {
  const tens = ['', '', 'twenty', 'thirty'];
  const units = ['', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine'];
  if (n < 20) throw new Error(`the gallery has shrunk to ${n} — teach this helper the small words`);
  const ten = tens[Math.floor(n / 10)] ?? '';
  return n % 10 === 0 ? ten : `${ten}-${units[n % 10] ?? ''}`;
}

const capitalise = (word: string) => word.charAt(0).toUpperCase() + word.slice(1);

describe('no surface hardcodes how many examples there are', () => {
  // Prose in this repository has claimed twenty, twenty-one and twenty-two,
  // against an actual 23. The count comes from `GET /api/examples` and from
  // nowhere else, so a literal here is a fourth thing to go stale.
  it('keeps digits out of the shared copy and out of the empty canvas', () => {
    expect(read('./examplesJourney.ts')).not.toMatch(/^export const .*\d\d.*examples/im);
    expect(EMPTY_CANVAS_EXAMPLES).not.toMatch(/\d/);
  });
});
