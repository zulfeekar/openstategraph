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
 */
export function boardTabState(tab: BoardTabId): BoardTabState {
  switch (tab) {
    case 'workflows':
      return { kind: 'board' };
    case 'osgEngineering':
      return {
        kind: 'unavailable',
        title: 'Not configured',
        body:
          'This tab would list what a patrol found in the engineering source a project ' +
          'points at. Nothing points at one yet, so there is nothing to list — and an ' +
          'empty board here would read as a patrol that ran and came back clean.',
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
