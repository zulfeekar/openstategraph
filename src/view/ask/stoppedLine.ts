/**
 * What the panel may honestly say about a run the developer stopped.
 *
 * **Two states used to produce one output** — the shape this repository keeps
 * paying for. Stopping a live run always printed *"nothing further is
 * scheduled. Steps already dispatched finish in the background and their
 * results are discarded."* That sentence was true when it was written and is
 * still true of some nodes, but since `async-first`'s Phase D it is false of
 * the ones it matters most for: an agent, a worker, a mounted workflow and an
 * orchestrator are all `async def`, and stopping cancels the body outright.
 *
 * Nothing on the clock distinguishes them. The stop is instant either way —
 * the connection closes, no further superstep is scheduled — so a surface
 * that only measures how long the person waited would report the same number
 * for both, which is exactly what `async-first/09` measured (0.00 s, before
 * and after). The difference is in the *work*, and it is large. Measured live
 * on 2026-08-27, `morning-brief`'s three concurrent workers disconnected 12 s
 * into the run:
 *
 * | the step in charge | seconds of work billed after the stop |
 * | --- | --- |
 * | cancellable (`async def`) | 0.68 / 0.41 / 1.08 |
 * | not (`def`, run in a worker thread) | 24.16 / 12.65 / 16.51 |
 *
 * Which of the two it was is not inferable here. It is a property of the node
 * that happened to be in charge — in one workflow an agent is cancellable
 * while the grader after it is not — so the server says so, per node, on
 * every frame that names an active node (`interruptible`, `docs/api.md`).
 *
 * **The cancelled sentence deliberately stops short of "nothing is running".**
 * A cancelled body unwinds at its next `await`, so the provider call already
 * issued is still finished and still paid for: 0.41–4.85 s across the nine
 * live runs behind this module. Claiming silence would be the next false
 * readout on this surface rather than the end of one.
 */

/** How a stopped turn ended — never a boolean, because there are three. */
export type StoppedHow = 'cancelled' | 'abandoned' | 'paused' | null;

/**
 * `'cancelled'` if the node in charge was one a stop reaches, else
 * `'abandoned'`.
 *
 * `false` — including the `false` a backend that predates the field produces
 * — is the conservative answer on purpose: it earns the sentence this product
 * has always shown, so an unknown node overstates nothing.
 */
export function howAStopEnded(interruptible: boolean): 'cancelled' | 'abandoned' {
  return interruptible ? 'cancelled' : 'abandoned';
}

export function stoppedLine(how: StoppedHow): string {
  switch (how) {
    case 'cancelled':
      return (
        'Stopped by you — the step that was running was cancelled, and nothing further ' +
        'is scheduled. The model call it had already sent still finishes; its result is ' +
        'discarded.'
      );
    case 'abandoned':
      return (
        'Stopped by you — nothing further is scheduled. Steps already dispatched cannot ' +
        'be interrupted: they finish in the background and their results are discarded.'
      );
    case 'paused':
      return (
        'Stopped by you — this run was waiting for approval, so nothing was interrupted. ' +
        'It stays checkpointed on the server and can still be resumed.'
      );
    default:
      return '';
  }
}
