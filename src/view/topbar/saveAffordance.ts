import { getOpenAddress } from '@app/openAddress';
import { getOpenSlug } from '@app/openWorkflow';
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
}

export function saveAffordance(
  address = getOpenAddress(),
  slug = getOpenSlug(),
): SaveAffordance {
  if (address && isInstance(address)) {
    // The one case where "Save" alone would be a lie: the bytes go to the
    // parent as this mount's overrides, not to the document on screen.
    return {
      label: 'Save mount',
      hint: `Save this mount's changes as overrides on ${address.root} — the mounted package itself is not changed, and neither is any other mount of it. Editing: ${formatMountAddress(address)}.`,
      unsaved: false,
    };
  }
  if (slug === null) {
    return {
      label: 'Save',
      hint: 'Not on disk yet. Edits so far are autosaved in this browser only — saving creates workflows/<slug>/ on the backend, and puts the link in the address bar.',
      unsaved: true,
    };
  }
  return {
    label: 'Save',
    hint: `Save to workflows/${slug}/ on the backend, overwriting what is there.`,
    unsaved: false,
  };
}
