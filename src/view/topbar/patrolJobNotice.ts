import type { PatrolStatus } from '@core/runtime/RuntimeClient';

/**
 * What the toolbar says about a background job that is running right now —
 * `kanban-patrol/10`.
 *
 * ## Why a chip at all
 *
 * A patrol keeps working after the board is dismissed, and the ticket's brief
 * is exactly that: *"there must be a good UX way to show a background job
 * running so user is aware of that."* A dialog the user closed cannot be that
 * signal, and neither can a toast — `save.marker`'s own comment records the
 * lesson, a toast fades in five seconds and a patrol runs for minutes.
 *
 * ## The states, and what each one renders
 *
 * | `status` | Means | Renders |
 * | --- | --- | --- |
 * | `running` | a patrol is working now | the chip |
 * | `finished` | it stopped, successfully | **nothing** |
 * | `failed` | it stopped, badly | **nothing** |
 * | `idle` / `null` | nothing has run, or nobody has asked yet | **nothing** |
 *
 * **The `failed` row is the whole reason this is a table.** It is the row that
 * gets forgotten, and forgetting it is not a cosmetic bug: the chip would keep
 * claiming a job is running long after the job has died, which the ticket
 * names as worse than having no chip. `finished` and `failed` differ in every
 * other way and are identical here — the chip's question is *is something
 * running*, and the answer to that is no in both.
 *
 * The chip therefore says nothing about **outcome**. That is
 * `patrolStatusLine`'s job, on the board, where there is room for a sentence
 * and a reader who came to look. Two surfaces, two questions, no duplicate
 * copy: this one is *live or not*, and it is silent the rest of the time for
 * the same reason `staleEditorNotice` is — a permanent chip reading "no patrol
 * running" is a fifth thing to ignore on every glance.
 *
 * ## Not a second source of truth
 *
 * Pure, and derived from the status the SSE stream last published. No timer,
 * no poll, no local "started at" of its own — the only way a chip can outlive
 * its job is by believing something the server never said.
 */
export interface PatrolJobNotice {
  /** The chip's word — short, because it sits in a toolbar. */
  readonly label: string;
  /** The whole sentence, as the badge's explanation. */
  readonly hint: string;
}

export function patrolJobNotice(status: PatrolStatus | null): PatrolJobNotice | null {
  if (status?.status !== 'running') return null;
  return {
    label: 'Patrol running',
    hint:
      'A patrol is scanning this project’s recorded runs and filing anything new to the ' +
      'board. It keeps going with the board closed; this mark disappears when it stops.',
  };
}
