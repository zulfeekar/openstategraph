import { readFileSync } from 'node:fs';
import { execSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * The instrument for `the-look-has-an-author-now/20`, filed on one sentence:
 * *"Rule of thumb: you must have design consistency. A box does not have a
 * default spacing."* — said pointing at the Stored runs popover, whose title
 * bar, back button, note and error line all touched its own edge.
 *
 * The defect was not the popover. `.popover` in `Popover.css` declared
 * `display: flex; flex-direction: column`, a fill, a border and a shadow, and
 * **no padding at all**; `.stored-runs` inside it declared a `gap` and no
 * padding either, so the two of them together produced a box whose content
 * had air between its rows and none at its edges. Nothing was wrong in that
 * file. What was wrong is that there was no default to have forgotten — every
 * box in the product picked an inset, or picked none, on its own.
 *
 * ## What counts as a box
 *
 * Derived, never listed: a rule in any `src/**\/*.css` that
 *
 * - draws a surface — a `border-radius` together with a non-transparent fill
 *   or a visible border, and
 * - **stacks its children** — `display: flex` with `flex-direction: column`,
 *   or `display: grid`.
 *
 * The second clause is what separates a box from a mark. A pill, a badge, a
 * `kbd`, a code span and a tooltip all draw a surface too, and all of them pad
 * *their own single line of text* — that padding is typography and the type
 * scale owns it. A box pads **other elements**, and that is the padding this
 * file is about.
 *
 * **The narrowing is a recorded gap, not a claim of completeness.** A surface
 * that lays its children out by flow or by row — `.menu`, `.shortcuts` — is a
 * container too, and this census does not see it, because from CSS alone a
 * row of two things and a control with an icon are the same declaration. That
 * is the same trade `aColumnHasOneEdgeNotFour.test.ts` records: a check that
 * covers less and never fires wrongly is worth more than one that covers
 * everything and gets suppressed.
 *
 * ## The rule
 *
 * A box's inset follows from **what its content is for**, in three members:
 *
 * | Member | The content is… | Inset |
 * | --- | --- | --- |
 * | *read* — the default | prose, a request, a form, a picker | `--box-inset` |
 * | *scanned* | a readout, a trace, a row in a list | `--box-inset-dense` |
 * | *regions* | named regions that carry their own inset, or one full-bleed child | zero, declared below |
 *
 * **Read is the default and is not recorded anywhere.** A box this file has
 * never seen must use `--box-inset` or it fails — which is the whole of what
 * the owner asked for, since the two tables below are the only two ways to
 * say something else and each row of them carries its argument.
 *
 * ## Padding and gap answer different questions
 *
 * Padding is the distance from the box's edge to its content. Gap is the
 * distance between two of its children. Neither substitutes for the other,
 * and a box that sets a gap has said nothing about its edges — which is
 * precisely how `.stored-runs` came to have generous air between its rows and
 * none around them. So this file checks padding and never reads `gap`.
 */

const SRC = fileURLToPath(new URL('../../', import.meta.url));

const STYLESHEETS: readonly string[] = execSync('find . -name "*.css"', { cwd: SRC })
  .toString()
  .trim()
  .split('\n')
  .map((p) => p.replace(/^\.\//, ''))
  .sort();

interface Rule {
  readonly selector: string;
  readonly decls: Readonly<Record<string, string>>;
}

/**
 * Depth-aware, so an at-rule block (`@media`, `@supports`) is descended into
 * rather than matched as a rule. A regex that flattens `@media` by deleting a
 * closing brace at column zero deletes every rule's closing brace too — which
 * is why this is a walk and not a `replace`.
 */
function parseRules(css: string): Rule[] {
  const src = css.replace(/\/\*[\s\S]*?\*\//g, '');
  const rules: Rule[] = [];
  let i = 0;
  let head = '';
  while (i < src.length) {
    const ch = src[i];
    if (ch === '{') {
      const selector = head.trim().replace(/\s+/g, ' ');
      head = '';
      if (selector.startsWith('@')) {
        i += 1;
        continue;
      }
      let depth = 1;
      let body = '';
      let j = i + 1;
      while (j < src.length && depth > 0) {
        if (src[j] === '{') depth += 1;
        else if (src[j] === '}') {
          depth -= 1;
          if (depth === 0) break;
        }
        body += src[j];
        j += 1;
      }
      const decls: Record<string, string> = {};
      for (const d of body.matchAll(/([-a-zA-Z]+)\s*:\s*([^;]+);/g)) {
        decls[d[1] ?? ''] = (d[2] ?? '').trim();
      }
      rules.push({ selector, decls });
      i = j + 1;
      continue;
    }
    if (ch === '}') {
      head = '';
      i += 1;
      continue;
    }
    head += ch;
    i += 1;
  }
  return rules;
}

const drawsASurface = (d: Readonly<Record<string, string>>): boolean => {
  const fill = d.background ?? d['background-color'] ?? '';
  const filled = fill !== '' && !/^(transparent|none|inherit|unset)$/.test(fill);
  const bordered =
    Object.keys(d).some((p) => /^border/.test(p) && !/radius|width/.test(p)) &&
    !/(^|\s)transparent(\s|$)/.test(d.border ?? 'x');
  return d['border-radius'] !== undefined && (filled || bordered);
};

const stacksItsChildren = (d: Readonly<Record<string, string>>): boolean => {
  const display = d.display ?? '';
  return (/flex/.test(display) && d['flex-direction'] === 'column') || /grid/.test(display);
};

/** The declared inset, as authored — shorthand if there is one, else the
 *  longhands it set, so a box that pads three sides is not read as padding
 *  all four. `undefined` means the box declared no inset at all. */
function insetOf(d: Readonly<Record<string, string>>): string | undefined {
  if (d.padding !== undefined) return d.padding;
  const sides = (['top', 'right', 'bottom', 'left'] as const)
    .map((s) => (d[`padding-${s}`] === undefined ? null : `${s}:${d[`padding-${s}`]}`))
    .filter((v): v is string => v !== null);
  return sides.length > 0 ? sides.join(' ') : undefined;
}

interface Box {
  readonly file: string;
  readonly selector: string;
  readonly inset: string | undefined;
}

function census(): Box[] {
  const boxes: Box[] = [];
  for (const file of STYLESHEETS) {
    const merged = new Map<string, Record<string, string>>();
    for (const rule of parseRules(readFileSync(SRC + file, 'utf8'))) {
      merged.set(rule.selector, { ...(merged.get(rule.selector) ?? {}), ...rule.decls });
    }
    for (const [selector, decls] of merged) {
      // A pseudo-element paints a decoration, not a box that holds children.
      if (/::(before|after|-webkit|-moz)/.test(selector)) continue;
      if (!drawsASurface(decls) || !stacksItsChildren(decls)) continue;
      boxes.push({ file, selector, inset: insetOf(decls) });
    }
  }
  return boxes;
}

/** The default. A box is read unless one of the two tables below says why not. */
const READ = 'var(--box-inset)';

/** A box whose content is scanned rather than read. */
const DENSE = 'var(--box-inset-dense)';

/**
 * Boxes whose content is a readout, a trace or a row in a list. `--box-inset`
 * is the air a paragraph wants; on three lines of monospace or a list row it
 * reads as a card, and a column of them reads as a stack of cards rather than
 * a list. Each row is here because somebody looked at what the box holds.
 */
const SCANNED: ReadonlyMap<string, string> = new Map([
  ['.ask__steps', 'the trace: one line per step, scanned while a run is moving'],
  ['.inspector__log', 'a node’s captured log lines, monospace'],
  ['.node__live-input', 'the value that arrived on a port, shown on the card'],
  ['.workflow-manager__item', 'one row of the workflow list — a row, not a card'],
  [
    '.arrival__row',
    'one row of the arrival offer — a name, where it lives, how long ago; scanned ' +
      'down a column, and at the wider inset a column of them reads as cards',
  ],
  ['.start-panel__row', 'the same row, on the blank canvas’s Recent list'],
]);

/**
 * Boxes that deliberately declare no inset, because something inside them
 * already owns the edge. This is the answer to *"what about a box whose child
 * is edge-to-edge on purpose"*: it is said here, by name, with the argument —
 * never by a box quietly having no padding.
 */
const REGIONS: ReadonlyMap<string, string> = new Map([
  [
    '.dialog',
    'header, body and footer regions, each with its own inset; the header ' +
      'draws a rule to the box’s edge and a padded parent would inset that rule',
  ],
  [
    '.graph-preview__panel',
    'the same three regions as `.dialog`, and its body holds a diagram that ' +
      'is sized to the box rather than laid inside it',
  ],
  [
    '.node',
    'a card’s header carries a full-bleed fill that has to reach the card’s ' +
      'own edge to read as a header; the body below it carries the inset',
  ],
  [
    '.minimap',
    'one child, `.minimap__surface`, is a render of the whole canvas — an ' +
      'inset would crop it away from the frame it is a miniature of',
  ],
]);

describe('a box has a default inset', () => {
  const boxes = census();

  it('the census finds the boxes it is meant to find', () => {
    // A positive floor. Were the parser or either predicate to break, every
    // assertion below would pass over an empty list and this file would
    // measure nothing at all.
    expect(boxes.length).toBeGreaterThanOrEqual(13);
    expect(boxes.map((b) => b.selector)).toContain('.popover');
  });

  it('every box declares the inset its kind calls for', () => {
    const wrong: string[] = [];
    for (const box of boxes) {
      const expected = REGIONS.has(box.selector)
        ? undefined
        : SCANNED.has(box.selector)
          ? DENSE
          : READ;
      if (box.inset !== expected) {
        wrong.push(
          `${box.file} ${box.selector}: ${box.inset ?? 'no inset'} — wanted ${expected ?? 'no inset'}`,
        );
      }
    }
    expect(wrong).toEqual([]);
  });

  it('every recorded exception names a box that still exists', () => {
    // A row left behind after its box is renamed or deleted is a licence
    // nobody is using, and the next box to take that name inherits it.
    const live = new Set(boxes.map((b) => b.selector));
    const orphans = [...SCANNED.keys(), ...REGIONS.keys()].filter((s) => !live.has(s));
    expect(orphans).toEqual([]);
  });

  it('both insets are defined once, in the token file', () => {
    const tokens = readFileSync(SRC + 'design/styles/tokens.css', 'utf8');
    expect(tokens).toMatch(/--box-inset:\s*var\(--space-3\);/);
    expect(tokens).toMatch(/--box-inset-dense:\s*var\(--space-2\);/);
  });

  it('no stylesheet re-derives an inset from the raw spacing scale', () => {
    // `--box-inset` exists so that the answer to "how much air does a box
    // give its content" is in one place. A box spelling `var(--space-3)`
    // directly has re-derived it, and the two would then drift apart the way
    // two definitions of one grey did in `16`.
    const raw = boxes.filter((b) => b.inset !== undefined && /var\(--space-/.test(b.inset));
    expect(raw.map((b) => `${b.file} ${b.selector}: ${b.inset}`)).toEqual([]);
  });

  /**
   * The positive half, on the box the owner pointed at. Every assertion above
   * would stay green the day `.popover`'s padding is deleted and `.popover` is
   * added to `REGIONS` — the check would be measuring a decision nobody made.
   */
  it('the popover the owner pointed at declares the default inset', () => {
    const popover = boxes.find((b) => b.selector === '.popover');
    expect(popover?.inset).toBe(READ);
  });

  /**
   * The named escape, asserted rather than assumed. A popover holding a
   * `Panel` — the Workflows list — is the regions case, and a box cannot
   * cancel a padding its parent applied around it, so the parent stands its
   * content off instead. Without this the popover's inset would nest a second
   * edge inside the panel's own header rule.
   */
  it('the popover stands off a child that brings its own regions', () => {
    const css = readFileSync(SRC + 'design/primitives/Popover.css', 'utf8');
    const escape = parseRules(css).find((r) => r.selector === '.popover:has(> .panel)');
    expect(escape?.decls.padding).toBe('0');
  });

  /**
   * The height bound, and the honest limit of a CSS census.
   *
   * `Popover.tsx` measures the room left below the trigger against the stage
   * and applies it as an inline `maxHeight`, so **every** popover is bounded
   * by the container and no stylesheet can be read to prove it. What this
   * file can say is the half that lives in CSS: content inside a popover must
   * not declare a height bound of its own. A second literal would be the
   * copied-number defect `16` found in a colour, arriving in a property
   * nobody was watching — and it would win over the measured one, so the
   * popover would stop shrinking when the run dock is dragged.
   */
  it('no stored-runs rule declares a height bound of its own', () => {
    const css = readFileSync(SRC + 'view/run/StoredRuns.css', 'utf8');
    const bounded = parseRules(css)
      .filter((r) => r.decls['max-height'] !== undefined || r.decls.height !== undefined)
      .map((r) => r.selector);
    expect(bounded).toEqual([]);
  });

  /**
   * And the positive half of the same seam: a bound is only honest if the
   * overflow is reachable. Exactly one region of this panel scrolls, and the
   * rest are pinned — a picker whose own title scrolls away is one you can
   * get lost in.
   */
  it('the stored runs list is the one region that scrolls', () => {
    const rules = parseRules(readFileSync(SRC + 'view/run/StoredRuns.css', 'utf8'));
    const scrollers = rules
      .filter((r) => /auto|scroll/.test(r.decls['overflow-y'] ?? r.decls.overflow ?? ''))
      .map((r) => r.selector);
    expect(scrollers).toEqual(['.stored-runs__list']);
    const list = rules.find((r) => r.selector === '.stored-runs__list');
    // Without this floor a flex item cannot shrink below its content, and the
    // list would push the popover past the measured bound instead of moving
    // inside it.
    expect(list?.decls['min-height']).toBe('0');
  });
});
