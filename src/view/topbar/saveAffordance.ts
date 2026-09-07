import { getOpenAddress } from '@app/openAddress';
import { getOpenSlug } from '@app/openWorkflow';
import { BLIND_AFTER_FAILED_POLLS, getWatchReach, type WatchReach } from '@app/workflowFileWatch';
import { formatMountAddress, isInstance } from '@core/model/MountAddress';

/**
 * What the toolbar's Save says about itself, before it is pressed.
 *
 * `say-it-on-the-surface` 01: the defect was never only that Save was hard to
 * find — it was that nothing on screen said whether this document is on disk.
 * Autosave is browser-local, so "my work is somewhere" and "my work is in
 * `workflows/<slug>/`" are different facts and only one of them survives
 * clearing a browser profile.
 *
 * The three acts of `saveWorkflow` produce three different promises, and a
 * button that made one promise while performing another would be worse than
 * the missing button. So the label and the sentence are derived from the same
 * state the act reads — never written twice.
 *
 * Pure and DOM-free so it can be tested without a toolbar; the tooltip and the
 * label are the whole surface.
 */

export interface SaveAffordance {
  /** The button's word. Short — the sentence lives in the tooltip. */
  readonly label: string;
  /** The tooltip: what pressing this will do, in full. */
  readonly hint: string;
  /**
   * True when this document has no folder on the backend yet. The toolbar
   * marks it, because "not on disk" is the state a user cannot otherwise see.
   */
  readonly unsaved: boolean;
  /**
   * True when the file watch has not been able to reach the backend for
   * `BLIND_AFTER_FAILED_POLLS` checks running (`say-it-on-the-surface/07`).
   *
   * Not a reason to disable Save, and deliberately not wired to one. Saving
   * while the backend is briefly unreachable is a normal thing a person does,
   * and the save path already fails honestly rather than half-writing. What
   * the ticket asks for is that the affordance *reflect* reality — so the
   * sentence stops making a claim about a folder nothing can currently see,
   * and the button carries a mark.
   */
  readonly unreachable: boolean;
  /**
   * The single mark on the button, or none.
   *
   * One element, not two: the dot already means "no folder yet", and two dots
   * on one button is a worse answer than one. `unreachable` wins the tie
   * because it is the fact nothing else on screen carries — "not on disk" is
   * also legible from the hint and from an empty address bar.
   */
  readonly marker: 'unsaved' | 'unreachable' | null;
}

/**
 * What Save appends when the watch cannot see. Additive: it never replaces
 * what the act does, only the confidence about what is at the other end.
 */
function unreachableNote(): string {
  return (
    ` Cannot reach the backend — nothing has answered for ${BLIND_AFTER_FAILED_POLLS} checks in a row,` +
    ' so this cannot say what is there right now. Saving still works the moment it answers.'
  );
}

export function saveAffordance(
  address = getOpenAddress(),
  slug = getOpenSlug(),
  reach: WatchReach = getWatchReach(),
): SaveAffordance {
  const blind = reach.blind;
  const note = blind ? unreachableNote() : '';
  if (address && isInstance(address)) {
    // The one case where "Save" alone would be a lie: the bytes go to the
    // parent as this mount's overrides, not to the document on screen.
    return {
      label: 'Save mount',
      hint: `Save this mount's changes as overrides on ${address.root} — the mounted package itself is not changed, and neither is any other mount of it. Editing: ${formatMountAddress(address)}.${note}`,
      unsaved: false,
      unreachable: blind,
      marker: blind ? 'unreachable' : null,
    };
  }
  if (slug === null) {
    return {
      label: 'Save',
      hint:
        'Not on disk yet. Edits so far are autosaved in this browser only — saving creates workflows/<slug>/ on the backend, and puts the link in the address bar.' +
        note,
      unsaved: true,
      unreachable: blind,
      marker: blind ? 'unreachable' : 'unsaved',
    };
  }
  return {
    label: 'Save',
    // The confident sentence is *replaced* rather than suffixed here: "saving
    // overwrites what is there" is a claim about the contents of a folder
    // nothing has been able to look at, which is the exact shape of the
    // defect. The address is not in doubt, so it still names the folder.
    hint: blind
      ? `Save to workflows/${slug}/ on the backend.${unreachableNote()}`
      : `Save to workflows/${slug}/ on the backend, overwriting what is there.`,
    unsaved: false,
    unreachable: blind,
    marker: blind ? 'unreachable' : null,
  };
}
