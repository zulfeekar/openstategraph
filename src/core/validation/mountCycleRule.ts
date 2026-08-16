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
 *   is `f"Workflow {slug!r} includes itself through its subgraphs ({chain}); "
 *   "a subgraph cycle can never terminate"` — `!r` on a plain slug is single
 *   quotes, which is why they are single quotes here.
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
  const candidate = candidateSlug.trim();
  if (!candidate) return null;

  const trail = ancestry.map((slug) => slug.trim()).filter((slug) => slug !== '');
  if (!trail.includes(candidate)) return null;

  // The whole trail plus the candidate, exactly as `_subgraph` spells it:
  // `" -> ".join((*self._ancestry, slug))`. Not the trail truncated at the
  // match — the chain a reader needs is the route that produced the cycle.
  const chain = [...trail, candidate].join(' -> ');
  return (
    `Workflow '${candidate}' includes itself through its subgraphs (${chain}); ` +
    'a subgraph cycle can never terminate'
  );
}
