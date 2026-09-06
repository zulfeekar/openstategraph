/**
 * What the compiler calls a canvas node, and how to read that back.
 *
 * A compiled `StateGraph` names its nodes `safe_name(node_id)`, and every
 * checkpoint namespace, run frame and lane header a user ever sees carries
 * that name rather than the one on the card. Turning one back into something
 * a reader recognises has exactly one honest direction.
 *
 * **Forward, never reverse.** `safe_name` is not injective — it rewrites every
 * non-alphanumeric character to `_`, so `worker_web` could have come from
 * `worker-web`, `worker.web` or `worker_web`, and a label that quietly names
 * the wrong node is worse than one that looks technical. So: mangle every id
 * in the document *this* client has open, and look the stored name up in the
 * result. Nothing is guessed, and a name with no entry stays as stored.
 *
 * The live run path answers the same question server-side, where the mounted
 * documents' ids are known (`RunPathResolver`, consumed by `frameTarget`).
 * This is for the surfaces that read a *stored* run: they are about the
 * document on the canvas now, which the checkpointer has never seen.
 */

/**
 * A graph-legal name for a workflow node id.
 *
 * Mirrors `safe_name` in `backend/openstategraph/compile/workflow_compiler.py`
 * — LangGraph reserves `:` and our ids look like `node:agent.llm-1`, so
 * `add_node` raises on the id verbatim. Two languages hold one rule, so
 * `graphName.test.ts` pins this to the compiler's own expression rather than
 * to a memory of it.
 */
export function safeName(nodeId: string): string {
  return Array.from(nodeId, (ch) => (/[0-9A-Za-z_]/.test(ch) ? ch : '_')).join('');
}

/** The parts of a node this module needs: who it is, and what it is called. */
export interface NamedNode {
  readonly id: string;
  readonly title: string;
  /** Whether `title` is the node's own name or its type's label. */
  readonly hasCustomTitle: boolean;
}

/**
 * Graph node name → what the open document calls that node.
 *
 * Two rules, and the second is the reason the reverse mangling was refused:
 *
 * - **A type label is not a name.** `INodeModel.title` falls back to the node
 *   *type's* label, and an untitled node is common: `support-triage` ships
 *   three `tool.email-send` nodes with no title, so `title` is `"Send email"`
 *   for all three. Resolving to that would replace distinct technical names
 *   with identical readable ones. So the display name is the node's *own*
 *   title when it has one, and its canvas id otherwise — the id being what the
 *   document and the inspector call that node.
 * - **A collision resolves to nothing.** If two ids mangle to one name the
 *   entry is dropped rather than won by whichever came first, because the
 *   whole reason for not reversing was that naming the wrong node is the bad
 *   outcome, and first-wins is a reversal with better manners.
 */
export function displayNamesByGraphName(nodes: readonly NamedNode[]): ReadonlyMap<string, string> {
  const names = new Map<string, string>();
  const contested = new Set<string>();
  for (const node of nodes) {
    const name = safeName(node.id);
    if (names.has(name)) {
      contested.add(name);
      continue;
    }
    names.set(name, node.hasCustomTitle ? node.title : node.id);
  }
  for (const name of contested) names.delete(name);
  return names;
}
