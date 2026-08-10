import type { dia } from '@joint/core';
import { CANVAS } from '@design/tokens';
import { DisposableStore, type IDisposable, type Unsubscribe } from '@core/kernel/Disposable';
import { EventBus } from '@core/kernel/EventBus';
import type { NodeId } from '@core/model/contracts/node';
import type { Rect } from '@core/kernel/geometry';
import type { Viewport } from '../Viewport';
import { decideFollow } from './followDecision';

/** Comfort inset: a target inside this share of the viewport is left alone. */
const COMFORT_MARGIN = 0.14;

interface FollowerEvents extends Record<string, unknown> {
  /** `reason` is set only when following was switched off by a gesture. */
  changed: { enabled: boolean; reason: string | null };
}

/**
 * Keeps the camera on whatever is running.
 *
 * A collaborator, not a method on `PaperController` — it owns a mode, a
 * latch and a set of active nodes, which is a reason to change all of its
 * own. The paper hands it a viewport and asks nothing else of it.
 *
 * **Never fights the user.** The moment a real gesture arrives — wheel,
 * pinch, drag — following latches off and stays off until the next run.
 * Detection is on the *input events*, not on viewport changes: a follower
 * that watched the transform would see its own moves and turn itself off,
 * and one that tried to filter its own moves would still misread the tail of
 * an animation. Watching gestures has no such ambiguity.
 */
export class RunFollower implements IDisposable {
  private readonly disposables = new DisposableStore();
  private readonly bus = new EventBus<FollowerEvents>();
  private readonly active = new Map<NodeId, Rect>();

  private wanted = false;
  private latchedOff = false;
  /** The warning is worth saying once per run, and then it is nagging. */
  private explained = false;

  constructor(
    private readonly viewport: Viewport,
    private readonly graph: dia.Graph,
    container: HTMLElement,
  ) {
    const surrender = (reason: string) => {
      if (!this.wanted || this.latchedOff) return;
      this.latchedOff = true;
      this.viewport.stopGlide();
      const explain = this.explained ? null : reason;
      this.explained = true;
      this.bus.emit('changed', { enabled: false, reason: explain });
    };

    this.disposables.addFn(
      listen(container, 'wheel', (event) => {
        // A wheel event with no delta is not a gesture — some inertial and
        // synthetic sequences end with one, and surrendering to it would turn
        // following off for a scroll that never moved anything.
        const wheel = event as WheelEvent;
        if (wheel.deltaX === 0 && wheel.deltaY === 0) return;
        surrender('Follow run paused — you took the wheel');
      }),
    );
    this.disposables.addFn(
      listen(container, 'pointerdown', () => {
        // Only a gesture that moves the *camera* counts. Clicking a card to
        // read it, or dragging a selection box, is not a request to be left
        // alone. `PanZoomFeature` stamps `data-panning` in a capture-phase
        // handler when it claims the pointer — middle-drag or space-drag — so
        // by the time this bubble-phase listener runs the flag is the answer.
        if (container.dataset['panning'] !== 'true') return;
        surrender('Follow run paused — you moved the canvas');
      }),
    );
  }

  /** Whether the toolbar's toggle is lit: on, and not latched off. */
  get enabled(): boolean {
    return this.wanted && !this.latchedOff;
  }

  setEnabled(enabled: boolean): void {
    this.wanted = enabled;
    // Asking for it again is the explicit undo of the latch.
    this.latchedOff = false;
    this.bus.emit('changed', { enabled: this.enabled, reason: null });
    if (this.enabled) this.follow();
  }

  onChange(handler: (payload: FollowerEvents['changed']) => void): Unsubscribe {
    return this.bus.on('changed', handler);
  }

  /**
   * A run has begun. Clears the latch, so panning during one run does not
   * silently disable following for every run after it.
   */
  runStarted(): void {
    this.active.clear();
    this.latchedOff = false;
    this.explained = false;
    if (this.wanted) this.bus.emit('changed', { enabled: true, reason: null });
  }

  /**
   * Reports which nodes are running right now.
   *
   * Takes the whole set rather than one id because a `Send` fan-out has
   * several at once and the camera's answer for three nodes is not three
   * answers for one node.
   */
  setActive(nodeIds: readonly NodeId[]): void {
    this.active.clear();
    for (const id of nodeIds) {
      const cell = this.graph.getCell(id);
      if (!cell?.isElement()) continue;
      const box = cell.getBBox();
      this.active.set(id, { x: box.x, y: box.y, width: box.width, height: box.height });
    }
    this.follow();
  }

  dispose(): void {
    this.disposables.dispose();
    this.bus.dispose();
  }

  private follow(): void {
    if (!this.enabled || this.active.size === 0) return;
    const decision = decideFollow({
      viewport: this.viewport.visibleRect,
      zoom: this.viewport.zoom,
      targets: [...this.active.values()],
      margin: COMFORT_MARGIN,
      padding: CANVAS.fitPadding,
      minZoom: CANVAS.zoom.min,
      maxZoom: CANVAS.zoom.max,
    });
    if (decision.kind === 'stay') return;
    this.viewport.glideTo(
      decision.center,
      decision.kind === 'fit' ? decision.zoom : this.viewport.zoom,
    );
  }
}

function listen(target: HTMLElement, type: string, handler: (event: Event) => void): Unsubscribe {
  target.addEventListener(type, handler, { passive: true });
  return () => target.removeEventListener(type, handler);
}
