import type { TabDefinition } from '@design/primitives';

/**
 * The board's three tabs — `kanban-patrol/06`.
 *
 * ## Why this is not in `patrolBoardModel`
 *
 * It was, and that module had five reasons to change: a column, a tab, a
 * priority level, the card's shape and the board's copy. A tab and a column
 * are unrelated axes — one is *which source of findings you are looking at*,
 * the other is *what a finding needs next* — and they will move for different
 * reasons and at different times. Splitting them is the smallest honest cut.
 */

export type BoardTabId = 'workflows' | 'osgEngineering' | 'github';

export const BOARD_TABS: readonly TabDefinition<BoardTabId>[] = [
  { id: 'workflows', label: 'Workflows' },
  { id: 'osgEngineering', label: 'OSG Engineering' },
  { id: 'github', label: 'GitHub' },
];

export type BoardTabState =
  | { readonly kind: 'board' }
  | { readonly kind: 'unavailable'; readonly title: string; readonly body: string };

/**
 * What the backend said about the environment it is running in —
 * `team-board-and-gap-reports/04`.
 *
 * Two fields, both from `GET /api/health`, and the second is the **name** of
 * a variable rather than its value: the variable holds a URI with a password
 * in it, and what this surface needs is something a maintainer can be told to
 * set. Nothing here spells the name itself — one copy owner, and the owner is
 * the process that actually reads the variable.
 */
export interface BoardConfig {
  readonly teamBoardConfigured: boolean;
  readonly teamBoardEnvVar: string;
}

/**
 * What a tab is worth before the backend has answered.
 *
 * Not an optimistic guess: a board that drew four empty columns while the
 * fact was still in flight would make the claim-versus-state mistake this
 * module exists to avoid, one beat before making the right one. The variable
 * name is empty because nothing has said one, and the sentence below is
 * written to survive that.
 */
const UNANSWERED: BoardConfig = { teamBoardConfigured: false, teamBoardEnvVar: '' };

/**
 * What a tab has behind it.
 *
 * Two of the three have nothing, and saying so is the point. Four empty
 * columns under a heading is a board that **ran and found nothing** — a
 * different claim from a board that cannot run, and the more reassuring of the
 * two. `ArrivalDialog` records the same distinction in its own words: *"no
 * workflows" and "could not ask" are two very different states and one
 * appearance is how 27 was reported*.
 *
 * The two sentences differ because the two states differ. One is a connection
 * this product supports and nobody has configured; the other is a connection
 * this product does not have yet.
 *
 * ## And a third state, since `team-board-and-gap-reports/04`
 *
 * *Configured, and here are the cards.* `02` and `03` made something able to
 * point at a shared board, so this is a function of **state** and not of the
 * tab id alone — two of the three tabs can be `board`, and which ones depends
 * on configuration. `github` is the one that cannot, whatever the environment
 * says, because no store exists behind it.
 *
 * The argument has a default, which is why the older test needed no edit: an
 * unanswered question reads as unconfigured, and the unconfigured answer is
 * word for word the one it always was, plus the variable to set.
 */
export function boardTabState(tab: BoardTabId, config: BoardConfig = UNANSWERED): BoardTabState {
  switch (tab) {
    case 'workflows':
      return { kind: 'board' };
    case 'osgEngineering':
      if (config.teamBoardConfigured) return { kind: 'board' };
      return {
        kind: 'unavailable',
        title: 'Not configured',
        body:
          'This tab would list what a patrol found in the engineering source a project ' +
          'points at. Nothing points at one yet, so there is nothing to list — and an ' +
          'empty board here would read as a patrol that ran and came back clean.' +
          // The half that makes the sentence actionable — `CLAUDE.md`'s Ollama
          // rule on a surface: never leave a maintainer with "not configured"
          // and no name to configure. Appended rather than woven in, so the
          // original sentence stays the sentence its own test pins, and
          // omitted when nothing has told us the name yet rather than
          // inventing one.
          (config.teamBoardEnvVar ? ` Set ${config.teamBoardEnvVar} and restart to use one.` : ''),
      };
    case 'github':
      return {
        kind: 'unavailable',
        title: 'Not available',
        body:
          'This product has no GitHub connection yet. When it has one, this tab shows ' +
          'what the patrol found there; until then it shows this, because four empty ' +
          'columns would be a claim rather than a state.',
      };
  }
}
