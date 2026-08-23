/**
 * Whether a load represented the file faithfully — and may therefore be
 * written back over it.
 *
 * `WorkflowSerializer` drops a link whose port no longer exists, because a
 * link to nothing cannot be drawn, and it says so in `warnings`.
 * `DocumentController.importJSON` passes that up as its outcome `message`. The
 * load path then **ignored the return value**, and disk autosave rewrote the
 * file from the model it now held — so opening `ops-desk` deleted four of its
 * twelve edges from disk, with no edit, no Save, and nothing on screen
 * (`every-workflow-green` 22).
 *
 * The rule this restores is one `CLAUDE.md` already makes for an unknown node
 * type — *"preserved exactly as saved"*. An edge the editor cannot render
 * deserves the same promise. It cannot be drawn, so it cannot be kept in the
 * model; what it can be given is the guarantee that nothing overwrites it.
 *
 * So a lossy load withholds the autosave baseline. `writeOpenWorkflowToDisk`
 * already skips a slug with no baseline — that mechanism exists for a
 * different race and is exactly right here: **the file wins until a person
 * saves on purpose.**
 */
export function loadWasFaithful(outcome: {
  readonly ok: boolean;
  readonly message?: string;
}): boolean {
  return outcome.ok && !outcome.message;
}
