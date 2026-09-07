import type { BoardCard } from './patrolBoardModel';

/**
 * Cards to draw the shell against — `kanban-patrol/06`.
 *
 * **A fixture, deliberately, and it does not wait on `02`.** The real card
 * schema is `kanban-patrol/02` and it is still open; the shell's job is
 * columns, the dialog variant and the two states, none of which depend on a
 * finding's final field list. When `02` lands, this file is what gets
 * deleted — nothing in `PatrolBoard` reads it, because the board takes its
 * cards as a prop and this is only the default.
 *
 * The contents are shaped to make the layout answerable rather than to be
 * plausible data: one column carrying several cards (so the scroll and the
 * sticky header have something to do), one carrying a single card, and one
 * carrying none (so an empty column is visibly an empty column and not a
 * broken one).
 */
export const PATROL_BOARD_FIXTURE: readonly BoardCard[] = [
  {
    id: 'f-1',
    title: 'A tool call with no timeout',
    secondary: 'chinook-assistant · answer',
    kind: 'bug',
    lifecycle: 'open',
    when: '2m ago',
    priority: 'med',
    area: 'backend',
  },
  {
    id: 'f-2',
    title: 'Two nodes write the same state key',
    secondary: 'chinook-assistant · summarise, classify',
    kind: 'bug',
    lifecycle: 'open',
    when: '2m ago',
    priority: 'high',
    area: 'backend',
  },
  {
    id: 'f-3',
    title: 'A model is named that no provider is configured for',
    secondary: 'support-triage · draft-reply',
    kind: 'bug',
    lifecycle: 'open',
    when: '11m ago',
    priority: 'high',
    area: 'backend',
  },
  {
    id: 'f-4',
    title: 'A credential would be sent to an unvalidated server',
    secondary: 'support-triage · lookup-order',
    kind: 'grilling',
    lifecycle: 'open',
    when: '11m ago',
    priority: 'high',
    area: 'backend',
  },
  {
    id: 'f-5',
    title: 'A branch has no path back to the end',
    secondary: 'release-notes · decide',
    kind: 'grilling',
    lifecycle: 'open',
    when: '38m ago',
    priority: 'med',
    area: 'ux',
  },
  {
    id: 'f-6',
    title: 'The step budget is lower than the longest path',
    secondary: 'release-notes · compile',
    kind: 'task',
    lifecycle: 'claimed',
    when: 'an hour ago',
    priority: 'low',
    area: 'test',
  },
];
