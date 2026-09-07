/**
 * What Delete on an MCP row actually does, in the words the user reads.
 *
 * mcp-connect ticket 06. Every row carried a red **Delete** that removed it
 * instantly — no confirmation, no toast, no undo — and on the two rows badged
 * `default` that read as destroying a server the product ships. It never did:
 * deleting a built-in writes `enabled: false` into the project's config, a
 * committed and commented record. The mechanism was good and the user was
 * never told it exists.
 *
 * A module of its own, and pure, for the reason `workflow/consequences.ts` is:
 * these sentences are the fix, and a string built inline in a click handler is
 * a string nothing can hold to its promise.
 */

/**
 * The delete confirm.
 *
 * Two facts, and which of them is true depends on the badge:
 *
 * - a **project** entry has a line in the config and deleting removes it;
 * - a **default** has no line, so deleting *writes* one — it is hidden for
 *   this project and can be brought back.
 *
 * `usedBy` is the second warning the ticket asked for. A `tool.mcp` card
 * **names** a server and the project says what that name reaches, which is
 * what makes a copied package carry no URL of yours — and also what lets a
 * delete break a document nobody has open.
 */
export function mcpDeleteConfirmation(
  name: string,
  origin: 'built-in' | string,
  usedBy: readonly string[] = [],
): string {
  const head = `Delete the MCP server “${name}”?`;
  const what =
    origin === 'built-in'
      ? // No markdown: this is `window.confirm`, which renders plain text, so
        // asterisks around "Restore defaults" arrive on screen as asterisks.
        // Found by reading the dialog rather than the string.
        `It is one of the defaults this install ships with, so nothing is destroyed: ` +
        `it is hidden for this project, and the Restore defaults control in this ` +
        `panel brings it back.`
      : `Its entry is removed from this project's config file. Nothing else is deleted, ` +
        `and re-adding it means entering the URL again.`;
  const breakage =
    usedBy.length === 0
      ? null
      : usedBy.length === 1
        ? `One saved workflow names it — ${usedBy[0]}. Its MCP card will stop resolving ` +
          `until a server of this name exists again.`
        : `${usedBy.length} saved workflows name it — ${usedBy.join(', ')}. Their MCP cards ` +
          `will stop resolving until a server of this name exists again.`;
  return [head, what, breakage].filter((part) => part !== null).join('\n\n');
}

/** The toast after a delete, in the same terms the confirm used. */
export function mcpDeletedMessage(name: string, origin: 'built-in' | string): string {
  return origin === 'built-in'
    ? `Hidden: ${name} — a default, so it is hidden for this project rather than deleted. Restore defaults brings it back.`
    : `Deleted: ${name} — its entry is gone from this project's config.`;
}

/** The toast after a restore. */
export function mcpRestoredMessage(name: string): string {
  return `Restored: ${name} — back as a default, with the URL this install ships.`;
}

/**
 * The label on the control that brings hidden defaults back.
 *
 * Says how many, because the whole failure was that a hidden default was
 * indistinguishable from one that never existed — a button reading "Restore
 * defaults" on a project with nothing hidden is the same silence one step
 * along. Returns `null` when there is nothing to restore, so the panel has no
 * decision of its own to make.
 */
export function restoreDefaultsLabel(hidden: readonly string[]): string | null {
  if (hidden.length === 0) return null;
  return hidden.length === 1
    ? `Restore “${hidden[0]}”`
    : `Restore ${hidden.length} hidden defaults`;
}
