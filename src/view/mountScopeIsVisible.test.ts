import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

/**
 * `say-it-on-the-surface/08` — the sentence that makes **Open this mount**
 * safe to press used to live only in a `title` attribute, on the card
 * (`CompositionBody.tsx`) and again on arrival (`DrillBanner.tsx`). A
 * `title` does not exist on a touch device and does not appear for a
 * keyboard user tabbing to the control — so the one fact answering *"if I
 * edit this, what else changes?"* was invisible at the moment a user
 * decides whether to click.
 *
 * Modelled on `src/nodes/compose/slugIsExplained.test.ts` — that ticket's
 * own pin, and the nearest shape for this one: read the source as text
 * (`chipsDoNotMoveTheLayout.test.ts` already does this for a `view/`
 * component, precisely so the suite can stay in `node` with no DOM) and
 * assert the fact sits in a JSX text node, not inside `title={...}`.
 *
 * The two wrong models a reader can hold are *"this edits everything"* and
 * *"this is a copy"* (`CLAUDE.md`'s own lexicon: a mount is an instance, by
 * reference — not a copy). Both must-not-say checks below guard that
 * distinction rather than merely a word count.
 */

const compositionBody = readFileSync(
  new URL('./nodes/CompositionBody.tsx', import.meta.url),
  'utf8',
);
const drillBanner = readFileSync(new URL('./workflow/DrillBanner.tsx', import.meta.url), 'utf8');

describe('the mount card says what the button does before it is pressed', () => {
  it('carries the fact in a visible span, not only in the title attribute', () => {
    // Exact shape of the element this ticket adds: a JSX text child, so it
    // renders for a keyboard user and on a touch device, not only on hover.
    expect(compositionBody).toMatch(
      /<span className="node__composition-scope">\s*this mount only, others unaffected\s*<\/span>/,
    );
  });

  it('still explains the fuller picture in the title, for a mouse', () => {
    // The `title` is not removed — a mouse user still gets the longer
    // sentence on hover. It is just no longer the *only* carrier.
    expect(compositionBody).toMatch(/its own overrides, not the shared definition/);
  });

  it('never says "copy" beside the visible fact — a mount is a reference', () => {
    const scopeLine = compositionBody.match(
      /<span className="node__composition-scope">[\s\S]*?<\/span>/,
    )?.[0];
    expect(scopeLine).toBeDefined();
    expect(scopeLine).not.toMatch(/copy/i);
  });
});

describe('the drill banner says the same fact on arrival', () => {
  it('carries the fact as visible text inside the pill, not only its title', () => {
    expect(drillBanner).toMatch(
      /<span className="drill-banner__shared">\s*\{mount\} — its own overrides, not the shared package\. Values can differ here; shape cannot\.\s*<\/span>/,
    );
  });

  it('never claims the shape is editable', () => {
    const pill = drillBanner.match(/<span className="drill-banner__shared">[\s\S]*?<\/span>/)?.[0];
    expect(pill).toBeDefined();
    // "shape cannot [differ]" must survive; nothing may say the opposite.
    expect(pill).toMatch(/shape cannot/);
    expect(pill).not.toMatch(/shape can\b/);
  });

  it('never says "copy" beside the visible fact — a mount is a reference', () => {
    const pill = drillBanner.match(/<span className="drill-banner__shared">[\s\S]*?<\/span>/)?.[0];
    expect(pill).toBeDefined();
    expect(pill).not.toMatch(/copy/i);
  });
});
