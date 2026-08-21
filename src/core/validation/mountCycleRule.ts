/**
 * Whether a mount would make a workflow include itself.
 *
 * The server already refuses this twice, in two different ways — the ancestry
 * chain in `compile/node_runtime.py::_subgraph` and the visited chain in
 * `api/mount_resolution.py`. The editor compared **nothing**, so a user could
 * pick their own package as a mount, save it, and learn about it only when the
 * run failed to compile (organisms-first-class ticket 42).
 *
 * Three properties, each deliberate, and each from ticket 10's direction:
 *
 * - **The server stays the authority.** This is a courtesy that reports the
 *   same refusal earlier. It must never be weakened *or* widened — a client
 *   that refuses something the compiler would accept is worse than one that
 *   refuses nothing, because the only way out is to fight the editor.
 * - **The server's own sentence, verbatim.** A user who hits this both ways
 *   reads one sentence, not two that sound like different problems. The Python
 *   is `f"Workflow {slug!r} mounts itself ({chain}); "
 *   "a mount cycle can never terminate"` — `!r` on a plain slug is single
 *   quotes, which is why they are single quotes here. It said "includes itself
 *   through its subgraphs … a subgraph cycle" until consistency-sweep ticket
 *   10: a LangGraph name, twice, in the sentence a user reads most often, and
 *   describing a construct this compiler does not emit.
 * - **Ancestry, not one slug.** Drill-in makes this more than a self-check: you
 *   can be three levels deep in a mount chain, and the cycle you would create
 *   is not with the document you are looking at.
 *
 * A forward reference stays legal. The slug field is free text on purpose —
 * sketching a parent before building its child is a real way to work — and a
 * package that does not exist yet cannot be an ancestor of anything.
 *
 * Pure: a candidate and a trail in, a sentence or nothing out. No React, no
 * storage, no catalogue. Who supplies the trail is the caller's problem, which
 * is what makes the rule testable at every depth without an editor.
 */
export function mountCycleRefusal(
  candidateSlug: string,
  /** The slugs above this document, oldest first — the drill trail then here. */
  ancestry: readonly string[],
): string | null {
  const chain = cycleChain(candidateSlug, ancestry);
  if (chain === null) return null;
  return `Workflow '${chain.candidate}' mounts itself (${chain.path}); ${NEVER_TERMINATES}`;
}

/**
 * The same rule, asked about a **gesture** rather than about a document.
 *
 * `workflow-gallery` 65. `mountCycleRefusal` is the compiler's sentence and it
 * is in the **indicative**: it says a workflow *mounts itself*, which is a fact
 * about a document that already declares the mount. That is exactly right where
 * a mount node exists and a slug has been typed into its field — and exactly
 * wrong on a Packages palette row, where nothing has been dropped yet.
 *
 * A package scaffolded with `openstategraph new` is both the document on screen
 * and the only row in the Packages section, so its own row refuses — correctly,
 * because dropping it there would not compile — and it was refusing with a
 * sentence that read as a diagnosis of a graph the user had not drawn. On the
 * first screen after `new`, with no mount node anywhere in the document, the
 * product accused itself of being broken.
 *
 * So: same rule, same path, same closing clause, **conditional mood**. The
 * refusal set is byte-for-byte the same one — widening or narrowing it here is
 * how the editor and the server start disagreeing, which is the one failure
 * this family must not have — and only the tense differs, because only the
 * tense was ever wrong.
 *
 * Use this wherever the mount does not exist yet and a user is being told why a
 * gesture is unavailable. Use `mountCycleRefusal` where the document really
 * does name the mount.
 */
export function mountGestureRefusal(
  candidateSlug: string,
  /** The slugs above this document, oldest first — the drill trail then here. */
  ancestry: readonly string[],
): string | null {
  const chain = cycleChain(candidateSlug, ancestry);
  if (chain === null) return null;
  return `Mounting '${chain.candidate}' here would make it mount itself (${chain.path}); ${NEVER_TERMINATES}`;
}

/** The compiler's closing clause, shared so the two moods cannot drift apart. */
const NEVER_TERMINATES = 'a mount cycle can never terminate';

/**
 * The one comparison both sentences are made of: is the candidate already on
 * the trail, and if so what route produced the cycle.
 *
 * Single-sourced deliberately. Two spellings of this would agree on the day
 * they were written and disagree on the first edit to either.
 */
function cycleChain(
  candidateSlug: string,
  ancestry: readonly string[],
): { candidate: string; path: string } | null {
  const candidate = candidateSlug.trim();
  if (!candidate) return null;

  const trail = ancestry.map((slug) => slug.trim()).filter((slug) => slug !== '');
  if (!trail.includes(candidate)) return null;

  // The whole trail plus the candidate, exactly as `_subgraph` spells it:
  // `" -> ".join((*self._ancestry, slug))`. Not the trail truncated at the
  // match — the chain a reader needs is the route that produced the cycle.
  return { candidate, path: [...trail, candidate].join(' -> ') };
}
