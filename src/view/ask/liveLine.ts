/**
 * How long the one live line stays on screen.
 *
 * A pure function rather than a condition inside `AskPanel`'s `update`
 * handler, for the same reason `progressLine.ts` is one: what goes wrong here
 * is invisible from the panel. The rule was a bare `progress: null` inlined in
 * that handler, and it was wrong for two years' worth of frames without ever
 * failing a build or looking wrong in a screenshot — the line was on screen,
 * just for a handful of milliseconds each time (`launch-readiness/110`).
 */

/**
 * What is on screen right now, and **who said it**.
 *
 * The node is not decoration: the whole rule below is about telling a step's
 * own completion apart from the completion of the work that step announced.
 */
export interface LiveLine {
  readonly node: string;
  readonly text: string;
}

/**
 * The live line after `completedNode` finished — the same line, or nothing.
 *
 * A completed step makes the live line stale, **unless it is the step that
 * spoke**. That exception is the whole fix, and it is not a special case: a
 * narration line is written from a `before_*` hook, describing work that has
 * not happened yet, and the hook is itself a traced step whose `update` frame
 * lands microseconds later. Clearing on that frame meant the line announcing a
 * forty-second model call was erased before the model call began — which is
 * how a run with narration on the wire read, on screen, exactly like a run
 * with none.
 *
 * The half that was already right is kept: the tool line
 * `"Calling mcp_list_lenses on http://localhost:8080/mcp/"` must not outlive
 * its tool call, and it does not — `tools` completing no longer clears it, but
 * the next step's `update` does, one frame later.
 */
export function liveLineAfterStep(line: LiveLine | null, completedNode: string): LiveLine | null {
  if (line === null) return null;
  return line.node === completedNode ? line : null;
}
