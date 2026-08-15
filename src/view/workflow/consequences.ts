/**
 * What each lifecycle verb actually does, in the words the user reads.
 *
 * These sentences are the ticket (production-ready 06), not decoration around
 * it: save, publish and delete all worked already — what was missing is that
 * "deleting says what is lost" and "publishing says what changed". A confirm
 * reading only *"this cannot be undone"* has named neither the thing nor the
 * loss, and a publish toast that never says `/chat` leaves the one rule the
 * draft lifecycle exists for invisible from the canvas.
 *
 * A module of its own, and pure, for the reason `runIntent` is: copy that
 * matters is copy worth a test, and a string built inline in a click handler
 * is a string nothing can hold to its promise.
 */

/**
 * The delete confirm.
 *
 * The folder is the point. A workflow is a **package** — `workflow.json` plus
 * its `tools/`, `tests/`, `functions/` and knowledge — and deleting it removes
 * the directory, not a row in a list. Someone who thinks they are discarding a
 * drawing is about to lose Python they wrote.
 */
export function deleteConfirmation(name: string, published: boolean): string {
  const base =
    `Delete “${name}”?\n\n` +
    `Its whole folder goes with it — the workflow document and any tools, ` +
    `tests and knowledge in that package. This cannot be undone.`;
  // Said only when it is true: a draft is not on the customer surface, so
  // telling a draft's owner about /chat would be describing someone else's
  // workflow.
  return published
    ? `${base}\n\nIt is published, so it also disappears from /chat immediately.`
    : base;
}

/** The toast after a delete — the same terms the confirm used. */
export function deletedMessage(name: string): string {
  return `Deleted: ${name} — its folder is gone from workflows/.`;
}

/**
 * The toast after a publish.
 *
 * Names the transition, not the new state alone: *what changed* is the thing
 * the canvas could not show. The knowledge reminder stays because publishing
 * deliberately does not rebuild routing as a side effect — Auto routing keeps
 * answering from what it last learned until someone rebuilds it.
 */
export function publishedMessage(name: string): string {
  return `Published: ${name} — no longer a draft: it is now in the /chat picker for customers. Rebuild knowledge to put it into Auto routing.`;
}

/**
 * The toast after an unpublish.
 *
 * The last clause answers the question this verb always raises. Unpublish sits
 * next to Delete in the list, and a user who cannot tell them apart will use
 * neither.
 */
export function unpublishedMessage(name: string): string {
  return `Unpublished: ${name} — back to draft: it is out of the /chat picker. Nothing is deleted; the folder is untouched.`;
}
