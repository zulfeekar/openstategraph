import { mountGestureRefusal } from '@core/validation/mountCycleRule';
import type { WorkflowChoice } from '@core/runtime/workflowCatalogue';

/** One saved package as the palette shows it, and why it may refuse the drag. */
export interface PackageRow extends WorkflowChoice {
  /**
   * The compiler's sentence when dropping this would make the open document
   * include itself, `null` when the drag is free to happen. Non-null is the
   * whole of "greyed out": the row still renders, it just cannot be picked up.
   */
  readonly refusal: string | null;
}

/**
 * Which saved packages the Packages section lists, and which of them refuse.
 *
 * Pure — the catalogue, the trail and the search box come in as arguments, so
 * the rule is testable at every depth without React, a `sessionStorage` or a
 * backend. `Palette.tsx` renders the answer; it does not own it, which is the
 * split `paletteSearch.ts` already established beside it.
 *
 * **A refused package is listed, not filtered out.** That is ticket 42's
 * finding paid off: a native `<datalist>` drops a disabled option instead of
 * greying it, so the mount combobox could only append " — would include itself"
 * to the label, and hiding the entry would have deleted the one row a reader is
 * hunting for while saying nothing about why. A palette row *can* grey, and
 * this is the surface that does it — the gesture is unavailable rather than
 * merely punished afterwards.
 *
 * The refusal is `mountGestureRefusal`'s, not a second comparison: the server
 * stays the authority (`node_runtime.py::_subgraph`, `api/mount_resolution.py`)
 * and a user who meets this by dragging, by typing, or by running meets one
 * rule rather than three that sound like different problems.
 *
 * **In the conditional, and that is `workflow-gallery` 65.** The rule's other
 * mood — `mountCycleRefusal`, the compiler's own sentence — says a workflow
 * *mounts itself*, which is a fact about a document that declares the mount.
 * A palette row declares nothing: it offers a gesture. A package fresh from
 * `openstategraph new` is its own only row, so the first screen a new user ever
 * sees was telling them their untouched document mounts itself, with no mount
 * node in it. The greying was right; the tense was not.
 */
export function packageRows(
  catalogue: readonly WorkflowChoice[],
  /** Oldest first — the drill trail, then the document on screen. */
  ancestry: readonly string[],
  query: string,
): readonly PackageRow[] {
  const needle = query.trim().toLowerCase();
  return catalogue
    .filter(
      (choice) =>
        !needle ||
        choice.slug.toLowerCase().includes(needle) ||
        choice.name.toLowerCase().includes(needle),
    )
    .map((choice) => ({ ...choice, refusal: mountGestureRefusal(choice.slug, ancestry) }));
}
