import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * One narrow-table grammar, written on three surfaces — `stable-beta-public/15`.
 *
 * A markdown table is the shape a model reaches for first, and until this
 * ticket every container narrower than a panel made a good answer look broken.
 * Measured on the starter's own answer (`gpt-oss:120b`, five rows of
 * *Reason | Explanation*):
 *
 * | | before | after (stacked) |
 * | --- | --- | --- |
 * | chat bubble, table box | 187px visible of 838px scrollable | 187px of 187px — no scroller |
 * | chat bubble, table height | 163px, every cell one clipped line | 580px, every word on screen |
 * | node result, table box | 296px inside a 216px card — clipped | 216px of 216px |
 * | node result, row height | 212px for two nowrap cells | 111px, label line + wrapped text |
 *
 * The two defects were different rules with one cause — a table laid out as a
 * grid in a container too narrow for one. `RichText.css`'s `display: block;
 * overflow-x: auto` is right for a 700px inspector and produced the bubble's
 * cut-off scroller; `typography.css`'s `.prose td:first-child { width: 1%;
 * white-space: nowrap }` is right for an index column and produced the node
 * card's tall empty boxes.
 *
 * So the fix is a modifier, `rich-text--narrow`, set by the two narrow
 * surfaces only — the chat bubble and the node result — and by the customer
 * page's bubble, which restates the rules in its own `<style>` because it is a
 * standalone asset with no build step (the same split `chatBubblesAgree.test.ts`
 * describes). This test reads the stylesheets as text and asserts the rules
 * exist by name on both, that both narrow surfaces actually set the class, and
 * that the wide rule the inspector and the docs depend on is untouched.
 */
const read = (relative: string) =>
  readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf8');

const RICH_TEXT_CSS = read('./RichText.css');
const CHAT_HTML = read('../../../backend/openstategraph/api/static/chat.html');
const ASK_PANEL_TSX = read('../ask/AskPanel.tsx');
const NODE_BODIES_TSX = read('../nodes/nodeBodyRegistry.tsx');

const MODIFIER = 'rich-text--narrow';

/**
 * Every declaration written under a selector naming the modifier, flattened.
 *
 * Selector-agnostic on purpose, exactly as `chatGrammar()` is: the editor
 * hangs the modifier beside `.rich-text` and `.prose`, the customer page
 * beside `.answer`, and insisting on one selector spelling would pin the part
 * that legitimately differs. What must not differ is the set of decisions.
 */
function narrowDeclarations(source: string): string {
  let flattened = '';
  for (const rule of source.matchAll(/([^{}]*)\{([^{}]*)\}/g)) {
    if ((rule[1] ?? '').includes(MODIFIER)) flattened += `${rule[2] ?? ''}\n`;
  }
  return flattened.replace(/\s+/g, ' ');
}

/**
 * The four decisions that turn a grid into something readable in ~200px, each
 * named by the declaration that carries it rather than by its selector:
 *
 * - cells wrap (`white-space: normal`) — the nowrap that made a cell one
 *   clipped line is off, on both the shared rule and `.prose`'s index column;
 * - rows become blocks (`display: block`) — a two-column table stacks, so the
 *   text gets the container's full width instead of a 96px column;
 * - the header row is not drawn in that stacked form (`display: none`) — in a
 *   two-column table the first cell is the label, and a header row stacked
 *   into two bare words is noise;
 * - a table with three or more columns keeps its scroller, with a floor under
 *   each column (`min-width`) so it scrolls rather than crushing to 30px.
 */
const DECISIONS = [
  ['cells wrap', /white-space:\s*normal/],
  ['rows stack', /display:\s*block/],
  ['the stacked header is not drawn', /display:\s*none/],
  ['wide tables keep a readable column floor', /min-width:/],
] as const;

describe('a narrow surface stacks a table instead of scrolling it', () => {
  const editor = narrowDeclarations(RICH_TEXT_CSS);
  const customer = narrowDeclarations(CHAT_HTML);

  it.each(DECISIONS)('%s — the editor stylesheet says so', (_name, pattern) => {
    expect(editor).toMatch(pattern);
  });

  it.each(DECISIONS)('%s — the customer page says so too', (_name, pattern) => {
    expect(customer).toMatch(pattern);
  });

  it('releases the index column the node card was squeezed by', () => {
    // `.prose td:first-child { width: 1% }` is what gave *Reason* 170px of a
    // 216px card. The modifier has to out-specify it, not merely follow it.
    for (const [file, source] of [
      ['RichText.css', RICH_TEXT_CSS],
      ['chat.html', CHAT_HTML],
    ] as const) {
      const rules = [...source.matchAll(/([^{}]*)\{([^{}]*)\}/g)].filter(
        (rule) => (rule[1] ?? '').includes(MODIFIER) && (rule[1] ?? '').includes('first-child'),
      );
      expect(rules.length, `${file} releases td:first-child under the modifier`).toBeGreaterThan(0);
    }
  });
});

describe('the modifier is set by the narrow surfaces and by nobody else', () => {
  // A `className` attribute, not the file's text: the first draft of this
  // asserted `toContain(MODIFIER)` and stayed green with the class stripped
  // off every element, because the comment explaining the modifier names it.
  const applied = new RegExp(`className="[^"]*${MODIFIER}`);

  it('the chat bubble sets it', () => {
    expect(ASK_PANEL_TSX).toMatch(applied);
  });

  it("the node card's result sets it", () => {
    expect(NODE_BODIES_TSX).toMatch(applied);
  });

  it("the customer page's bubble sets it", () => {
    expect(CHAT_HTML).toMatch(new RegExp(`class="answer[^"]*${MODIFIER}`));
  });
});

describe('the wide surfaces keep the rule they were right to have', () => {
  it('`.rich-text table` still scrolls inside its own box', () => {
    const wide = RICH_TEXT_CSS.match(/\.rich-text table\s*\{([^}]*)\}/)?.[1] ?? '';
    expect(wide, 'the unmodified .rich-text table rule exists').not.toBe('');
    expect(wide).toMatch(/display:\s*block/);
    expect(wide).toMatch(/overflow-x:\s*auto/);
    expect(wide).toMatch(/max-width:\s*100%/);
  });

  it('the shared cell rule still holds the inspector to one line per cell', () => {
    // The inspector is 700px wide: a nowrap cell there is a column, not a
    // clipped word. `15` narrows a surface, it does not re-style every table.
    const cells = RICH_TEXT_CSS.match(/\.rich-text th,\s*\.rich-text td\s*\{([^}]*)\}/)?.[1] ?? '';
    expect(cells).toMatch(/white-space:\s*nowrap/);
  });
});
