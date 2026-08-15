import type { ClipboardFragment } from '@controller/ClipboardService';

/**
 * A wired assembly you drag onto the canvas you are already working in.
 *
 * **Not a node type**, and that is the whole point. A `Loop` node would compile
 * to nothing new — recorded in the organism-taxonomy research, in the `loop`
 * template's ticket, and in `templates/index.json` — because a loop is a
 * *cycle in the graph*, not a box around one. What drops is ordinary nodes and
 * ordinary edges; afterwards the document is indistinguishable from one drawn
 * by hand, which is what keeps `workflow.json` portable.
 *
 * **Not a template, either.** A template produces a whole new document and
 * stops existing (`--template loop`, the editor's *Start from* picker). This
 * adds to a document that already exists. Ticket 01 shipped the first and its
 * own notes claimed the second; ticket 21 is the correction.
 *
 * The tier is **organism** — an assembly of molecules. Ticket 14 established
 * that organisms are the only tier obtainable two ways, *drawn or dragged*,
 * and dragging one had only ever meant mounting a package. This is the other
 * half of that rule.
 */
export interface IAssemblyDefinition {
  readonly id: string;
  readonly label: string;
  readonly description: string;
  readonly iconId: string;
  /** Which palette section it appears in. */
  readonly category: string;
  readonly keywords: readonly string[];
  /**
   * The nodes and edges to insert, in the clipboard's own fragment shape.
   *
   * Deliberately the same type a copy produces: inserting an assembly *is* a
   * paste of a canned fragment, so it inherits id remapping, edge rewiring,
   * instance caps and the single undoable command rather than growing a
   * second mechanism beside them.
   */
  readonly fragment: ClipboardFragment;
}
