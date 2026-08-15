import { Err, Ok, type Result } from '@core/kernel/Result';
import type { IDocumentController } from '@controller/contracts';
import type { IWorkflowTemplates } from '@core/runtime/WorkflowFileClient';
import { clearOpenSlug } from '@app/openWorkflow';
import { clearDrillStack } from '@app/drillStack';

/**
 * Starting a new workflow — the knowledge, with no surface attached.
 *
 * Extracted from `WorkflowManager` for the same reason `loadWorkflowIntoEditor`
 * was: there is now more than one way to ask for it. Ticket 06's owner pass put
 * **New** in the toolbar, because a first-time user does not know the panel
 * exists — and the ticket's own guard is that a second entry point must be a
 * *promotion* of the manager, never a second implementation of it. So the
 * button moved and this did not: clear the canvas, apply a template if one was
 * chosen, name the document, and forget both the slug and the drill trail.
 *
 * The *presentation* stays with each caller. The panel closes itself and names
 * the template it used; the toolbar has neither a panel nor a picker.
 */

/**
 * The picker's "no template" option — the editor's original behaviour.
 *
 * Not a template, which is why it is a sentinel rather than a fourth entry in
 * the catalogue: `openstategraph new` scaffolds a package that must run, so its
 * default is `minimal`; the canvas holds an empty document perfectly well, and
 * someone who asks for a new workflow should not have three nodes appear under
 * their cursor.
 */
export const BLANK_TEMPLATE = 'blank';

export interface NewWorkflowRequest {
  /** What the user typed. Blank falls back to `defaultWorkflowName()`. */
  readonly name: string;
  /** A template name from the catalogue, or `BLANK_TEMPLATE`. */
  readonly template: string;
}

export interface NewWorkflow {
  readonly name: string;
  /** The template applied, or `null` for a blank canvas. */
  readonly template: string | null;
}

/** The name a workflow gets when nobody types one. */
export function defaultWorkflowName(now: Date = new Date()): string {
  return `Workflow ${now.getFullYear()}`;
}

export async function createNewWorkflow(
  request: NewWorkflowRequest,
  controller: { readonly document: IDocumentController },
  templates: IWorkflowTemplates,
): Promise<Result<NewWorkflow, string>> {
  const name = request.name.trim() || defaultWorkflowName();

  // Fetched before anything is cleared: a failed fetch must leave the canvas
  // exactly as it was, not empty and templateless. The document is re-fetched
  // with the name the user actually typed, because a template may render that
  // name into it (the team template titles its supervisor "<name> Lead") and
  // the editor's result must be the CLI's rather than an approximation.
  let starting: unknown = null;
  if (request.template !== BLANK_TEMPLATE) {
    const outcome = await templates.templates(name);
    const chosen = outcome.ok
      ? outcome.value.find((template) => template.name === request.template)
      : undefined;
    if (!chosen) {
      return Err(`Could not load the ${request.template} template — nothing was changed.`);
    }
    starting = chosen.document;
  }

  controller.document.clear();
  if (starting !== null) {
    // Imported exactly as a saved workflow would be. Nothing records which
    // template it was: a template is a scaffold input, so from here on this is
    // just a document.
    controller.document.importJSON(JSON.stringify(starting));
  }
  controller.document.setName(name);
  // A fresh workflow has no slug yet — the next save asks the backend to mint
  // one. The URL loses its `w=` with it: an unsaved document is not on the
  // backend, so there is nothing a link could open.
  clearOpenSlug();
  // Same reasoning as a manual load: a brand-new document is not "inside"
  // anything, so there is nothing to go back to.
  clearDrillStack();

  return Ok({ name, template: request.template === BLANK_TEMPLATE ? null : request.template });
}

export interface DiscardSubject {
  readonly name: string;
  readonly nodeCount: number;
  /** Whether this document already has a folder on the backend. */
  readonly saved: boolean;
}

/**
 * The warning to put in front of a New that would throw work away, or `null`.
 *
 * The toolbar's New creates **immediately** — no panel, no form, no second
 * step — which makes it the one control in the editor that can discard a
 * document with a single click. A saved workflow is safe (its folder holds it,
 * and edits autosave there), and an empty canvas has nothing to lose; a
 * never-saved document with nodes on it lives in this browser and nowhere
 * else, so it is the one case that has to be asked about.
 */
export function discardWarning(subject: DiscardSubject): string | null {
  if (subject.saved || subject.nodeCount === 0) return null;
  const nodes = subject.nodeCount === 1 ? '1 node' : `${subject.nodeCount} nodes`;
  return (
    `Start a new workflow?\n\n` +
    `“${subject.name}” has never been saved, so its ${nodes} live in this browser only. ` +
    `Starting a new one discards them.`
  );
}
