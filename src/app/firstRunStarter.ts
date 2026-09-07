import type { Workbench } from './Workbench';
import type { KeyValueStore } from './workflowStore';
import type { ClipboardFragment } from '@controller/ClipboardService';
import type { NodeId } from '@core/model/contracts/node';
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
 * The note's id **in the fragment**, and only there.
 *
 * Not how the rewrite finds it. `insertFragment` routes through
 * `pasteCommand`, which mints a fresh id for every node it inserts — checked,
 * not assumed: a placed starter's note is `node:annotate.note-1`. So the
 * rewrite finds the note by its type and by `BEFORE_RUN_MARKER`, which is
 * what that marker is for. (The line here used to claim the opposite; it was
 * written in slice 1, before anything had looked.)
 */
export const NOTE_ID = 'first-run-note';

/**
 * The last line of a note still waiting for its first run.
 *
 * **Not an HTML comment.** That was the first design (program design,
 * "least confident decisions" #2) and it does not hold: checked live against
 * the actual `RichText` render (react-markdown, no raw-HTML plugin), a
 * standalone `<!-- ... -->` line is not recognised as an HTML block in this
 * position — it comes through as ordinary paragraph text, so a reader would
 * see the literal comment syntax printed at the bottom of the note. Recorded
 * in `docs/plans/runnable-starter/00-status.md`.
 *
 * A single zero-width space (`U+200B`) on its own line has none of that
 * problem: it is a real, non-whitespace character, so markdown does not trim
 * the line away, but it renders at zero width — nothing a reader can see. It
 * must stay the **last** line of every before-run wording, because that is
 * the whole test for "this note is still ours to rewrite"
 * (`starterNoteAwaitingRun`). A note the user has typed one word into no
 * longer ends with it, and is left alone.
 */
export const BEFORE_RUN_MARKER = '​';

/**
 * The question already sitting in the Input on first paint.
 *
 * About the product itself, on purpose (program design, "least confident
 * decisions" #4): a data question would need a tool and a key before the
 * first press could ever succeed, and the whole point of the tracer is one
 * press to a real answer. A question about OpenStateGraph is checkable by
 * the reader with nothing else configured.
 */
export const STARTER_QUESTION =
  'What is a state graph, and why would I draw one instead of writing a script?';

/** What `beforeRunNote`/`firstRunFragment` read to decide their wording. */
export type StarterReadiness = { readonly modelConfigured: boolean; readonly runReadiness: string };

/**
 * The first sentences a stranger reads inside the product, before their
 * first Run.
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
const BEFORE_RUN_TEXT = [
  '# Start here',
  '',
  'The **Input** already has a question, the **Agent** answers it, the **Output** shows the answer.',
  '',
  `Press Run to see it answered. Nothing is saved yet — this canvas is ${UNNAMED_DOCUMENT} until you save it.`,
  '',
  'Done reading? Delete this note. The three nodes stay.',
  '',
  BEFORE_RUN_MARKER,
].join('\n');

/**
 * How much of the server's readiness sentence the note will carry.
 *
 * Shorter than a failure's `REASON_LIMIT` because this wording keeps the
 * three-node sentence as well — and the 400-character ceiling is the whole
 * argument for the note existing on a canvas rather than in a manual.
 */
const READINESS_LIMIT = 140;

/** As much of a server sentence as fits, with an ellipsis when it does not. */
function clamped(sentence: string, limit: number): string {
  const trimmed = sentence.trim();
  return trimmed.length > limit ? `${trimmed.slice(0, limit).trimEnd()}…` : trimmed;
}

/**
 * The wording for a first visit that cannot run yet.
 *
 * It **quotes** and does not compose. The sentence is
 * `ProviderCatalogue.elected_default().reason` — the server's own account of
 * what a run would do, the one place the variable to set is named — carried
 * to the browser as `/api/providers`' `run_readiness` and held in
 * `serverReadiness`. A second wording here would be a second thing to keep
 * true, and this side of the wire does not know which variable the install
 * would name.
 *
 * It must not say *press Run*: the product's success metric is one press to
 * an answer, and inviting a press that cannot answer is the failure this
 * wording exists to prevent.
 */
function noModelText(sentence: string): string {
  return [
    '# Start here',
    '',
    'The **Input** already has a question, the **Agent** answers it, the **Output** shows the answer.',
    '',
    'No model is configured yet, so a run has nothing to answer with. The server says:',
    '',
    `> ${clamped(sentence, READINESS_LIMIT)}`,
    '',
    'This note is yours to delete.',
    '',
    BEFORE_RUN_MARKER,
  ].join('\n');
}

/**
 * The before-run wording for a given readiness.
 *
 * `null` — `serverReadiness` has not answered yet — reads as the ordinary
 * "press Run" text: on first paint there is no evidence of a missing model,
 * so nothing here should read as a warning.
 *
 * So does `modelConfigured: false` **with no sentence**, and that is a
 * decision rather than an oversight. `model_configured` arrives on
 * `/api/health`; the sentence arrives on `/api/providers`, which is behind
 * auth and may refuse. Knowing there is a wall without holding the words for
 * it is not licence to invent them — the architecture says this file quotes
 * and never composes — and `serverReadiness`'s own rule is that saying
 * nothing is the honest option when the browser cannot know.
 */
export function beforeRunNote(readiness: StarterReadiness | null): string {
  if (readiness == null || readiness.modelConfigured) return BEFORE_RUN_TEXT;
  const sentence = readiness.runReadiness.trim();
  return sentence === '' ? BEFORE_RUN_TEXT : noModelText(sentence);
}

/**
 * What the shared readiness store says, in the two fields this file needs.
 *
 * Structural rather than typed against `ServerReadiness`, for the reason
 * `StarterRunOutcome` is structural: this module is copy and placement, and a
 * dependency on the provider layer would tie the first-visit text to a class
 * it has no other business with. The shell passes the real singleton.
 */
export interface StarterReadinessSource {
  modelConfigured(): boolean | null;
  runReadiness(): string | null;
}

/**
 * The readiness to write a note from, or `null` when the server has not
 * answered.
 *
 * `''` for a sentence the server has not given is passed through rather than
 * replaced: `beforeRunNote` reads it as *no words for this*, which is not the
 * same as *no problem*, and is the only shape that keeps the two apart.
 */
export function starterReadinessOf(source: StarterReadinessSource): StarterReadiness | null {
  const configured = source.modelConfigured();
  if (configured === null) return null;
  return { modelConfigured: configured, runReadiness: source.runReadiness() ?? '' };
}

/** The `null`-readiness wording, kept as a constant for callers that have no readiness to pass. */
export const FIRST_RUN_NOTE = beforeRunNote(null);

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
export function firstRunFragment(readiness: StarterReadiness | null): ClipboardFragment {
  const flow = starterAssembly.fragment;
  return {
    origin: NOTE_AT,
    nodes: [
      {
        id: NOTE_ID,
        type: NOTE_TYPE,
        position: NOTE_AT,
        size: NOTE_SIZE,
        parentId: null,
        data: { body: beforeRunNote(readiness) },
      },
      ...flow.nodes.map((node) => ({
        ...node,
        position: { x: node.position.x, y: node.position.y + FLOW_OFFSET_Y },
        // The assembly's own Input stays empty (a palette drag must not
        // answer a question nobody asked); the first-visit fragment is the
        // one place a question is filled in, so only that node's `prompt`
        // is touched here.
        data: 'prompt' in node.data ? { ...node.data, prompt: STARTER_QUESTION } : node.data,
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
export function placeFirstRunStarter(
  workbench: Workbench,
  store: KeyValueStore,
  readiness: StarterReadiness | null = null,
): void {
  // `null` by default, and it is the honest default: on first paint the
  // health poll has usually not answered, and a note that accused an install
  // of having no model on no evidence would be the defect `serverReadiness`
  // itself exists to end. `refreshStarterNote` catches up when the answer
  // lands.
  workbench.controller.clipboard.insertFragment(firstRunFragment(readiness), NOTE_AT);
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

/* ---------------- after the first run ---------------- */

/**
 * A run that has just ended, in the terms the note needs.
 *
 * Deliberately **not** a runtime type: this module is copy and placement, and
 * importing a run's own payload would tie the first-visit text to an
 * execution shape it has no other business with. The shell translates once,
 * at the seam it already listens on.
 *
 * `models` is one name per model the run reported. The program design said it
 * comes from "`usage`'s first model key", and that is exactly right about the
 * **backend** run's `RunUsage[]` — one row per model — which is what the shell
 * reads. It is not true of `workbench.engine`'s `run:finish`, whose `usage` is
 * a `TokenUsage`: three counts and no model name anywhere in it. The plan named
 * the wrong one of the two, and `AppShell.tsx` records how that was found.
 */
export type StarterRunOutcome =
  | { readonly ok: true; readonly models: readonly string[]; readonly totalTokens: number }
  | { readonly ok: false; readonly reason: string };

/** How much of a failure's own sentence the note will carry. */
const REASON_LIMIT = 160;

/**
 * Which model to name, and how to admit the others.
 *
 * Program design, least-confident decision 3: a run that touched several
 * models names the first and counts the rest. A note whose entire argument is
 * that it is short cannot print a list.
 */
function namedModel(models: readonly string[]): string {
  const first = models[0];
  if (first == null) return 'The agent';
  const others = models.length - 1;
  return others > 0 ? `**${first}** (and ${others} more)` : `**${first}**`;
}

/**
 * What the note says once the first run has finished.
 *
 * Three jobs, the same discipline as the before-run wording: say **who
 * answered and what it cost** (the one thing a stranger cannot deduce from
 * the canvas), say **what to change next**, and stop claiming the run has not
 * happened. It drops `BEFORE_RUN_MARKER`, which is what makes the rewrite
 * happen exactly once.
 *
 * A failure quotes the run's own sentence rather than inventing a second
 * wording for the same fact — clamped to `REASON_LIMIT`, because an error
 * string has no length ceiling and this note does.
 */
export function afterRunNote(outcome: StarterRunOutcome): string {
  if (!outcome.ok) {
    const reason = outcome.reason.trim();
    const quoted =
      reason.length > REASON_LIMIT ? `${reason.slice(0, REASON_LIMIT).trimEnd()}…` : reason;
    return [
      '# The run stopped',
      '',
      quoted,
      '',
      'Press Run again once that is sorted. This note is yours to delete.',
    ].join('\n');
  }
  return [
    '# It ran',
    '',
    `${namedModel(outcome.models)} answered — ${outcome.totalTokens.toLocaleString()} tokens. The answer is in the **Output**.`,
    '',
    'Change the question in the **Input** and press Run again.',
    '',
    // The step the note used to stop short of (`stable-beta-public/31`). Both
    // halves are things nothing else on the canvas can say: a saved workflow
    // becomes a **package**, which is both mountable and reopenable; and the
    // name the first save asks for is not a label but a directory, minted into
    // a slug and then frozen. **Package**, never *template* — the second is a
    // scaffold that copies and stops existing, and teaching the wrong one on
    // the first screen a stranger reads teaches it first.
    'Save it and it appears under **Packages** — drag it into another workflow as one step, ' +
      'or press Open to edit it. The first save asks for a name; that name becomes its folder.',
    '',
    'This note is yours to delete.',
  ].join('\n');
}

/**
 * The starter's note, if it is still waiting for its first run.
 *
 * By type and marker rather than by id, because the placed note does not keep
 * `NOTE_ID` (see above). The marker is the last line of every before-run
 * wording, so a note the user has edited — even to add one word at the end —
 * is no longer awaiting anything and is left alone. That is the intended
 * reading, not a limitation: the rewrite overwrites a whole body, and a body
 * somebody has been typing in is not ours to overwrite.
 */
export function starterNoteAwaitingRun(workbench: Workbench): NodeId | null {
  for (const node of workbench.model.nodes()) {
    if (node.type !== NOTE_TYPE) continue;
    const body = node.data['body'];
    if (typeof body === 'string' && body.endsWith(BEFORE_RUN_MARKER)) return node.id;
  }
  return null;
}

/**
 * Rewrites the still-awaiting starter note to explain the run that just ended.
 *
 * Through `controller.nodes.setField` — a `SetFieldCommand` — so it is one
 * undoable step and the model stays the truth the canvas is projected from.
 * Writing to the node's data directly would put text on a canvas the history
 * cannot account for, and `Cmd-Z` after a run would then undo something else.
 *
 * Returns whether it wrote. `false` is the ordinary case for every run after
 * the first, and for a note the user deleted or edited — none of which is a
 * failure worth reporting anywhere.
 */
export function explainFirstRun(workbench: Workbench, outcome: StarterRunOutcome): boolean {
  const noteId = starterNoteAwaitingRun(workbench);
  if (noteId == null) return false;
  workbench.controller.nodes.setField(noteId, 'body', afterRunNote(outcome));
  return true;
}

/**
 * Rewrites a note that is **still waiting** to match a readiness that has
 * just changed.
 *
 * The flip, in both directions. A note placed before `/api/health` answered
 * says *press Run*; if the answer is that nothing can run, the invitation has
 * become false and is replaced by the server's sentence. A key that appears
 * while the note is still up is the same event backwards, and reads back to
 * *press Run*.
 *
 * Three things it will not do. It will not touch a note the run has already
 * explained or the user has edited — both have lost the marker, which is what
 * "still ours" means everywhere in this file. It will not touch a canvas that
 * never held a starter. And it pushes **no command** when the wording it
 * would write is the wording already there: readiness announces on every poll
 * that moves any field, and a history full of identical note writes would
 * make Cmd-Z mean nothing.
 */
export function refreshStarterNote(
  workbench: Workbench,
  readiness: StarterReadiness | null,
): boolean {
  const noteId = starterNoteAwaitingRun(workbench);
  if (noteId == null) return false;
  const next = beforeRunNote(readiness);
  if (workbench.model.node(noteId)?.data['body'] === next) return false;
  workbench.controller.nodes.setField(noteId, 'body', next);
  return true;
}

/**
 * What a failed first run is allowed to say about why.
 *
 * Three sources and no fourth, in the order a reader would want them:
 *
 * - **The readiness sentence**, when the wall is a missing provider. The same
 *   sentence the before-run note quotes, so one fact has one wording — and it
 *   is the only one of the three that names the thing to *do*.
 * - **The run's own error**, when there was a model and it still failed.
 * - **An admission**, when neither exists. `runView` carries no error text
 *   today (checked, not assumed: its fields are `source`, `question`, `rows`,
 *   `running`, `threadId`, `usage`), so this is the branch a failed run
 *   without a readiness wall actually takes. It says the run reported nothing
 *   and points at the timeline, which is true; guessing at a cause on no
 *   evidence would be the same defect the no-model wording refuses.
 */
export function failedRunReason(input: {
  readonly readiness: StarterReadiness | null;
  readonly error: string | null;
}): string {
  const readiness = input.readiness;
  if (readiness != null && !readiness.modelConfigured) {
    const sentence = readiness.runReadiness.trim();
    if (sentence !== '') return sentence;
  }
  const error = input.error?.trim();
  if (error != null && error !== '') return error;
  return 'The run reported no reason. The timeline along the bottom has what it did.';
}
