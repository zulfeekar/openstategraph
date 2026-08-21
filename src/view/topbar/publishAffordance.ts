import { getOpenAddress } from '@app/openAddress';
import { getOpenSlug } from '@app/openWorkflow';
import { isInstance, type MountAddress } from '@core/model/MountAddress';

/**
 * What the toolbar says about **who can see this workflow**, before anything
 * is pressed.
 *
 * `ship-it` 39. The owner asked for "the possibility to publish the workflow"
 * and it already existed — `POST /api/workflows/{slug}/publish`, and a
 * Publish/Unpublish button in the Workflows panel. They had not found it, and
 * that is the finding: a developer spends their day on the canvas, and the
 * lifecycle control lived in a list they opened once.
 *
 * `published` is not a minor flag. It is what gates a package from the
 * **customer** surface — the chat app's picker lists published, non-hidden
 * packages only — so it is the most consequential state a workflow has, and it
 * was invisible from the one place the workflow is being worked on.
 *
 * ## Publish is a lifecycle action, not a document setting
 *
 * `13fa2d7` put a document-level setting into the Inspector's Document section
 * through `DocumentController.setSetting`, and that is the neighbouring
 * precedent — so the question is real rather than rhetorical. `published` is
 * not one of those, on three counts, all of them measured rather than assumed:
 *
 * - **It is not in the document.** `workflow_store.set_published` rewrites one
 *   key of the *envelope*, a sibling of `savedAt`, and reads nothing inside
 *   `workflow`. A setting travels with the document; this belongs to the
 *   folder.
 * - **It takes effect without a Save**, immediately, for people who are not in
 *   this editor. Every other Document-section field takes effect when the file
 *   is written.
 * - **It is not undoable.** `Mod+Z` walks the model's command history; a
 *   published workflow that quietly unpublished itself on an undo would be a
 *   customer-visible change nobody asked for.
 *
 * So it belongs beside Save in the toolbar — Save answers *is my work on
 * disk*, this answers *is my work in front of customers*, and those are the
 * two facts about an open package that nothing on the canvas used to state.
 *
 * ## …and publishing does not save
 *
 * Measured, not assumed: the endpoint flips the envelope's flag and never
 * looks at a document, so **publishing a slug whose canvas holds unsaved edits
 * ships the saved version.** That is the ticket's second half and the same
 * class of surprise as `ship-it` 38.
 *
 * Making publish *imply* save was considered and rejected. Two reasons, and
 * the first is decisive: while a mount instance is open, Save writes the
 * **parent's** overrides (`saveAffordance`), so publish-implies-save would
 * write a different package than the one being published. And nothing on a
 * lifecycle path may write a document at all — a flag is not an edit.
 *
 * What replaces the implication is saying it. The hint names
 * `workflows/<slug>/` as what goes live in both directions, and when this
 * browser holds work newer than the file, publishing asks first and names the
 * gap. That is `2e9c75c`'s rule applied to an outward-facing verb: a control
 * that would quietly ship something other than what is on screen owes the user
 * the sentence, not the silence.
 *
 * Pure and DOM-free, like `saveAffordance` beside it: the label, the hint and
 * the confirm are the whole surface, and copy that matters is copy worth a
 * test.
 */

export type PublishStatus =
  /** No folder on the backend yet — a draft in the most literal sense. */
  | 'unsaved'
  /** A mount instance is open; the lifecycle is not this document's. */
  | 'instance'
  /** The runtime has not said, and this module never guesses. */
  | 'unknown'
  /** Saved, and customers cannot see it. */
  | 'draft'
  /** Saved, and customers can. */
  | 'published';

export interface PublishAffordance {
  readonly status: PublishStatus;
  /** The word the toolbar prints, or `null` to print nothing at all. */
  readonly label: string | null;
  /** The status tooltip: what this state means for a customer. */
  readonly hint: string;
  /** The verb available here, or `null` when there is nothing to press. */
  readonly action: 'publish' | 'unpublish' | null;
  readonly actionLabel: string | null;
  /** The action tooltip: what pressing it will do. */
  readonly actionHint: string;
  /** The confirm to clear before acting, or `null` when none is owed. */
  readonly confirmation: string | null;
}

export interface PublishSubject {
  readonly address: MountAddress | null;
  readonly slug: string | null;
  /**
   * What the backend last said about this slug. `null` means *not yet known* —
   * a fresh session, or an unreachable runtime — and is deliberately distinct
   * from `false`.
   */
  readonly published: boolean | null;
  /** Whether this browser holds a draft newer than the file on disk. */
  readonly unsavedWork: boolean;
}

const NOTHING: Omit<PublishAffordance, 'status' | 'hint'> = {
  label: null,
  action: null,
  actionLabel: null,
  actionHint: '',
  confirmation: null,
};

export function publishAffordance(
  subject: PublishSubject = {
    address: getOpenAddress(),
    slug: getOpenSlug(),
    published: null,
    unsavedWork: false,
  },
): PublishAffordance {
  const { address, slug, published, unsavedWork } = subject;

  if (address && isInstance(address)) {
    return {
      ...NOTHING,
      status: 'instance',
      hint: `Editing one mount of a package. Whether customers can see a package is set on the package itself, not on a mount of it.`,
    };
  }

  if (slug === null) {
    return {
      ...NOTHING,
      status: 'unsaved',
      label: 'Draft',
      hint:
        `Draft — not on disk yet, so there is nothing to put in front of customers. ` +
        `Save it first: publishing shows people the saved version of a workflow, never the canvas.`,
    };
  }

  if (published === null) {
    return {
      ...NOTHING,
      status: 'unknown',
      hint: `The runtime has not said whether customers can see this workflow.`,
    };
  }

  const folder = `workflows/${slug}/`;

  if (published) {
    return {
      status: 'published',
      label: 'Published',
      hint:
        `Published — people using the chat app can pick this workflow from their list. ` +
        `What they get is the version saved in ${folder}, not unsaved changes on this canvas.`,
      action: 'unpublish',
      actionLabel: 'Unpublish',
      actionHint:
        `Take it back out of the chat app, so people using it stop seeing it in their list. ` +
        `Nothing is deleted; the folder is untouched and you can publish it again.`,
      confirmation: null,
    };
  }

  return {
    status: 'draft',
    label: 'Draft',
    hint:
      `Draft — people using the chat app never see this workflow in their list. ` +
      `Publishing puts the version saved in ${folder} into it; what is on this canvas goes live only once you Save.`,
    action: 'publish',
    actionLabel: 'Publish',
    actionHint:
      `Put this workflow into the chat app, so people using it can pick it from their list. ` +
      `They get what is saved in ${folder}.`,
    confirmation: unsavedWork ? publishWithUnsavedChangesConfirmation(slug) : null,
  };
}

/**
 * The confirm shown when a publish is about to ship something other than what
 * is on screen.
 *
 * Named on the slug rather than the display name, because the slug is what
 * names the folder the customer's copy comes out of — and a name is not an
 * identity (`the-editor-makes-a-real-package` 07).
 */
export function publishWithUnsavedChangesConfirmation(slug: string): string {
  return (
    `Publish “${slug}” as it is saved, not as it is on screen?\n\n` +
    `This canvas has changes that are not in workflows/${slug}/ yet. Publishing ` +
    `shows people using the chat app the saved version; the changes you have not ` +
    `saved stay in this browser, and they never see them.\n\n` +
    `Cancel to Save first, or continue to publish the saved version.`
  );
}
