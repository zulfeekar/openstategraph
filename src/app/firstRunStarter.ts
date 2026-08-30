import type { Workbench } from './Workbench';
import type { KeyValueStore } from './workflowStore';
import type { ClipboardFragment } from '@controller/ClipboardService';
import { UNNAMED_DOCUMENT } from '@core/model/documentName';
import { starterAssembly } from '@nodes/assemblies';

/**
 * What the very first canvas in a browser holds — and why that is not
 * `install-experience` 23 coming back.
 *
 * 23 (`be3af73`) deleted two things that put a document on a canvas nobody had
 * asked for: `seedDemoWorkflow`, which imported a 13-node package before a byte
 * of storage was read, and `resolveSession`'s adoption of this *origin's*
 * newest draft, whoever left it. The owner's complaint was not "three nodes
 * appeared". It was that the editor opened inside **somebody else's named
 * workflow**, wearing a plausible title and a `Draft` badge, with no way for
 * the user to account for it.
 *
 * Every one of those properties is inverted here:
 *
 * - **Nobody else's.** Nothing is read; four nodes are composed from the
 *   assembly the palette already offers. There is no author to be confused
 *   with, no package to overwrite, and no slug.
 * - **Announced.** A Note on the canvas is the first thing in reading order,
 *   and it says what the flow is, what to do with it, and that deleting it is
 *   allowed. 23's document explained itself nowhere.
 * - **Once, ever.** 23's adoption fired for *every* tab whose own
 *   `sessionStorage` was empty — a browser restart was enough, forever. This
 *   fires only while `localStorage` holds no draft **and** no marker, which is
 *   a state a browser is in exactly once.
 * - **Unsaved.** The document keeps `WorkflowModel`'s unnamed name, so the top
 *   bar reads `Untitled` and the first save asks for a real one.
 *
 * ## Why it is not auto-saved
 *
 * `the-look-has-an-author-now` (`91f37a2`) made the first save ask for a name,
 * because the backend mints the package slug from that name and **freezes** it
 * — a slug is a directory and directories do not get renamed. Auto-saving a
 * starter would mint `workflows/untitled/` permanently out of a word nobody
 * chose, which is the defect that ticket removed arriving through a different
 * door. So: placed, not saved. The browser draft still records it after the
 * first edit, exactly as it records any other unsaved document, and *Workflows
 * ▸ Unsaved in this browser* still finds it.
 *
 * ## Why it is not a second definition of the starter
 *
 * `starterAssembly` already is Input → Agent → Output, wired, in the fragment
 * shape a paste consumes. Spelling those three nodes out again here would be
 * two descriptions of one thing — CLAUDE.md's named defect — so this file
 * composes the shipped one and contributes only the Note and the geometry that
 * puts the Note above it.
 */

/** The marker that says this browser has been handed its starter already. */
export const STARTER_PLACED_KEY = 'openstategraph-starter-placed';

/**
 * The first sentences a stranger reads inside the product.
 *
 * Four jobs and no fifth: name the three nodes, say the one gesture that runs
 * them, say that nothing is saved yet — in `Untitled`, the same word the top
 * bar is showing while they read this — and say the note is theirs to delete.
 *
 * It does **not** repeat the empty-canvas copy, which teaches how to *get* the
 * three nodes and is showing precisely when this is not
 * (`view/canvas/emptyStateCopy.ts`). The canvas is not a manual, and the test
 * beside this holds it under 400 characters so the next session answers a
 * support question somewhere else.
 */
export const FIRST_RUN_NOTE = [
  '# Start here',
  '',
  'The **Input** holds your question, the **Agent** answers it, the **Output** shows the answer.',
  '',
  `Type a question into the Input and press Run. Nothing is saved yet — this canvas is ${UNNAMED_DOCUMENT} until you save it.`,
  '',
  'Done reading? Delete this note. The three nodes stay.',
].join('\n');

const NOTE_TYPE = 'annotate.note';
const NOTE_AT = { x: 0, y: 0 };
const NOTE_SIZE = { width: 420, height: 190 };
/**
 * How far the flow sits below the note. The note's height plus a gap, so the
 * two read as one column rather than as an overlap — the canvas does not lay
 * out for us and a fragment carries absolute positions.
 */
const FLOW_OFFSET_Y = NOTE_SIZE.height + 70;

/**
 * The note, then the shipped starter translated below it.
 *
 * A function rather than a constant because it hands out a fresh object each
 * time: a fragment is passed to `pasteCommand`, and a shared mutable literal
 * escaping into the clipboard's own slot is the kind of aliasing that only
 * shows up on the second call.
 */
export function firstRunFragment(): ClipboardFragment {
  const flow = starterAssembly.fragment;
  return {
    origin: NOTE_AT,
    nodes: [
      {
        id: 'first-run-note',
        type: NOTE_TYPE,
        position: NOTE_AT,
        size: NOTE_SIZE,
        parentId: null,
        data: { body: FIRST_RUN_NOTE },
      },
      ...flow.nodes.map((node) => ({
        ...node,
        position: { x: node.position.x, y: node.position.y + FLOW_OFFSET_Y },
      })),
    ],
    edges: flow.edges,
  };
}

/**
 * Whether this page load should hand over the starter.
 *
 * Pure, and every input is a fact the caller already had — so the decision can
 * be read and tested without a DOM, which is the shape `shouldSeedDemo` proved
 * out. Each clause forbids a different way of becoming ticket 23:
 *
 * - `opening` — a `?w=` deep link names a document; three nodes on top of it
 *   would be exactly the "put something on the canvas nobody asked for" move.
 * - `restored` — this tab reloaded and got its own draft back.
 * - `nodeCount` — something already put a document here. `?demo=1` seeds in
 *   `main.tsx`, before React exists, so a non-empty model is the only evidence
 *   of it this decision can read.
 * - `mostRecentId` — this browser holds a draft, anybody's, under any key. It
 *   has been worked in, so the lesson is past.
 * - `alreadyPlaced` — it has been handed over once. This is what makes
 *   deleting it stick.
 */
export function shouldPlaceStarter(input: {
  readonly opening: 'fetch' | 'restore';
  readonly restored: boolean;
  readonly nodeCount: number;
  readonly mostRecentId: string | null;
  readonly alreadyPlaced: boolean;
}): boolean {
  if (input.opening !== 'restore') return false;
  if (input.restored) return false;
  if (input.nodeCount > 0) return false;
  if (input.mostRecentId != null) return false;
  return !input.alreadyPlaced;
}

/**
 * Has this browser been handed the starter already?
 *
 * **Fails safe, and the safe direction is `true`.** A store that throws — a
 * locked-down browser, blocked site data, a private window — cannot remember a
 * dismissal, so answering `false` would put the starter back on every load with
 * no way to be rid of it: ticket 23's symptom rebuilt out of an exception
 * handler. Answering `true` costs a first-time user in that browser their
 * starter, and they still have the empty-canvas copy and the palette.
 */
export function hasPlacedStarter(store: KeyValueStore): boolean {
  try {
    return store.getItem(STARTER_PLACED_KEY) != null;
  } catch {
    return true;
  }
}

/**
 * Puts the starter and its note on the canvas, and records that it happened.
 *
 * Through `clipboard.insertFragment` — the seam a palette drag already uses —
 * so this inherits fresh ids, edge rewiring, instance caps and a **single**
 * undoable command rather than growing a second way to insert nodes. One undo
 * is the second way out, beside deleting it.
 *
 * The marker is written even though the write may fail, and a failed write is
 * not reported: there is nothing the user could do about it, and the worst case
 * is one extra offer of a starter in a browser that cannot remember anything
 * anyway.
 */
export function placeFirstRunStarter(workbench: Workbench, store: KeyValueStore): void {
  workbench.controller.clipboard.insertFragment(firstRunFragment(), NOTE_AT);
  // A drop leaves what it dropped selected, which is right for a gesture and
  // wrong for an arrival: the first canvas a stranger sees would come up with
  // all four nodes highlighted and one Backspace from empty — while the note
  // in front of them says deleting *it* leaves the three nodes standing. The
  // note has to be true.
  workbench.controller.selection.clear();
  try {
    store.setItem(STARTER_PLACED_KEY, new Date().toISOString());
  } catch {
    /* see above */
  }
}
