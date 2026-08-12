import { PaperFeature, type PaperFeatureContext } from './IPaperFeature';

/** Schedules `run` for after the current frame, returning a cancel function. */
export type FrameScheduler = (run: () => void) => () => void;

const defaultScheduler: FrameScheduler =
  typeof requestAnimationFrame === 'function'
    ? (run) => {
        const handle = requestAnimationFrame(run);
        return () => cancelAnimationFrame(handle);
      }
    : (run) => {
        const handle = setTimeout(run, 0);
        return () => clearTimeout(handle);
      };

/**
 * Frames the document whenever the document is *replaced*.
 *
 * The camera is a projection of the model, and a wholesale replacement is a
 * new coordinate space: the child of a mounted team lives nowhere near its
 * parent's mount card, and a transform chosen for one graph means nothing
 * for the other. Before this, drilling into a Team/Workflow mount — or
 * coming back out, or loading a workflow from the panel — left the camera
 * exactly where it was, so the nodes and edges of the newly loaded document
 * were off screen or at an unreadable scale. That is the bug; three of the
 * call sites had a hand-written `requestAnimationFrame(fit)` and three did
 * not, which is precisely the kind of knowledge that must live in one place.
 *
 * A feature rather than a method, because it is an installable behaviour of
 * the canvas with its own lifetime — and because it makes the rule testable
 * without a paper.
 *
 * Only `workflow:reset` counts. Ordinary edits — add, move, delete — must
 * never move the camera; a canvas that re-fits while you are working is
 * worse than one that never fits at all.
 *
 * The frame is deferred and coalesced: the adapter rebuilds the graph on the
 * same event, React then mounts a card per node, and `model.bounds()` is
 * only meaningful once those have landed. Deferring also means a load that
 * emits two resets costs one fit.
 */
export class FrameOnLoadFeature extends PaperFeature {
  readonly id = 'frameOnLoad';

  private cancel: (() => void) | null = null;

  constructor(private readonly schedule: FrameScheduler = defaultScheduler) {
    super();
  }

  protected onInstall(ctx: PaperFeatureContext): void {
    this.addTeardown(ctx.controller.model.on('workflow:reset', () => this.frameSoon()));
    this.addTeardown(() => this.clearPending());
  }

  private frameSoon(): void {
    this.clearPending();
    this.cancel = this.schedule(() => {
      this.cancel = null;
      this.ctx.viewport.fit(this.ctx.controller.model.bounds());
    });
  }

  private clearPending(): void {
    this.cancel?.();
    this.cancel = null;
  }
}
