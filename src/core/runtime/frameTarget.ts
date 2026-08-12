/**
 * Which card a run frame should light, for the document that is actually open.
 *
 * A frame from inside a mounted Team or Workflow carries two answers to
 * "where is the run": `node`, the step that really ran — an id belonging to
 * the *child* document — and `activeNode`, the top-level owner, which is the
 * mount's own card on the *parent* canvas. Both are true; which one is useful
 * depends entirely on which document you are looking at.
 *
 * The old rule preferred `activeNode` unconditionally. On the parent canvas
 * that is right, and it is why a mounted team glows as one card while it
 * works. But opening the mount — the editor *navigates* to the child, it does
 * not nest a canvas — left every inner card dark, because the only id the
 * projection ever offered belonged to a node that document does not contain.
 * A developer watching a team run, who opens the team to see it run, got a
 * static diagram.
 *
 * So the rule is not "am I inside a mount" — nothing needs to know that.
 * **Project onto whatever document is open**: prefer the frame's own node when
 * this document has it, since that is the precise answer, and fall back to the
 * owner when it does not. One expression, and the parent's behaviour is
 * unchanged because a parent never contains its child's node ids.
 */
export interface RunFrameEnds {
  /** The step that actually ran. Belongs to the innermost graph. */
  readonly node: string;
  /** The top-level node that owns it — the mount, for anything nested. */
  readonly activeNode?: string;
}

/**
 * @param hasNode whether the open document contains an id. Injected rather
 *   than taking a model, so the decision is a pure function over two strings
 *   and a predicate — `core/` owes nothing to the canvas here.
 */
export function frameTarget(frame: RunFrameEnds, hasNode: (id: string) => boolean): string | null {
  const own = frame.node?.trim();
  if (own && hasNode(own)) return own;

  const owner = frame.activeNode?.trim();
  if (owner && hasNode(owner)) return owner;

  // Neither end is on this canvas: a frame from a sibling branch of a
  // document nobody is looking at. Lighting nothing is the honest outcome —
  // the alternative is lighting whichever card happens to share an id.
  return null;
}
