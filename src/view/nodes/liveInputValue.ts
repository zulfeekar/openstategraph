/**
 * What an entry Input card should say a run is actually using (ticket 34).
 *
 * ## The defect, in its purest form
 *
 * A developer ran `concierge`, watched the mounted Chinook Assistant light up,
 * and opened it. Its Text Input read **"Which genre earns the most revenue?
 * Name the genre and the figure."** — every time, whatever had been asked. That
 * is the saved `prompt` field: the value the file holds, not the question in
 * flight. The canvas was displaying a stored value where the truth was live.
 *
 * The chat panel writes the question onto the *open* document's entry node
 * before it runs, which is why the parent's card looked right and hid this for
 * so long. Nothing writes it onto a mounted child's card, because the child is
 * not open when the run starts — and it must not be written even when the
 * child *is* opened, because that would edit a saved document to display a
 * fact about a run. Two different things live in one slot, so the card shows
 * them as two things.
 *
 * ## Why "differs" and not merely "ran"
 *
 * Repeating the field back at the developer under a second heading teaches
 * nothing and costs a third of the card. The note earns its space exactly when
 * the two disagree — which is the whole content of the bug — so that is when
 * it appears.
 */

/**
 * @param runValue what the run reported this node produced (`runtime.output`),
 *   which for an entry Input node *is* the question the graph received.
 * @param storedValue the node's saved `prompt` field.
 * @returns the value to show as the run's, or `null` to leave the card alone.
 */
export function liveInputValue(runValue: unknown, storedValue: string): string | null {
  if (typeof runValue !== 'string') return null;
  const live = runValue.trim();
  if (live === '') return null;
  // Compared trimmed, so trailing whitespace in a saved prompt cannot invent a
  // disagreement — the point is whether the developer is being shown the
  // wrong *question*, not the wrong bytes.
  return live === storedValue.trim() ? null : live;
}
