import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { boardTabState, type BoardConfig } from './boardTabs';

/**
 * The fourth state — `team-board-and-gap-reports/18`.
 *
 * `04` gave this tab three: *not configured*, *not available*, and
 * *configured, here are the cards*. The owner met a fourth that nothing could
 * express — **configured, and this server could not open it** — because the
 * extra carrying the driver was missing from an upgrade line. The backend
 * answered `team_board_configured: true`, the tab drew four empty columns,
 * and the real reason arrived as a two-hundred-line traceback in the terminal
 * once per SSE reconnect.
 *
 * Four empty columns under "OSG Engineering" is the claim-versus-state
 * mistake `boardTabs.ts` exists to prevent, in its worst form yet: not *a
 * patrol ran and found nothing*, but *a patrol's findings exist and you are
 * being shown somebody else's empty table*.
 *
 * ## Why the command is a field of its own
 *
 * `osg-agent-experience/83`: a shell command that shares a line with prose is
 * one a reader cannot paste, because the prose reflows around it. The backend
 * puts the command on its own line in the sentence it composes — it is the
 * only thing that knows where the prose ends — and this splits on that
 * newline rather than guessing what a command looks like.
 */

const SRC = fileURLToPath(new URL('../../', import.meta.url));
const TABS_TS = readFileSync(SRC + 'view/board/boardTabs.ts', 'utf8');
const BOARD_TSX = readFileSync(SRC + 'view/board/PatrolBoard.tsx', 'utf8');

const COMMAND = "uv tool install --force 'openstategraph[postgres,server]==0.3.0rc16'";
const SENTENCE = `SOME_VARIABLE is set, but psycopg is not installed —\n${COMMAND}`;

const BROKEN: BoardConfig = {
  teamBoardConfigured: true,
  teamBoardEnvVar: 'SOME_VARIABLE',
  teamBoardError: SENTENCE,
};
const WORKING: BoardConfig = {
  teamBoardConfigured: true,
  teamBoardEnvVar: 'SOME_VARIABLE',
  teamBoardError: null,
};

describe('a configured board this server could not open', () => {
  it('is not a board, however configured it is', () => {
    expect(boardTabState('osgEngineering', BROKEN).kind).toBe('unavailable');
  });

  it('is still a board when nothing went wrong', () => {
    expect(boardTabState('osgEngineering', WORKING).kind).toBe('board');
  });

  it('says the backend sentence rather than a sentence of its own', () => {
    const state = boardTabState('osgEngineering', BROKEN);
    if (state.kind !== 'unavailable') throw new Error('expected unavailable');
    expect(state.body).toContain('SOME_VARIABLE is set, but psycopg is not installed');
  });

  it('carries the install command on a line of its own, whole', () => {
    const state = boardTabState('osgEngineering', BROKEN);
    if (state.kind !== 'unavailable') throw new Error('expected unavailable');
    expect(state.command).toBe(COMMAND);
    // And never inside the prose, where it would wrap.
    expect(state.body).not.toContain('uv tool install');
  });

  it('does not read as "nobody configured one", which is the other state', () => {
    const state = boardTabState('osgEngineering', BROKEN);
    if (state.kind !== 'unavailable') throw new Error('expected unavailable');
    expect(state.title).not.toBe('Not configured');
  });

  it('says a restart is what applies the fix, because the board is opened once', () => {
    const state = boardTabState('osgEngineering', BROKEN);
    if (state.kind !== 'unavailable') throw new Error('expected unavailable');
    expect(state.body.toLowerCase()).toContain('restart');
  });

  it('leaves an error with no command with no command to render', () => {
    const state = boardTabState('osgEngineering', {
      ...BROKEN,
      teamBoardError: 'could not connect to postgresql://***@db:5432/cards',
    });
    if (state.kind !== 'unavailable') throw new Error('expected unavailable');
    expect(state.command).toBeUndefined();
    expect(state.body).toContain('could not connect');
  });

  it('changes neither of the other two tabs', () => {
    for (const config of [BROKEN, WORKING]) {
      expect(boardTabState('workflows', config).kind).toBe('board');
      expect(boardTabState('github', config).kind).toBe('unavailable');
    }
  });

  it('still spells no variable name and no install line of its own', () => {
    // One copy owner, unchanged by this ticket: the backend reads the
    // variable and composes the command, so a literal of either here would be
    // a second spelling that goes stale silently.
    expect(TABS_TS).not.toContain('OPENSTATEGRAPH_');
    expect(TABS_TS).not.toContain('openstategraph[');
    expect(TABS_TS).not.toContain('pip install');
  });

  it('renders the command through the design system, not the view', () => {
    expect(BOARD_TSX).not.toMatch(/\bfetch\(/);
    expect(BOARD_TSX).toContain('state.command');
  });
});
