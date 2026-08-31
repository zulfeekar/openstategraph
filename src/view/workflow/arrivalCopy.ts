import { relativeTime } from '@core/runtime/pastRunView';
import type { ArrivalChoice } from '@core/runtime/arrivalChoices';

/**
 * What the arrival offer says — `install-experience` 28.
 *
 * Held apart from the two components that show it for the reason
 * `emptyStateCopy.ts` is held apart from the canvas: a string inside JSX has
 * no way to fail, and these sentences make promises the rest of the product
 * has to keep. Both surfaces read from here, so the dialog and the start panel
 * cannot come to call the same things by different names.
 */

export const ARRIVAL_TITLE = 'Open a workflow';

/**
 * The subtitle names **both** clocks the list is sorted by, because the order
 * is otherwise unarguable: one of the two is a fact only this browser holds,
 * and a reader who cannot see why a row is first has no way to tell a sensible
 * order from a broken one. `arrivalChoices` carries the long version.
 */
export const ARRIVAL_SUBTITLE =
  'The workflows in this project, most recently opened or edited first.';

export const ARRIVAL_EMPTY_TITLE = 'No workflows in this project yet';

/**
 * What an empty project is told. It says where the folder is — the same fact
 * every row prints — so the answer to *"is it really empty?"* is a directory a
 * reader can look in, not a claim they have to take.
 *
 * It deliberately does not describe naming or renaming. The slug is minted by
 * the backend at first save and frozen, and a sentence here implying a folder
 * follows a rename would be the misdirection `say-it-on-the-surface` 03
 * removed from five other surfaces.
 */
export const ARRIVAL_EMPTY_HINT =
  'Nothing has been saved to the workflows folder. Start one and the first save asks what to call it.';

export const ARRIVAL_NEW = 'New workflow';

/**
 * The dismissal, worded as what it does. *Cancel* would suggest something was
 * under way and is being abandoned; nothing is. Dismissing selects nothing and
 * leaves the canvas exactly as it arrived — with the start panel on it.
 */
export const ARRIVAL_DISMISS = 'Not now';

/** Said under the buttons, so the dismissal's consequence is not a surprise. */
export const ARRIVAL_DISMISS_HINT = 'Nothing opens until you pick one.';

export const START_PANEL_START = 'Start';
export const START_PANEL_RECENT = 'Recent';
export const START_PANEL_OPEN = 'Open…';

/** What *Recent* says when the project holds nothing to be recent about. */
export const START_PANEL_NO_RECENT = 'No workflows in this project yet.';

/**
 * One row's provenance line — which clock put it where it is, and how long ago.
 *
 * `relativeTime` is the shared formatter rather than a second one written here:
 * a past run and a workflow both age, and two spellings of *"2 h ago"* on one
 * screen is the duplication of knowledge this repository names.
 */
export function arrivalRecencyLine(choice: ArrivalChoice, now: number): string {
  if (choice.from === 'never') return 'Not opened in this browser';
  const when = relativeTime(choice.at, now);
  return `${choice.from === 'opened' ? 'Opened' : 'Edited'} ${when}`;
}
