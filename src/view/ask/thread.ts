/**
 * Which conversation the next question belongs to.
 *
 * Two rules, both small enough to state and both wrong in ways that are
 * invisible from the UI — which is exactly why they are here as pure functions
 * rather than inline in `AskPanel`. A thread is a *server* object: nothing on
 * screen changes when a question is sent into the wrong one, and nothing on
 * screen changes when a question is sent into none. The defect that produced
 * this file was live for weeks for that reason.
 */

/**
 * The conversation in progress — the server-named thread, and the workflow it
 * is a conversation *about*.
 *
 * The pair is the point. LangGraph's checkpointer is keyed by thread id
 * **alone**, so an id carried across a workflow switch would replay the
 * previous document's `messages` into a different graph. Holding the slug
 * beside the id makes "a conversation about a different graph is a different
 * conversation" a property of the type rather than of a call site remembering
 * to check.
 *
 * `slug` is `undefined` for an unsaved canvas, and two unsaved canvases are
 * indistinguishable here — the same resolution the run itself has
 * (`workflowSlug`), so nothing new is lost.
 */
export interface ThreadBinding {
  readonly slug: string | undefined;
  readonly id: string;
}

/**
 * The `thread_id` to send with a question asked against `slug`, or `undefined`
 * to let the server open a new conversation.
 *
 * `undefined` is not a failure mode: the first question of any conversation
 * returns it, and the server names the thread it minted on the terminal frame.
 */
export function continuingThread(
  held: ThreadBinding | null,
  slug: string | undefined,
): string | undefined {
  if (!held) return undefined;
  return held.slug === slug ? held.id : undefined;
}

/**
 * Fold a terminal frame's disclosed thread id into what the panel holds.
 *
 * An empty `threadId` means "this frame said nothing about its thread" — an
 * older backend, or the non-streaming `POST /api/runs`, which names none. It
 * must never be read as "there is no thread", so it leaves what is held
 * untouched rather than clearing it: a run whose terminal frame was silent
 * still happened inside the conversation the previous one named.
 */
export function rememberThread(
  held: ThreadBinding | null,
  slug: string | undefined,
  threadId: string,
): ThreadBinding | null {
  if (!threadId) return held;
  if (held && held.slug === slug && held.id === threadId) return held;
  return { slug, id: threadId };
}
