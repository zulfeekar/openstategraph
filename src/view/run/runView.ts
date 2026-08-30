import type { RunUsage } from '@core/runtime/RuntimeClient';
import type { ActivityRow } from '../ask/traceTree';

/**
 * The run the dock is drawing, held where a panel cannot take it with it.
 *
 * `memory-and-replay` 51 settled the shape: **one component, two data
 * sources**. Live, the rows arrive frame by frame from the SSE stream the Ask
 * panel already owns. Finished, the same rows come back off a record. The dock
 * is written against neither — it is written against this snapshot, so the
 * lane rules, the dash-for-no-clock rule (`launch-readiness` 108) and every
 * fix a future defect earns are learned once rather than twice. 37's
 * resolution said the same thing about replay: *"that view, fed from storage
 * instead of a stream."*
 *
 * The same argument `conversationStore.ts` makes about the thread applies to
 * the run, and harder: the Ask panel is conditionally rendered, so closing it
 * is a real unmount, and a timeline that lived inside it would go dark the
 * moment a developer closed the chat to look at the canvas the run is drawing
 * on. That is precisely the reason to promote the surface out of the panel.
 *
 * **In memory, for this tab, for this load.** A run's trace is evidence about
 * a graph as it was; the transcript store gives the long form of why that is
 * not persisted, and nothing here disagrees with it.
 *
 * Framework-free, so what it holds is decidable without React.
 */
export interface RunView {
  /**
   * Where these rows came from. Not decoration: it is what tells the dock
   * whether the run has an end, and therefore whether a transport can honestly
   * be offered — *"a live run has no end yet; a slider that cannot reach its
   * right-hand edge is lying about what it can do."*
   */
  readonly source: 'live' | 'stored';
  /** What the run was asked, for the dock's own header. */
  readonly question: string;
  readonly rows: readonly ActivityRow[];
  /** True only while frames are still arriving. A stored run is never running. */
  readonly running: boolean;
  /**
   * The thread this run happened in — `''` when the run has not named one.
   *
   * `memory-and-replay` 61. The dock is outside the conversation, so *which
   * run is this* is a question it could not answer at all: the header could
   * say what was asked, and two runs of one question are one header. `53`'s
   * `started` frame carries this on the first frame of every stream and the
   * terminal frames carry it again, so a run identifies itself long before it
   * ends.
   *
   * `''` means *the run told us nothing about its thread*, never *there was no
   * thread* — the same reading `RunResult.threadId` documents, and the reason
   * the dock prints nothing rather than a placeholder.
   *
   * **There is no run id beside it, and none is invented.** This runtime
   * identifies a *turn*; a second identifier minted client-side would be a
   * second name for one thing, and a name the server has never heard is not
   * an identity a reader can look anything up with.
   */
  readonly threadId: string;
  /**
   * What the run spent, one row per model — `null` when it reported none.
   *
   * Widened rather than reached past, which is `61`'s own question. The
   * alternative was a second store for the identity and the cost, and the
   * property this snapshot exists for is that the dock is written against
   * **one** shape: a stored run fills these two fields from a record exactly
   * as a live one fills them from the terminal frame, and the panel learns the
   * `—`-not-`0` rule once. A second source would have made the dock's own
   * reader ask which of two objects is talking about the run it is drawing.
   *
   * It stays one *writer* — `AskPanel` — which is what `61` warned a second
   * source would cost. Two fields on one snapshot is a field; two snapshots is
   * a design change.
   *
   * Read by `runCost`, which is the whole of `14`'s rule: a mirror that stops
   * at the mapper is not a mirror. `RunUsage` had been parsed by
   * `RuntimeClient` since `56` and displayed by nothing.
   */
  readonly usage: readonly RunUsage[] | null;
}

const NOTHING: RunView = {
  source: 'live',
  question: '',
  rows: [],
  running: false,
  threadId: '',
  usage: null,
};

export class RunViewStore {
  #held: RunView = NOTHING;
  readonly #listeners = new Set<() => void>();

  /** The same object until something actually changes, so React can compare by identity. */
  read(): RunView {
    return this.#held;
  }

  /**
   * Show this run.
   *
   * Silent when nothing changed. The Ask panel calls this from an effect that
   * runs on every one of its renders — a streaming turn re-renders per frame —
   * so a store that notified unconditionally would re-render the dock for
   * every keystroke in the composer as well.
   */
  publish(view: RunView): void {
    const held = this.#held;
    if (
      held.source === view.source &&
      held.question === view.question &&
      held.running === view.running &&
      held.rows === view.rows &&
      held.threadId === view.threadId &&
      held.usage === view.usage
    ) {
      return;
    }
    this.#held = view;
    for (const listener of [...this.#listeners]) listener();
  }

  /** Back to having nothing to draw — a fresh canvas, a closed conversation. */
  clear(): void {
    this.publish(NOTHING);
  }

  subscribe(listener: () => void): () => void {
    this.#listeners.add(listener);
    return () => {
      this.#listeners.delete(listener);
    };
  }
}

/**
 * The one this tab uses.
 *
 * A module singleton for the same reason `AskPanel`'s conversation store is
 * one: the writer and the reader are two components that are mounted and
 * unmounted independently, and neither is an ancestor of the other. Threading
 * it through context would put a run's rows on the `Workbench`, which is the
 * model's, and a run writes to no model (`canvas-feels-right` 07).
 */
export const runView = new RunViewStore();
