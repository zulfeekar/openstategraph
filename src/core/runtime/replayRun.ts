import { frameOwnsOutput, frameTarget, type RunFrameEnds } from './frameTarget';
import type { MountAddress } from '@core/model/MountAddress';

/**
 * Catches a newly-opened document up to where the run already is (ticket 34).
 *
 * ## Why projecting each frame as it arrives is not enough
 *
 * `frameTarget` answers "which card should this frame light, on the document
 * that is open" — and it answers it *at the moment the frame arrives*. That is
 * the whole story only while the document stays put. It does not: clicking
 * **Edit workflow** on a mount loads the child into the same editor, and the
 * child has seen none of this run. Its input step, its router, the tools that
 * already returned — all of that streamed past while the parent was open, was
 * projected onto the parent (correctly, as the mount's one glowing card), and
 * is not recoverable from the canvas afterwards.
 *
 * So opening a mount mid-run showed a diagram that was live from that instant
 * *forward* and blank behind: the current step eventually lit up, but the
 * steps that led to it stayed grey, and the entry Input card still showed its
 * saved prompt rather than the question the run was carrying — because the
 * frame that said so had already gone by.
 *
 * The frames are not lost, though. The panel keeps every one of them as the
 * turn's activity, because that record is what the trace and timeline views
 * are built from. Replaying it through the same `frameTarget` gives the newly
 * opened document the state it would have had if it had been open all along.
 *
 * ## What it produces
 *
 * The **settled** result, not an animation: one write per node, in the order
 * the run first reached it. Re-pacing history through the highlight queue
 * would make opening a mount cost `MIN_HIGHLIGHT_MS` per step already taken —
 * a canvas that spends ten seconds catching up to a run that has moved on.
 * Everything that ran is `success`; the node the run is currently inside is
 * `running`; nothing else is touched.
 */

/** One recorded frame — structurally what `ActivityRow` already carries. */
export interface ReplayFrame extends RunFrameEnds {
  /** The node's settled output, when this frame reported one. */
  readonly output?: string | null;
}

/** One card to repaint, and what to say about it. */
export interface ReplayWrite {
  readonly nodeId: string;
  readonly status: 'running' | 'success';
  /** Present only when the run actually produced a value for this card. */
  readonly output?: string;
}

/**
 * @param frames the run's frames so far, oldest first.
 * @param hasNode whether the *newly opened* document contains an id — the same
 *   injected predicate `frameTarget` takes, for the same reason.
 * @param running whether the run is still live. A finished run leaves no card
 *   glowing, exactly as it would have if the document had been open at the end.
 * @param open the address now on screen, when known. Passed straight
 *   through to `frameTarget`, and it matters more here than on the live path:
 *   a replay writes every frame at once, so an id shared by two documents
 *   would repaint a whole history that never happened here.
 */
export function replayRun(
  frames: readonly ReplayFrame[],
  hasNode: (id: string) => boolean,
  running: boolean,
  open?: MountAddress,
): readonly ReplayWrite[] {
  // Insertion-ordered, and that is the point: a node the run visited twice —
  // a revise loop's second lap — keeps its first position and its latest
  // output, so the replay reads as the path taken rather than the path
  // re-sorted.
  const settled = new Map<string, ReplayWrite>();
  let last: string | null = null;

  for (const frame of frames) {
    const target = frameTarget(frame, hasNode, open);
    // A frame belonging to a sibling branch of a document nobody has open.
    // Skipped rather than defaulted, exactly as the live path skips it.
    if (target === null) continue;
    const output =
      frameOwnsOutput(frame, target) && frame.output != null ? frame.output : undefined;
    settled.set(target, {
      nodeId: target,
      status: 'success',
      // Kept from an earlier frame when this one carries nothing: a node that
      // reported its output and was then passed through again must not have
      // that output erased by the second visit.
      ...(output !== undefined ? { output } : pickOutput(settled.get(target))),
    });
    last = target;
  }

  // The last card the run reached is the one it is inside, and only while it
  // still is. Rewritten rather than special-cased in the loop so a node that
  // appears twice is still marked by its *final* appearance.
  if (running && last !== null) {
    const held = settled.get(last);
    settled.set(last, { ...(held as ReplayWrite), status: 'running' });
  }

  return [...settled.values()];
}

/** The `output` of a previous write, as a spreadable fragment. */
function pickOutput(previous: ReplayWrite | undefined): { output?: string } {
  return previous?.output !== undefined ? { output: previous.output } : {};
}

/**
 * A turn, as far as this decision is concerned.
 *
 * Structural rather than importing `AskPanel`'s own type: `core/` owes nothing
 * to the view, and this needs three fields out of a dozen.
 */
export interface ReplayCandidate {
  readonly running: boolean;
  /**
   * Why this turn is not running, when it was cut short rather than finished.
   *
   * Structural, like the rest of this interface, and deliberately widened to
   * the *shape* rather than the vocabulary: the words belong to
   * `view/ask/stoppedLine.ts`, and `core/` owes nothing to the view. Only the
   * null-ness is read below — a stopped turn of any kind is not replayed —
   * so a fourth word there costs nothing here.
   */
  readonly stopped: string | null;
  readonly activity: readonly ReplayFrame[];
  /**
   * The document this turn ran — the class slug open when it was sent, or
   * `null` for a never-saved one.
   *
   * Required rather than optional, and that is ticket 25's whole substance. A
   * turn without it is a run with no address, and every rule downstream is
   * then matching node ids that two unrelated documents happen to share.
   */
  readonly slug: string | null;
}

/**
 * The document on screen, as this decision needs it — two names, because a
 * mount has two.
 */
export interface OpenDocument {
  /**
   * The **root** of the address displayed: the parent document, when a mount
   * of it is open, and otherwise the same as `slug`. This is the one that
   * matches a run, because a run is rooted where it was started.
   */
  readonly root: string | null;
  /** The class slug of the document displayed. */
  readonly slug: string | null;
}

/**
 * Whether this run ever touched the document now on screen.
 *
 * Three ways it can have, and they are not interchangeable:
 *
 * 1. **It is this document's run** — `slug === root`. The ordinary case.
 * 2. **It is this document's parent's run** — a drill-in. `concierge/wf-music`
 *    displays `chinook-assistant` while the address root stays `concierge`,
 *    and those inner steps are exactly what ticket 34 exists to paint.
 * 3. **The run reached this document as a package** — someone opened the
 *    shared definition mid-run rather than drilling in, so the address cannot
 *    index the run and the evidence is in the frames' own `pathSlugs`.
 *
 * Anything else is another document's run, and the honest projection of
 * another document's run onto this canvas is nothing at all.
 */
function turnTouches(turn: ReplayCandidate, open: OpenDocument): boolean {
  if (turn.slug === open.root) return true;
  const here = open.slug;
  if (here === null) return false;
  return turn.activity.some((frame) => frame.pathSlugs?.includes(here) ?? false);
}

/**
 * Which turn a newly-opened document should catch up to, and whether to glow.
 *
 * Ticket 43. The subscription used to project the running turn and give up
 * otherwise — "a finished run leaves nothing to catch up to". That was true of
 * the *stream* and false of the *record*: the turn keeps every frame it
 * received, because the trace and timeline views are built from them, and
 * `replayRun` is a pure projection over exactly those frames. So the editor
 * showed a developer the run if they clicked into a mount fast enough, and a
 * static diagram if they did not — the same
 * *renders-what-was-saved-not-what-happened* shape as tickets 33 and 34, one
 * beat later.
 *
 * Two turns are deliberately **not** replayed:
 *
 * - **Stopped.** `AskPanel` marks every node `idle` when a run is stopped
 *   (ticket 33), because the developer abandoned it. Replaying it as a series
 *   of successes would undo that on the next document opened, claiming steps
 *   finished that never did.
 * - **Paused.** A run waiting on a human approval is mid-flight, and its
 *   interrupt node is `paused` — a state this projection does not model.
 *   Painting it as finished is a worse lie than painting nothing.
 *
 * The live turn still wins, and it is still the only one whose last card
 * glows: `running` rides out with the choice so the caller cannot pair the
 * wrong turn with the wrong flag.
 *
 * Ticket 25 added the document. A conversation outlives the workflow it was
 * asked about — the panel keeps its turns when the developer opens another
 * file — so "the newest turn" and "a turn about what I am looking at" stopped
 * being the same sentence, and the projection was answering the first while
 * meaning the second. See `turnTouches`.
 *
 * @param open the document on screen, when the caller knows it. Omitted means
 *   *no claim*, not *no match*: the per-frame rules in `frameTarget` stay the
 *   gate, exactly as they were.
 */
export function turnToReplay(
  turns: readonly ReplayCandidate[],
  open?: OpenDocument,
): { readonly turn: ReplayCandidate; readonly running: boolean } | null {
  const mine = open ? turns.filter((turn) => turnTouches(turn, open)) : turns;

  const live = mine.find((turn) => turn.running);
  if (live) return { turn: live, running: true };

  // Last first: a conversation's newest settled turn is the one whose state
  // the canvas should be showing.
  for (let index = mine.length - 1; index >= 0; index -= 1) {
    const turn = mine[index];
    if (!turn || turn.stopped !== null || turn.activity.length === 0) continue;
    return { turn, running: false };
  }
  return null;
}
