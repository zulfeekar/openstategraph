import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { BOARD_EMPTY_BODY, BOARD_EMPTY_TITLE, BOARD_PATROL_ACTION } from './boardCopy';
// The tabs are their own axis and their own module — a tab and a column move
// for different reasons, so they no longer share a file.
import { BOARD_TABS, boardTabState } from './boardTabs';

/**
 * `kanban-patrol/06`. Two of the three tabs are not built, and the empty
 * state is the first thing most people will see.
 *
 * ## A tab that is not built says so
 *
 * `Workflows` has content. `OSG Engineering` and `GitHub` do not, and neither
 * has an integration behind it — those are separate tickets. The failure worth
 * a test is the **plausible** one: four empty columns under a heading is a
 * board that has run and found nothing, which is a different claim from a
 * board that cannot run at all. `ArrivalDialog` already carries this
 * distinction in its own comment — *"no workflows" and "could not ask" are two
 * very different states and one appearance is how 27 was reported* — and this
 * is the same sentence one surface along.
 *
 * ## The empty state offers the patrol
 *
 * The owner's words: *I'll see a blank screen, meaning no patrol has run.* The
 * repository's answer to that shape is `.canvas-empty`, which offers **New
 * workflow** and **Recent** rather than showing nothing, and `install-
 * experience/28` is the ticket that decided it. So the blank board says what
 * blank means and carries the one action that changes it.
 *
 * `boardTabState` is a pure function so this runs, rather than a regex over
 * JSX that passes on the day prettier re-wraps a line.
 */

const SRC = fileURLToPath(new URL('../../', import.meta.url));
const BOARD_TSX = readFileSync(SRC + 'view/board/PatrolBoard.tsx', 'utf8');

describe('three tabs, and only one of them has anything behind it', () => {
  it('names them in the settled order', () => {
    expect(BOARD_TABS.map((tab) => tab.label)).toEqual(['Workflows', 'OSG Engineering', 'GitHub']);
  });

  it('gives the two unbuilt tabs a state that is not a board', () => {
    expect(boardTabState('osgEngineering').kind).toBe('unavailable');
    expect(boardTabState('github').kind).toBe('unavailable');
    expect(boardTabState('workflows').kind).toBe('board');
  });

  it('says which of the two things it is, in a sentence, per tab', () => {
    const engineering = boardTabState('osgEngineering');
    const github = boardTabState('github');
    expect(engineering.kind).toBe('unavailable');
    expect(github.kind).toBe('unavailable');
    if (engineering.kind !== 'unavailable' || github.kind !== 'unavailable') return;
    // Two tabs, two reasons, and not one shared shrug. "Not configured" and
    // "not available" are different answers and the reader is owed the right
    // one.
    expect(engineering.title).not.toBe(github.title);
    expect(engineering.body.length).toBeGreaterThan(40);
    expect(github.body.length).toBeGreaterThan(40);
  });

  it('promises no integration this product does not have', () => {
    // The scope line in the ticket, made checkable. A tab that talks about
    // fetching, connecting or authorising is a tab somebody will wire up
    // against copy rather than against a decision.
    expect(BOARD_TSX).not.toMatch(/\bfetch\(/);
    expect(BOARD_TSX).not.toContain('supabase');
    expect(BOARD_TSX).not.toMatch(/api\.github\.com/);
  });
});

describe('a blank board says what blank means', () => {
  it('names the state rather than showing four empty columns', () => {
    expect(BOARD_EMPTY_TITLE).toMatch(/patrol/i);
    // The owner's own reading of the screen: blank means nothing has looked.
    expect(BOARD_EMPTY_BODY.length).toBeGreaterThan(40);
  });

  it('carries the action that changes it, the way the blank canvas does', () => {
    expect(BOARD_PATROL_ACTION.length).toBeGreaterThan(0);
    expect(BOARD_TSX).toContain('BOARD_PATROL_ACTION');
    expect(BOARD_TSX).toContain('BOARD_EMPTY_TITLE');
    // Wired to the caller's callback, not to a stub inside the view. Running
    // a patrol for real is another ticket; pretending to is a defect.
    expect(BOARD_TSX).toContain('onClick={onPatrol}');
  });

  it('shows the empty state instead of the columns, not beside them', () => {
    // Four headers reading `0` above the sentence "no patrol has run" is the
    // same contradiction the tabs check above is about.
    expect(BOARD_TSX).toContain('cards.length === 0');
  });
});
