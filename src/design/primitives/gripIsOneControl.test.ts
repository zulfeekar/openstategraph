import { readFileSync, readdirSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join, relative, sep } from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * `stable-beta-public/21`. **A draggable edge is one control, and this
 * repository was drawing it twice.**
 *
 * The owner drew a stroke over the run dock's grip and asked for the same
 * thing on the chat column, *"the rule of thumb of the design system for
 * draggable"*. Measured on 8124 at `ce751c6`, before this file existed —
 * both grips resting at 2px × 300px of `--color-rule`, and both hovering a
 * 2px `--color-primary` line, so the two hand-written rule sets agreed on
 * paper. What did **not** agree is what a reader sees, because the dock's
 * grip sits on the dock's own `border-bottom: var(--border-width-rule)
 * solid var(--color-rule)` and the column's sits on a hairline panel edge:
 * the dock's hovered edge painted **4px** of ink (y 233–237: 2px accent
 * over 2px rule) against the column's 2px. One control, two weights, and
 * neither stylesheet could see the other.
 *
 * So the weight is a token and the control is a primitive. Two states,
 * both drawn, both owned here and unpickable by a surface:
 *
 * - **at rest** — a `--grip-length` bar, centred on the edge, at
 *   `--color-border` and hairline weight. Present without a pointer, quiet
 *   enough not to read as a second border.
 * - **on hover and on `:focus-visible`** — the same bar at `--grip-weight`
 *   in `--color-rule`: the heavy stroke the owner drew, and the 4px the
 *   dock's edge already measured.
 *
 * The point of the file is the last assertion rather than the first ones:
 * **no other stylesheet under `src/` draws a resting grip bar.** Two
 * declarations of one affordance is the defect; a test that only checked
 * the primitive was right would have passed on the day `19` shipped, with
 * the two hand-written rule sets still in place.
 *
 * `NodeCard`'s resize corner is deliberately not this control — the owner
 * said its style is correct — and it is a glyph drawn out of two border
 * edges rather than a bar centred on an edge, so it spends neither token.
 */

const SRC = fileURLToPath(new URL('../../', import.meta.url));
const read = (path: string): string => readFileSync(path, 'utf8');
const at = (relPath: string): string => read(join(SRC, relPath));
const code = (css: string): string => css.replace(/\/\*[\s\S]*?\*\//g, '');
const under = (path: string): string => relative(SRC, path).split(sep).join('/');

/** Every `.css` under `src/`, so a new stylesheet is covered the day it lands. */
function stylesheets(dir: string = SRC): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) found.push(...stylesheets(path));
    else if (entry.endsWith('.css')) found.push(path);
  }
  return found.sort();
}

/** The block for one selector, as written — `{...}` only, comments stripped. */
function ruleBody(css: string, selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = new RegExp(`${escaped}\\s*\\{([^}]*)\\}`).exec(code(css));
  if (!match) throw new Error(`no rule for ${selector}`);
  return match[1] ?? '';
}

const GRIP_CSS = 'design/primitives/Grip.css';

describe('the grip is one primitive, with both of its states in tokens', () => {
  /**
   * **Derived, not picked.** `tokens.css` says twice already that the
   * authored file ships two widths and a third number here would be a
   * third guess. 4px is `--osg-rule` doubled — which is not a coincidence
   * and not a taste: it is the composite the dock's hovered edge measured,
   * an accent line stacked on the dock's own rule.
   */
  it('declares --grip-weight from the authored rule width, not a fresh literal', () => {
    const tokens = code(at('design/styles/tokens.css'));
    const declared = /--grip-weight:\s*([^;]+);/.exec(tokens)?.[1]?.trim() ?? '';
    expect(declared).toMatch(/var\(--osg-rule\)/);
    expect(declared).not.toMatch(/^\d/);
  });

  const ORIENTATIONS: ReadonlyArray<
    readonly [name: string, side: string, along: string, cursor: string]
  > = [
    ['.grip--vertical', 'border-left', 'height', 'ew-resize'],
    ['.grip--horizontal', 'border-top', 'width', 'ns-resize'],
  ];

  it.each(ORIENTATIONS)('%s rests quiet: a centred bar at hairline weight', (name, side, along) => {
    const body = ruleBody(at(GRIP_CSS), `${name}::before`);
    expect(body).toMatch(new RegExp(`${along}:\\s*var\\(--grip-length\\);`));
    expect(body).toMatch(
      new RegExp(`${side}:\\s*var\\(--border-width-hairline\\) solid var\\(--color-border\\);`),
    );
    expect(body).toMatch(/translate[XY]\(-50%\)/);
  });

  it.each(ORIENTATIONS)(
    '%s takes the full stroke on hover and on keyboard focus',
    (name, side, along) => {
      const body = ruleBody(at(GRIP_CSS), `${name}:hover::before,\n${name}:focus-visible::before`);
      expect(body).toMatch(new RegExp(`${along}:\\s*var\\(--grip-length\\);`));
      expect(body).toMatch(
        new RegExp(`${side}:\\s*var\\(--grip-weight\\) solid var\\(--color-rule\\);`),
      );
    },
  );

  it.each(ORIENTATIONS)(
    '%s is a 7px target with a resize cursor',
    (name, _side, _along, cursor) => {
      const body = ruleBody(at(GRIP_CSS), name);
      expect(body).toMatch(/(?:width|height):\s*7px;/);
      expect(body).toMatch(new RegExp(`cursor:\\s*${cursor};`));
    },
  );
});

describe('and nothing else draws one', () => {
  /**
   * The grep-shaped half. `--grip-length` is the resting bar's own
   * measurement: a stylesheet spending it is a stylesheet drawing a grip,
   * whatever it calls its class.
   */
  it('spends --grip-length in the primitive and nowhere else', () => {
    const spending = stylesheets()
      .filter((path) => /--grip-length\)/.test(code(read(path))))
      .map(under);
    expect(spending).toEqual([GRIP_CSS]);
  });

  /**
   * And the class half, because a copy could re-derive 300px by hand: no
   * stylesheet outside the primitive may style a selector called `grip`
   * at all. `NodeCard`'s corner is `.node__resize` and is untouched.
   */
  it('leaves no grip rule in a surface stylesheet', () => {
    const offenders = stylesheets()
      .filter((path) => under(path) !== GRIP_CSS)
      .filter((path) => /^[^{}]*grip[^{}]*\{/m.test(code(read(path))))
      .map(under);
    expect(offenders).toEqual([]);
  });

  /** Both surfaces render the primitive rather than a div of their own. */
  it.each([
    ['view/layout/PanelColumnGrip.tsx', 'vertical'],
    ['view/run/RunDock.tsx', 'horizontal'],
  ])('%s renders the Grip primitive', (file, orientation) => {
    const source = at(file);
    expect(source).toMatch(/from '@design\/primitives'/);
    expect(source).toMatch(new RegExp(`orientation="${orientation}"`));
    expect(source).not.toMatch(/className="[^"]*grip/);
  });
});
