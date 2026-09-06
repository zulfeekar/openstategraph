/**
 * What the Knowledge card says about its own effect — ticket 09.
 *
 * A user reasonably reads a node on a canvas as *the thing that makes a
 * capability happen*. This one does not: binding is **ambient**. When the
 * package's `knowledge/` holds at least one `.md`, the runtime attaches the
 * lookup tool to every agent and worker in that workflow
 * (`prebuilt_knowledge.ambient_knowledge_tool`), whether or not this card is on
 * the canvas. Deleting it removes nothing; adding one to a package with an
 * empty `knowledge/` adds nothing.
 *
 * That is a deliberate design — wiring it explicitly would break the
 * minimum-viable-prebuilt rule, and every existing package would silently lose
 * its knowledge — so the fix is not to change the binding. It is to stop the
 * canvas implying a wiring it does not do, on the one surface this project
 * insists must be a truthful projection of the model.
 *
 * The note is state-dependent because the truth is: with topics, the capability
 * is already live and this card is a window onto it; with none, there is
 * nothing to look up and the button is what changes that. One sentence that
 * covered both would have to be vague enough to be useless.
 *
 * Here rather than inline in the card so the wording is testable without a DOM,
 * the same reason `emptyStateCopy` lives apart from the canvas.
 */
export function knowledgeBindingNote(topicCount: number | null): string {
  if (topicCount === null) {
    // No open slug: the card cannot read `knowledge/`, so it must not claim
    // the directory is empty. Found in the browser — an unsaved draft showed
    // "Nothing to look up yet" for a package that has twelve topics on disk,
    // which is the same class of untruth this note exists to remove.
    return (
      'Save this workflow to a folder first — until then there is no knowledge/ ' +
      'to read from or build into, and this card cannot tell you what binds.'
    );
  }
  if (topicCount === 0) {
    return (
      'Nothing to look up yet. Build, and every agent in this package gets the ' +
      'lookup tool automatically — no wiring, and this card is not what binds it.'
    );
  }
  const topics = `${topicCount} topic${topicCount === 1 ? '' : 's'}`;
  return (
    `Every agent in this package can already look up these ${topics} — the ` +
    'binding is automatic, not this wire. Removing this card does not unbind it; ' +
    'emptying knowledge/ does.'
  );
}
