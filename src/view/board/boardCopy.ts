/**
 * Every word the board says — `kanban-patrol/06`.
 *
 * ## Why the strings are their own module
 *
 * They change for a different reason, at a different rate, and often by a
 * different person than anything else in this feature. A reword is not a
 * structural change, and a structural change should not require reading past
 * five sentences of product copy to reach the table it moves.
 */

export const BOARD_TITLE = 'Patrol';
export const BOARD_SUBTITLE = 'What the last patrol found, by what it needs next.';

/**
 * The blank board, which is the first thing most people will see.
 *
 * The owner's reading of it: *I'll see a blank screen, meaning no patrol has
 * run.* So it says that, and carries the one action that changes it — the
 * shape `.canvas-empty` and `StartPanel` already settled on for this product
 * (`install-experience/28`): a state nobody has reached yet is guidance, not
 * an error and not nothing.
 */
export const BOARD_EMPTY_TITLE = 'No patrol has run yet';
export const BOARD_EMPTY_BODY =
  'This board is blank because nothing has looked at the project, not because ' +
  'everything is clean. Start a patrol and cards land here one at a time as it finds them.';
export const BOARD_PATROL_ACTION = 'Run patrol';
