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

describe('and the surface it edges cannot cover it — `stable-beta-public/22`', () => {
  /**
   * **A 7px target of which three pixels answered.** Measured on 8124 with
   * the inspector open, `document.elementFromPoint` walked across the
   * column grip at its vertical centre: the grip answered at x 594, 595,
   * 596 and the panel answered at 597 through 601. The strip straddles the
   * edge (`left: -3px`), so the three pixels that worked were the three
   * *outside* the column and every pixel over the column itself belonged to
   * the panel. The owner reported it as the drag not working, which is what
   * a 3px sliver on a 1103px window feels like by hand.
   *
   * `22` guessed a stacking context between the two. There is none:
   * `.app-shell__right-panels` computes `position: absolute; z-index: auto`,
   * and every ancestor above it is `z-index: auto` with no transform,
   * opacity, filter, isolation or containment. The grip and the panels are
   * **siblings in one stacking context**, and the panel simply carries the
   * larger number — `z-index: 20` against the grip's `1`.
   *
   * The trap is that the panel looks unpositioned. `.panel` is
   * `position: static`, where `z-index` is normally inert — but a flex item
   * with a `z-index` other than `auto` paints as though it were positioned
   * (CSS Flexible Box §painting), and `.app-shell__right-panels > .panel`
   * is a flex item. So the number was live all along and nothing between
   * needed to explain it.
   *
   * Hence a token rather than a literal, and a derived one: a grip sits one
   * step above the surface it resizes, so `--z-panel` moving takes it along.
   * The 7px strip is unchanged and deliberately so — widening it to 9 or
   * 11px would have bought back the same three pixels while eating further
   * into the panel's own content, and the primitive's stated size was never
   * the thing that was wrong.
   */
  const zScale = (): Record<string, string> => {
    const out: Record<string, string> = {};
    for (const match of code(at('design/styles/tokens.css')).matchAll(/(--z-[a-z-]+):\s*([^;]+);/g))
      out[match[1] ?? ''] = (match[2] ?? '').trim();
    return out;
  };

  /** `calc(var(--z-panel) + 1)` → the integer a browser would paint with. */
  const resolve = (scale: Record<string, string>, name: string): number => {
    const raw = scale[name];
    if (raw === undefined) throw new Error(`no ${name} in the z scale`);
    const expanded = raw.replace(/var\((--z-[a-z-]+)\)/g, (_m, ref: string) =>
      String(resolve(scale, ref)),
    );
    const arithmetic = /^calc\(([\d\s+-]+)\)$/.exec(expanded)?.[1] ?? expanded;
    const bare = arithmetic.replace(/\s+/g, '');
    const terms = bare.match(/[+-]?\d+/g);
    if (terms === null || terms.join('') !== bare)
      throw new Error(`${name} is not an integer or a sum of them: ${raw}`);
    return terms.reduce((total, term) => total + Number(term), 0);
  };

  it('declares --z-grip above --z-panel, derived from it rather than guessed', () => {
    const scale = zScale();
    expect(scale['--z-grip']).toMatch(/var\(--z-panel\)/);
    expect(resolve(scale, '--z-grip')).toBeGreaterThan(resolve(scale, '--z-panel'));
  });

  it('spends that token on .grip, so the comparison is between the two names', () => {
    expect(ruleBody(at(GRIP_CSS), '.grip')).toMatch(/z-index:\s*var\(--z-grip\);/);
    expect(ruleBody(at('design/primitives/Panel.css'), '.panel')).toMatch(
      /z-index:\s*var\(--z-panel\);/,
    );
  });
});
