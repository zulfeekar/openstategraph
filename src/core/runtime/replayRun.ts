import { frameTarget, type RunFrameEnds } from './frameTarget';

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
 * @param openSlug the workflow now on screen, when known. Passed straight
 *   through to `frameTarget`, and it matters more here than on the live path:
 *   a replay writes every frame at once, so an id shared by two documents
 *   would repaint a whole history that never happened here.
 */
export function replayRun(
  frames: readonly ReplayFrame[],
  hasNode: (id: string) => boolean,
  running: boolean,
  openSlug?: string,
): readonly ReplayWrite[] {
  // Insertion-ordered, and that is the point: a node the run visited twice —
  // a revise loop's second lap — keeps its first position and its latest
  // output, so the replay reads as the path taken rather than the path
  // re-sorted.
  const settled = new Map<string, ReplayWrite>();
  let last: string | null = null;

  for (const frame of frames) {
    const target = frameTarget(frame, hasNode, openSlug);
    // A frame belonging to a sibling branch of a document nobody has open.
    // Skipped rather than defaulted, exactly as the live path skips it.
    if (target === null) continue;
    const output = frame.node === target && frame.output != null ? frame.output : undefined;
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
