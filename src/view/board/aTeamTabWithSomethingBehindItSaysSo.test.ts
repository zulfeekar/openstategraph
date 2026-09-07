import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { BOARD_TABS, boardTabState, type BoardConfig } from './boardTabs';

/**
 * `team-board-and-gap-reports/04`. The third state.
 *
 * `aTabThatIsNotBuiltSaysSo.test.ts` beside this one pinned two states and two
 * sentences: *a connection this product supports and nobody has configured*,
 * and *a connection this product does not have yet*. `02` and `03` created a
 * third — **configured, and here are the cards** — and nothing could express
 * it, so the tab went on making a false statement on the surface a maintainer
 * looks at.
 *
 * That older file is deliberately not edited. Its case is the unconfigured
 * one, and the whole claim of this ticket is that the unconfigured answer did
 * not change: `boardTabState` grew an argument with a default, so every
 * existing call reads exactly what it read before.
 *
 * ## Why the sentence names the variable
 *
 * *Not configured* and stopping there is what a maintainer met. `CLAUDE.md`'s
 * Ollama rule is the general form — never reach for a thing without naming a
 * variable someone can set, see and revoke — and the tab is a surface it
 * applies to: the name travels even when nothing is set, because that is
 * exactly when it is needed.
 */

const SRC = fileURLToPath(new URL('../../', import.meta.url));
const BOARD_TSX = readFileSync(SRC + 'view/board/PatrolBoard.tsx', 'utf8');
const TABS_TS = readFileSync(SRC + 'view/board/boardTabs.ts', 'utf8');

const UNSET: BoardConfig = { teamBoardConfigured: false, teamBoardEnvVar: 'SOME_VARIABLE' };
const SET: BoardConfig = { teamBoardConfigured: true, teamBoardEnvVar: 'SOME_VARIABLE' };

describe('the team tab, once something points at a board', () => {
  it('is a board when the backend says one is configured', () => {
    expect(boardTabState('osgEngineering', SET).kind).toBe('board');
  });

  it('is still exactly the old sentence when nothing is', () => {
    const state = boardTabState('osgEngineering', UNSET);
    expect(state.kind).toBe('unavailable');
    if (state.kind !== 'unavailable') return;
    expect(state.title).toBe('Not configured');
  });

  it('defaults to unconfigured, so a caller that asks nothing is told nothing new', () => {
    // The reason `aTabThatIsNotBuiltSaysSo.test.ts` needed no edit: a missing
    // answer is not an optimistic one. A board that rendered four empty
    // columns while the fact was still in flight would be the claim-versus-
    // state confusion this pair of tests exists to prevent.
    expect(boardTabState('osgEngineering').kind).toBe('unavailable');
  });

  it('names the variable to set, in the sentence a maintainer reads', () => {
    const state = boardTabState('osgEngineering', UNSET);
    expect(state.kind).toBe('unavailable');
    if (state.kind !== 'unavailable') return;
    expect(state.body).toContain('SOME_VARIABLE');
  });

  it('changes nothing about the other two tabs', () => {
    // Workflows is a board however the environment is set; GitHub is not a
    // board however the environment is set. Configuration moves exactly one
    // of the three, which is what makes it a *state* of that tab rather than
    // a mode of the board.
    for (const config of [UNSET, SET]) {
      expect(boardTabState('workflows', config).kind).toBe('board');
      expect(boardTabState('github', config).kind).toBe('unavailable');
    }
  });

  it('still promises no integration this product does not have', () => {
    // The scope line, restated because this ticket is the one that could
    // break it: the tab learns about the store through the same client the
    // Workflows tab uses, never by reaching out of the view.
    expect(BOARD_TSX).not.toMatch(/\bfetch\(/);
    expect(BOARD_TSX).not.toContain('supabase');
    expect(BOARD_TSX).not.toMatch(/api\.github\.com/);
  });

  it('spells no variable name of its own', () => {
    // One copy owner. The name is the backend's answer — it is the backend
    // that reads the variable — so a literal here would be a second spelling
    // that goes stale the day the variable is renamed, silently, in the one
    // sentence whose whole job is to be actionable.
    expect(TABS_TS).not.toContain('OPENSTATEGRAPH_');
  });

  it('keeps the tabs themselves in the settled order', () => {
    expect(BOARD_TABS.map((tab) => tab.label)).toEqual(['Workflows', 'OSG Engineering', 'GitHub']);
  });
});
