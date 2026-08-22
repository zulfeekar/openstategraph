import { CHAT_APP_AUDIENCE } from '@view/topbar/publishAffordance';

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

/**
 * The confirm shown when a save is about to mint a *second* package of a name
 * that already belongs to one, or `null` when no name collides.
 *
 * The-editor-makes-a-real-package 07: the default document name is a constant
 * (`AI Workflow`), most people save before renaming, and the second save
 * succeeded in silence. By the end of that review there were three packages
 * called "AI Workflow" and the only thing distinguishing them was a slug no
 * surface printed.
 *
 * The collision is still *allowed* — two packages may legitimately share a
 * name, and refusing would make the name an identity it is not. What changes
 * is that it is announced, with the slug it is about to take, before it
 * happens. Naming the slug is the substance: it is what the address bar, the
 * folder and the `/chat` picker will read afterwards.
 */
export function duplicateNameConfirmation(name: string, existingSlugs: readonly string[]): string {
  const trimmed = name.trim();
  const others =
    existingSlugs.length === 1
      ? `“${existingSlugs[0]}”`
      : `${existingSlugs.length} packages (${existingSlugs.join(', ')})`;
  return (
    `A workflow called “${trimmed}” already exists — ${others}.\n\n` +
    `Saving makes a second one. It gets its own folder and its own slug, and ` +
    `the two are told apart by the slug alone.\n\n` +
    `Cancel to rename this document first, or continue to create it anyway.`
  );
}

/**
 * The Workflows panel row's own tooltips — the badge and the Publish/Unpublish
 * button, both on the same row.
 *
 * `ship-it` 53: after 52 fixed the toast, this row was the third caller still
 * spelling the fact for itself — `'Visible in the customer /chat picker and
 * Auto routing'` on the badge, `'/chat picker'` twice more on the button —
 * where the badge in the toolbar (`publishAffordance.ts`) and the toast
 * (above) had already converged on `CHAT_APP_AUDIENCE`.
 *
 * Short on purpose: this list shows many rows at once, unlike the toolbar
 * badge or the toast, which each speak about one workflow. The row's own
 * Publish/Unpublish button already carries the verb; the tooltip's job is
 * only to say who is affected, not to re-argue the lifecycle rule the
 * toolbar's hint (`publishAffordance.ts`) already carries in full for the
 * open document.
 */
export function rowStatusHint(published: boolean): string {
  return published
    ? `Published — ${CHAT_APP_AUDIENCE} can find it in their list.`
    : `Draft — ${CHAT_APP_AUDIENCE} never see this until you publish.`;
}

/** The row's Publish/Unpublish button tooltip — the same audience, the verb. */
export function rowActionHint(published: boolean): string {
  return published
    ? `Back to draft — ${CHAT_APP_AUDIENCE} stop seeing it. Nothing is deleted.`
    : `Publish it, so ${CHAT_APP_AUDIENCE} can find it in their list.`;
}

/** The toast after a delete — the same terms the confirm used. */
export function deletedMessage(name: string): string {
  return `Deleted: ${name} — its folder is gone from workflows/.`;
}

/**
 * The toast after a publish.
 *
 * Names the transition, not the new state alone: *what changed* is the thing
 * the canvas could not show — the badge beside Save already says the steady
 * state, so repeating it here would be noise, not information. The knowledge
 * reminder stays because publishing deliberately does not rebuild routing as
 * a side effect — the workflow keeps being answered from what it last learned
 * until someone rebuilds its knowledge.
 *
 * The audience is `CHAT_APP_AUDIENCE`, the same words `publishAffordance`'s
 * badge uses (`ship-it` 52) — until this ticket the toast said "/chat picker"
 * and "Auto routing", internal surface names a second after the badge said
 * the same fact in plain words. `HIDDEN_PACKAGE_NOTE` was corrected for this
 * exact shape once already: an explanation that needs an explanation has not
 * been given.
 */
export function publishedMessage(name: string): string {
  return (
    `Published: ${name} — no longer a draft: ${CHAT_APP_AUDIENCE} can now find it in their ` +
    `list. It stays out of automatic answers until you rebuild its knowledge.`
  );
}

/**
 * The toast after an unpublish.
 *
 * The last clause answers the question this verb always raises. Unpublish sits
 * next to Delete in the list, and a user who cannot tell them apart will use
 * neither. Same shared audience as `publishedMessage`, for the same reason.
 */
export function unpublishedMessage(name: string): string {
  return (
    `Unpublished: ${name} — back to draft: ${CHAT_APP_AUDIENCE} no longer see it in their ` +
    `list. Nothing is deleted; the folder is untouched.`
  );
}
