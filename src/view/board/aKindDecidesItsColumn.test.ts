import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { BOARD_COLUMNS } from './patrolBoardModel';
import { CARD_KINDS, columnForCard, columnForKind, isHumanDecision } from './cardKind';

/**
 * `kanban-patrol/18`. A card is a ticket, and its **kind** decides which
 * column it sits in.
 *
 * ## The defect this forbids
 *
 * If a patrol chose a kind *and* a column, it could file a `grilling` — a
 * question only the owner may answer — into **Detected**, which is the column
 * an agent pulls work from. The agent would then answer a judgement that was
 * never its to make, unattended, and nothing would have refused it.
 *
 * The fix is that the column is not stored. It is derived, by one function,
 * from the kind. This file pins that derivation and the property that makes it
 * safe: the two groups **partition** the kinds — every kind lands in exactly
 * one column, none lands in neither, none in both.
 *
 * ## Why a partition rather than a lookup test
 *
 * A per-kind assertion passes for a table with a missing row: the kind simply
 * is not asserted about. The partition is the claim that cannot be satisfied
 * by omission, which is the shape a "does every X do Y" test needs here — the
 * same reason a structural claim in this repository is tested per function
 * rather than per file.
 */

const SRC = fileURLToPath(new URL('../../', import.meta.url));
const read = (relative: string): string => readFileSync(SRC + relative, 'utf8');

describe('a kind decides a column, and nothing else does', () => {
  it('maps every kind to a column that exists', () => {
    const columns = new Set(BOARD_COLUMNS.map((column) => column.id));
    for (const kind of CARD_KINDS) {
      expect(columns, `${kind} maps to a real column`).toContain(columnForKind(kind));
    }
  });

  it('partitions the kinds — every one is human-decided or agent-takeable, never both or neither', () => {
    const human = CARD_KINDS.filter((kind) => isHumanDecision(kind));
    const agent = CARD_KINDS.filter((kind) => !isHumanDecision(kind));

    // Neither group may be empty, or the board has a column nothing reaches.
    expect(human.length).toBeGreaterThan(0);
    expect(agent.length).toBeGreaterThan(0);
    // The partition itself: the two groups reconstruct the whole set exactly.
    expect([...human, ...agent].sort()).toEqual([...CARD_KINDS].sort());
  });

  it('sends every human-decided kind to Needs You and no other', () => {
    for (const kind of CARD_KINDS.filter((k) => isHumanDecision(k))) {
      expect(columnForKind(kind), `${kind} is a judgement`).toBe('needsYou');
    }
  });

  it('sends every agent-takeable kind to Detected and no other', () => {
    // Detected is the column `16`'s `claim_card` pulls from. A judgement
    // reaching it is the whole defect, so this is the assertion that matters.
    for (const kind of CARD_KINDS.filter((k) => !isHumanDecision(k))) {
      expect(columnForKind(kind), `${kind} is takeable`).toBe('detected');
    }
  });

  it('never derives a column a patrol is not allowed to open a card in', () => {
    // In Progress and Resolved are *reached*, never *filed into*: one means an
    // actor claimed it, the other carries evidence. A patrol that could open a
    // card directly into Resolved would close work nobody did.
    const opened = new Set(CARD_KINDS.map(columnForKind));
    expect(opened.has('inProgress')).toBe(false);
    expect(opened.has('resolved')).toBe(false);
  });

  it('is derived, not stored — no card carries a column of its own', () => {
    // The structural half. A `column` field on the card would let a caller
    // disagree with `columnForKind`, and the disagreement would be silent.
    const model = read('view/board/patrolBoardModel.ts').replace(/\/\*[\s\S]*?\*\//g, '');
    expect(model).not.toMatch(/^\s*readonly column:/m);
  });
});

describe('lifecycle outranks kind, which is what makes four columns reachable', () => {
  it('sends a resolved card to Resolved whatever kind it was', () => {
    for (const kind of CARD_KINDS) {
      expect(columnForCard({ kind, lifecycle: 'resolved' })).toBe('resolved');
    }
  });

  it('sends a claimed card to In Progress whatever kind it was', () => {
    // Including a `grilling`. A claimed judgement leaves Needs You precisely
    // so a second person does not start answering it too.
    for (const kind of CARD_KINDS) {
      expect(columnForCard({ kind, lifecycle: 'claimed' })).toBe('inProgress');
    }
  });

  it('leaves an open card wherever its kind opens it', () => {
    for (const kind of CARD_KINDS) {
      expect(columnForCard({ kind, lifecycle: 'open' })).toBe(columnForKind(kind));
    }
  });

  it('reaches all four columns and no more', () => {
    // The property the first shape of this feature failed: with the column
    // derived from kind alone, In Progress and Resolved were unreachable —
    // two of the four columns could never hold a card.
    const reachable = new Set(
      CARD_KINDS.flatMap((kind) =>
        (['open', 'claimed', 'resolved'] as const).map((lifecycle) =>
          columnForCard({ kind, lifecycle }),
        ),
      ),
    );
    expect([...reachable].sort()).toEqual(['detected', 'inProgress', 'needsYou', 'resolved']);
  });
});
