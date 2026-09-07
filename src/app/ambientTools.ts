/**
 * The tools every agent on this server binds without being wired to them.
 *
 * **The gap** (`every-workflow-green` 05a). An agent drawn with two tools
 * actually had five: the prebuilt memory tools bind to *every* agent when the
 * server has a store configured. A developer reading the canvas could not
 * enumerate their own agent's capabilities, and the truth appeared only because
 * a model hallucinated a tool name and provoked the runtime into listing the
 * real ones. Nothing reported it.
 *
 * The backend publishes it now, on the capabilities response, derived from the
 * same condition the runtime branches on rather than from a list somebody keeps
 * in step. This is where the editor keeps the answer.
 *
 * **A store rather than a prop**, for the reason `capabilityWarnings` records
 * one file over: it arrives asynchronously — after a load, after a Refresh —
 * and it is a **standing** condition rather than an event.
 *
 * **Conditional on the environment, never on the document.** A server with no
 * store binds none, which is why this is fetched rather than written on a card:
 * a hardcoded note would be false on that server. An empty list is a real
 * answer and renders as *nothing at all* — "none configured" would be a claim
 * about a workflow, when the fact belongs to a server.
 */

let tools: readonly string[] = [];
const listeners = new Set<() => void>();

/** The whole truth from the last capabilities fetch. Replaces, never appends. */
export function setAmbientTools(next: readonly string[]): void {
  tools = next;
  for (const listener of listeners) listener();
}

/**
 * Safe as a `useSyncExternalStore` snapshot: the reference changes only when
 * `setAmbientTools` runs, so a subscriber cannot loop on a fresh array.
 */
export function ambientTools(): readonly string[] {
  return tools;
}

/** Subscribe, `useSyncExternalStore`-shaped. Returns the unsubscribe. */
export function onAmbientToolsChange(handler: () => void): () => void {
  listeners.add(handler);
  return () => listeners.delete(handler);
}
