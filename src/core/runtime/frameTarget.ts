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
 * **Project onto whatever document is open.**
 *
 * ## What the first version got wrong, and how the browser said so
 *
 * That rule was right; the evidence it was given was not, and it took a real
 * streamed run to show it — this module shipped unit-tested and unverified,
 * and both of its assumptions turned out to be false on the wire:
 *
 * 1. *"`node` is the child's own step."* It is whatever **LangGraph** called
 *    the step. Inside an agent's compiled loop that is literally `model` or
 *    `tools`; inside a mounted document it is the compiler's `safe_name`, so
 *    the child's `agent-sql` arrives as `agent_sql` — a string with no hyphen,
 *    which the child document therefore does not contain either. Opening the
 *    mount matched neither end and lit nothing at all: the static diagram the
 *    ticket describes, produced by this function returning `null` correctly.
 * 2. *"A parent never contains its child's node ids."* The two shipped
 *    documents, `concierge` and `chinook-assistant`, share `in1`, `router1`
 *    and `out1`. Preferring the frame's own node meant the parent canvas lit
 *    its own input node while the child's input step ran.
 *
 * Both are fixed by the frame carrying a **path** — the chain of canvas node
 * ids from the outermost document inward, resolved server-side where the
 * mounted documents' ids are actually known (`RunPathResolver`). Walk it
 * **outermost-first** and stop at the first id this document has: the parent
 * stops at the mount, the child (which has no mount) walks on to the real
 * step, and the shared `in1` can no longer pull the parent inward.
 *
 * The older node/owner rule stays underneath as the fallback, so a frame with
 * no usable path — or a server that predates the field — behaves as before.
 */
import type { MountAddress } from '@core/model/MountAddress';

export interface RunFrameEnds {
  /** The step that actually ran, as the *runtime* named it. */
  readonly node: string;
  /** The top-level node that owns it — the mount, for anything nested. */
  readonly activeNode?: string;
  /**
   * Canvas node ids from the outermost document inward, one per level of
   * nesting the frame passed through. Optional: absent on a terminal frame
   * and on any server that predates it.
   */
  readonly path?: readonly string[];
  /**
   * Which document each entry of `path` belongs to — same length, same order.
   *
   * Ids are unique only *within* a document, and the shipped pair is the
   * counterexample: `concierge` mounts `chinook-assistant` and both have
   * `in1`, `router1` and `out1`. Matching on id alone would light the child's
   * router when the parent's router ran. An entry is `''` when the slug could
   * not be determined, which means "no claim" rather than "no match".
   */
  readonly pathSlugs?: readonly string[];
}

/**
 * @param hasNode whether the open document contains an id. Injected rather
 *   than taking a model, so the decision is a pure function over an id, a
 *   predicate and an address — `core/` owes nothing to the canvas here.
 * @param open the **address** the caller is displaying, when it knows.
 *
 *   An address, not a slug, and that is tranche 6's whole substance. A slug
 *   names the *class*, and `concierge` may mount `chinook-assistant` twice —
 *   so `pathSlugs` holds that slug at more than one level and `indexOf`
 *   answered with the first, lighting a card in the instance nobody was
 *   looking at, carrying the other instance's values. The address names which
 *   mount, and the frame's `path` is the same vocabulary, so the two line up
 *   position for position.
 */
export function frameTarget(
  frame: RunFrameEnds,
  hasNode: (id: string) => boolean,
  open?: MountAddress,
): string | null {
  const path = frame.path ?? [];
  const slugs = frame.pathSlugs ?? [];

  // The exact rule: this run's path and this address are the same chain of
  // mount ids, so the document on screen sits at exactly `mountPath.length`
  // levels in. Guarded on the root, because an address only indexes a run
  // rooted at the same document — open the shared definition mid-run and the
  // class rule below is the one that applies.
  if (open && path.length > 0 && (slugs[0] ?? open.root) === open.root) {
    const depth = open.mountPath.length;
    const prefixMatches = open.mountPath.every((segment, index) => path[index] === segment);
    if (prefixMatches) return depth < path.length ? (path[depth] ?? null) : null;
    // The address indexes this run, and this frame is on a different branch of
    // it — a sibling mount. Saying so is the answer; it is the case the slug
    // could not express.
    return null;
  }

  // The older class-level rule, for a frame whose run is rooted somewhere the
  // address cannot index.
  if (open && slugs.length > 0) {
    const level = slugs.indexOf(open.root);
    if (level >= 0 && level < path.length) return path[level] ?? null;
    // Every level was nameable and none was us: this frame is genuinely about
    // some other document, and saying so is an answer rather than a gap. If
    // any level could *not* be named, the evidence is incomplete and the id
    // walk below decides instead.
    if (slugs.every((slug) => slug !== '')) return null;
  }

  // Outermost-first, and that ordering is the substance rather than a
  // detail — see the header. The first hit is the level this document sits
  // at, because every id shallower than it belongs to a document that
  // mounts this one and cannot be a card here.
  for (const step of path) {
    const id = step?.trim();
    if (id && hasNode(id)) return id;
  }

  const own = frame.node?.trim();
  if (own && hasNode(own)) return own;

  const owner = frame.activeNode?.trim();
  if (owner && hasNode(owner)) return owner;

  // Neither end is on this canvas: a frame from a sibling branch of a
  // document nobody is looking at. Lighting nothing is the honest outcome —
  // the alternative is lighting whichever card happens to share an id.
  return null;
}

/**
 * Whether this frame's `output` belongs to `target` — the card `frameTarget`
 * just chose.
 *
 * A frame from inside a mount lights the mount's card on the parent canvas,
 * and it has nothing to say about that card: the text belongs to a step one
 * level down. So the value needs its own gate, and the gate is *not*
 * `frame.node === target`, which is what both call sites used to ask.
 *
 * `node` is the **runtime's** name for the step — `model` or `tools` inside a
 * compiled agent loop, otherwise the compiler's `safe_name`, which rewrites
 * every non-alphanumeric character. Inside a mount it therefore never equals a
 * canvas id, so the comparison answered `false` for every nested node and the
 * output was dropped on the floor. Captured on a real `?w=concierge` run: the
 * child's cards glowed and stayed empty for the whole run.
 *
 * `path` already answers this exactly. Its last entry is the frame's own card,
 * in its own document — one level deep for a top-level step, deeper for a
 * mounted one. A frame with no path falls back to the old comparison, so a
 * server that predates the field behaves as it did.
 *
 * Declared beside `frameTarget` rather than inlined at each caller because it
 * is one rule about one wire format, and the live path and the replay path
 * disagreeing about it is precisely how half a fix ships.
 */
export function frameOwnsOutput(frame: RunFrameEnds, target: string): boolean {
  const path = frame.path ?? [];
  if (path.length > 0) return path[path.length - 1]?.trim() === target;
  return frame.node?.trim() === target;
}
