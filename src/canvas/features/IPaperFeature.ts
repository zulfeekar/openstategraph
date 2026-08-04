import type { dia } from '@joint/core';
import type { IDisposable } from '@core/kernel/Disposable';
import type { IIdentifiable } from '@core/kernel/Registry';
import type { WorkflowController } from '@controller/WorkflowController';
import type { JointGraphAdapter } from '../JointGraphAdapter';
import type { Viewport } from '../Viewport';

/** Everything a feature is given when it installs. */
export interface PaperFeatureContext {
  readonly paper: dia.Paper;
  readonly graph: dia.Graph;
  readonly adapter: JointGraphAdapter;
  readonly controller: WorkflowController;
  readonly viewport: Viewport;
  /** The clipping element the paper is mounted inside. */
  readonly container: HTMLElement;
}

/**
 * One installable canvas behaviour.
 *
 * The commercial JointJS bundle ships selection, snaplines, scrolling,
 * keyboard handling and a navigator as separate plugins; the open-source
 * core ships none of them. Rebuilding each as a feature behind this
 * interface keeps that same shape: the paper stays a dumb renderer, each
 * behaviour is independently testable and individually removable, and
 * adding one means registering it rather than editing a growing setup
 * function.
 *
 * Every feature must undo everything it installed on `dispose` — a canvas
 * gets torn down and rebuilt whenever the document is replaced.
 */
export interface IPaperFeature extends IIdentifiable, IDisposable {
  readonly id: string;
  install(ctx: PaperFeatureContext): void;
}

/**
 * Base class handling the parts every feature repeats: holding the context
 * and tracking teardown.
 */
export abstract class PaperFeature implements IPaperFeature {
  abstract readonly id: string;

  protected ctx!: PaperFeatureContext;
  private readonly teardown: (() => void)[] = [];

  install(ctx: PaperFeatureContext): void {
    this.ctx = ctx;
    this.onInstall(ctx);
  }

  protected abstract onInstall(ctx: PaperFeatureContext): void;

  /** Registers a JointJS event handler that is removed on dispose. */
  protected onPaper(event: string, handler: (...args: never[]) => void): void {
    this.ctx.paper.on(event, handler as never);
    this.teardown.push(() => this.ctx.paper.off(event, handler as never));
  }

  protected onGraph(event: string, handler: (...args: never[]) => void): void {
    this.ctx.graph.on(event, handler as never);
    this.teardown.push(() => this.ctx.graph.off(event, handler as never));
  }

  /** Registers a DOM listener that is removed on dispose. */
  protected onDom<T extends EventTarget>(
    target: T,
    type: string,
    handler: (event: never) => void,
    options?: AddEventListenerOptions,
  ): void {
    target.addEventListener(type, handler as EventListener, options);
    this.teardown.push(() => target.removeEventListener(type, handler as EventListener, options));
  }

  protected addTeardown(fn: () => void): void {
    this.teardown.push(fn);
  }

  dispose(): void {
    // Reverse order, so a handler installed on top of another is removed
    // first — same unwind semantics as the disposable store.
    for (let i = this.teardown.length - 1; i >= 0; i -= 1) {
      try {
        this.teardown[i]?.();
      } catch (error) {
        console.error(`[dyflow] feature "${this.id}" teardown failed`, error);
      }
    }
    this.teardown.length = 0;
  }
}
