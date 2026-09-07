import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { BOARD_COLUMNS, cardsInColumn, type BoardCard } from './patrolBoardModel';

/**
 * `kanban-patrol/06`, and the two claims in it that are not decoration.
 *
 * ## One tone map, read twice
 *
 * `04` settled the words and the tones: `Detected` → `neutral`, `Needs You` →
 * `danger`, `In Progress` → `accent`, `Resolved` → `success`. Four columns
 * onto `Badge`'s four existing tones, which is how the board mints **zero new
 * colour tokens** — the owner's stated non-negotiable.
 *
 * `04`'s last line is the one with a failure mode: *"the mapping lives in one
 * place both the header and the card read, so a column cannot be `danger` in
 * one and `accent` in the other."* Two spellings of one fact agree on the day
 * they are written. The header badge and the in-card dot are two sites, so the
 * checks below pin that neither site holds a colour of its own — and that the
 * board's own stylesheet holds none either, which is the third site and the
 * one where a new token would actually get minted.
 *
 * **The in-card dot is `StatusDot`, not a span this feature colours in.** It
 * is the same decision `04` made one layer up: the product already has a
 * status-colour vocabulary, and a board that drew its own dots would be a
 * fifth opinion about what red means. The row carries both names because they
 * are two vocabularies — `Badge`'s four tones and `StatusDot`'s seven — and
 * the point of `04`'s rule is that they are chosen **together, once**, not
 * that only one of them exists.
 *
 * ## A board that re-sorts under the pointer is a board nobody can click
 *
 * Cards arrive one at a time while a patrol runs. The natural thing to write
 * is *newest first*, which is a sort on a value that changes — and a sort on
 * arrival means every landing card shoves the row under the reader's cursor
 * down by one. So the order is the order cards were given, an append-only
 * list, and the checks below are behavioural rather than a grep: the third one
 * fails on a sort key nothing else notices.
 */

const SRC = fileURLToPath(new URL('../../', import.meta.url));
const read = (relative: string): string => readFileSync(SRC + relative, 'utf8');

/**
 * Every view file in the feature, not just the shell.
 *
 * The board was one component; it is now three — the shell, the column and
 * the card — because a card is about to grow an action and six jobs in one
 * function is the god component this repository refuses. The rules below are
 * unchanged; what changed is that a rule about *no site spelling a colour*
 * now has three sites to check, and naming them individually is how one of
 * them silently stops being checked. `VIEW_SOURCES` is the union, and
 * `VIEW_TSX` is it concatenated for the "somewhere in the feature" claims.
 */
const VIEW_FILES = [
  'view/board/PatrolBoard.tsx',
  'view/board/PatrolColumn.tsx',
  'view/board/PatrolCard.tsx',
] as const;
const VIEW_SOURCES = VIEW_FILES.map((file) => [file, read(file)] as const);
const VIEW_TSX = VIEW_SOURCES.map(([, source]) => source).join('\n');
const BOARD_TS = read('view/board/patrolBoardModel.ts');
/** Comments out: this file forbids words, and a stylesheet may explain itself. */
const BOARD_CSS = read('view/board/PatrolBoard.css').replace(/\/\*[\s\S]*?\*\//g, '');

const card = (over: Partial<BoardCard> & Pick<BoardCard, 'id'>): BoardCard => ({
  title: 'A tool call with no timeout',
  secondary: 'chinook-assistant · answer',
  kind: 'bug',
  lifecycle: 'open',
  when: '2m ago',
  priority: 'med',
  area: 'backend',
  ...over,
});

describe('four columns, four tones, and one place that says which', () => {
  it('is the table `04` settled — the words, the badge tone and the dot, per row', () => {
    // One assertion over the whole table rather than three passes over it: a
    // row is the unit that has to stay coherent, and splitting the check is
    // how `danger` in the header and `success` on the dot become possible.
    expect(BOARD_COLUMNS.map(({ label, tone, dot }) => [label, tone, dot])).toEqual([
      ['Detected', 'neutral', 'idle'],
      ['Needs You', 'danger', 'error'],
      ['In Progress', 'accent', 'running'],
      ['Resolved', 'success', 'success'],
    ]);
  });

  it('spends each of `Badge`’s four existing tones exactly once', () => {
    // Once each is what makes the mapping free of new colour: a tone used
    // twice would leave one column with nowhere to go but a new token.
    expect(new Set(BOARD_COLUMNS.map((column) => column.tone)).size).toBe(BOARD_COLUMNS.length);
    expect(new Set(BOARD_COLUMNS.map((column) => column.dot)).size).toBe(BOARD_COLUMNS.length);
  });

  it('hands both names to the primitives rather than restating either', () => {
    expect(VIEW_TSX).toContain('<Badge');
    expect(VIEW_TSX).toContain('tone={column.tone}');
    expect(VIEW_TSX).toContain('<StatusDot');
    expect(VIEW_TSX).toContain('tone={column.dot}');
  });

  it('lets no site spell a colour name of its own', () => {
    // The whole defect in one assertion: a literal at either site is a second
    // opinion about a column's colour, and it agrees with the map until
    // somebody edits one of the two. The stylesheet is included because it is
    // where a new token would be minted rather than merely referenced.
    for (const { tone, dot } of BOARD_COLUMNS) {
      // Per file rather than over the concatenation: a claim about "every
      // site" that is asserted against one joined string still passes when a
      // fourth file is added and never read.
      for (const [file, source] of VIEW_SOURCES) {
        expect(source, `${file} spells the tone ${tone}`).not.toContain(`'${tone}'`);
        expect(source, `${file} spells the dot ${dot}`).not.toContain(`'${dot}'`);
      }
      expect(BOARD_CSS, `PatrolBoard.css names ${tone}`).not.toContain(tone);
      expect(BOARD_CSS, `PatrolBoard.css names ${dot}`).not.toContain(dot);
    }
  });

  it('names only colour roles in its stylesheet, and no palette ramp', () => {
    // `tokensDoNotDriftBack` already forbids a hex. This forbids the step
    // below it — reaching past the role layer into `--neutral-500` or
    // `--green-50`, which is a colour decision wearing a token's clothes.
    const colours = [
      ...BOARD_CSS.matchAll(/(?:^|\n)\s*(?:background|color|fill):\s*([^;]+);/g),
    ].map((match) => (match[1] ?? '').trim());
    expect(colours.length).toBeGreaterThan(0);
    expect(colours.filter((value) => !/^var\(--color-[a-z-]+\)$/.test(value))).toEqual([]);
  });
});

describe('a card that lands does not move the card under the pointer', () => {
  const cards: readonly BoardCard[] = [
    card({ id: 'a', when: '9m ago' }),
    card({ id: 'b', when: '2m ago' }),
    card({ id: 'c', kind: 'grilling' }),
    card({ id: 'd', when: '40m ago' }),
  ];

  it('returns a column’s cards in the order it was given them', () => {
    expect(cardsInColumn(cards, 'detected').map((c) => c.id)).toEqual(['a', 'b', 'd']);
    expect(cardsInColumn(cards, 'needsYou').map((c) => c.id)).toEqual(['c']);
    expect(cardsInColumn(cards, 'resolved')).toEqual([]);
  });

  it('appends an arriving card rather than inserting it', () => {
    const before = cardsInColumn(cards, 'detected').map((c) => c.id);
    const after = cardsInColumn([...cards, card({ id: 'e', when: 'just now' })], 'detected');
    // A prefix, exactly. This is the property that makes the board clickable
    // while a patrol runs: whatever was under the pointer is still there.
    expect(after.map((c) => c.id).slice(0, before.length)).toEqual(before);
    expect(after.map((c) => c.id)).toEqual([...before, 'e']);
  });

  it('does not reorder when the thing it might have sorted on changes', () => {
    // Every card ages, and the relative timestamp is the field a "newest
    // first" implementation reads. Re-word all four and the order must not
    // move a row.
    const aged = cards.map((c) => ({ ...c, when: 'an hour ago' }));
    expect(cardsInColumn(aged, 'detected').map((c) => c.id)).toEqual(
      cardsInColumn(cards, 'detected').map((c) => c.id),
    );
  });

  it('sorts nowhere, in the model or in the component', () => {
    // The behavioural checks above pass for a sort that happens to be stable
    // on this fixture. This one is about the shape: there is no ordering
    // decision in this feature to get wrong.
    expect(BOARD_TS).not.toContain('.sort(');
    for (const [file, source] of VIEW_SOURCES) {
      expect(source, `${file} sorts`).not.toContain('.sort(');
    }
  });

  it('is the function the board actually renders through', () => {
    // A model nothing calls is a model that guards nothing — the ratchet
    // written against a spelling the code does not use.
    expect(VIEW_TSX).toContain('cardsInColumn(');
    // And keyed by identity rather than by index, or React reuses the row a
    // card just left.
    expect(VIEW_TSX).toContain('key={card.id}');
  });
});
