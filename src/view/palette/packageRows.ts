import {
  MOUNT_CYCLE_NEVER_TERMINATES,
  mountCycleChain,
  mountGestureRefusal,
} from '@core/validation/mountCycleRule';
import type { WorkflowChoice } from '@core/runtime/workflowCatalogue';

/** One saved package as the palette shows it, and why it may refuse the drag. */
export interface PackageRow extends WorkflowChoice {
  /**
   * The compiler's sentence when dropping this would make the open document
   * include itself, `null` when the drag is free to happen. Non-null is the
   * whole of "greyed out": the row still renders, it just cannot be picked up.
   */
  readonly refusal: string | null;
  /**
   * The same refusal, split for the **row body**, `null` when free.
   *
   * `workflow-gallery` 74. `refusal` is one sentence, and the row printed it
   * where the slug goes, in a body clamped to two lines — so on a 1440x900
   * palette a reader got "Mounting 'routed-demo' here would make it mount
   * itself…" and the chain, the only part that says *what to do*, fell off the
   * end. It survived in the `title` and in the toast, which means a mouse user
   * who hovers was told and nobody else was.
   *
   * Two values rather than one, because the two want different treatment: a
   * short reason that may wrap, and a path that must not be cut. Composing
   * them here rather than in `Palette.tsx` keeps the copy testable in a `node`
   * environment, and keeps `core/` free of the row's presentation.
   */
  readonly refusalRow: PackageRowRefusal | null;
  /**
   * The accessible name of the row's **Open** control — `stable-beta-public/29`.
   *
   * Here rather than in `Palette.tsx` for the reason {@link PackageRow.refusalRow}
   * gives: an icon-only control's label is copy, and copy is testable in a
   * `node` environment only if it is not spelled inside JSX.
   *
   * Every package row has one — a *package* row, which is why this lives here
   * and not on the palette's other two row kinds: a node type and a starting
   * shape are not documents of the user's and have nothing to open.
   *
   * A refused row keeps it and greys it, carrying `refusal` verbatim as the
   * reason. Two arguments were weighed and the ticket settled on this one: a
   * row that is half-live reads as a rendering fault rather than as a rule,
   * and a reader who meets the mount cycle by dragging, by Entering and by
   * hovering the Open control should meet one sentence rather than three.
   */
  readonly openLabel: string;
}

/** A refused row's two readable parts — see {@link PackageRow.refusalRow}. */
export interface PackageRowRefusal {
  /** Why the gesture is unavailable. Deliberately carries no path. */
  readonly reason: string;
  /** The cycle the drop would create, verbatim as the compiler spells it. */
  readonly path: string;
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
    .map((choice) => {
      const cycle = mountCycleChain(choice.slug, ancestry);
      return {
        ...choice,
        refusal: mountGestureRefusal(choice.slug, ancestry),
        openLabel: `Open ${choice.name}`,
        // Both from `mountCycleChain`, so the row and the sentence cannot
        // print two different paths for one comparison.
        refusalRow:
          cycle === null
            ? null
            : {
                reason: `Would mount itself here — ${MOUNT_CYCLE_NEVER_TERMINATES}`,
                path: cycle.path,
              },
      };
    });
}
