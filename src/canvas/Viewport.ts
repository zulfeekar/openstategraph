import type { dia } from '@joint/core';
import { EventBus } from '@core/kernel/EventBus';
import type { Unsubscribe } from '@core/kernel/Disposable';
import { CANVAS } from '@design/tokens';
import { clamp, inflate, type Point, type Rect } from '@core/kernel/geometry';

interface ViewportEvents extends Record<string, unknown> {
  changed: { zoom: number; translate: Point };
}

/**
 * Pan and zoom.
 *
 * This is the open-source replacement for the commercial paper-scroller. It
 * takes the Figma-style approach — a fixed viewport with a transformed
 * canvas — rather than emulating scrollbars around an oversized element.
 * That means an infinite canvas with no scroll-extent bookkeeping, and
 * zoom-about-a-point becomes simple arithmetic instead of a scroll
 * adjustment chased across two coordinate systems.
 *
 * All mutation funnels through `apply`, so every consumer (minimap, zoom
 * readout, tooltips anchored to nodes) hears about a change exactly once.
 */
export class Viewport {
  private readonly bus = new EventBus<ViewportEvents>();
  // Annotated: the token object is `as const`, so inference would pin these
  // to the literal default and reject every later value.
  private currentZoom: number = CANVAS.zoom.default;
  private currentTranslate: Point = { x: 0, y: 0 };
  private glideFrame: number | null = null;

  constructor(
    private readonly paper: dia.Paper,
    private readonly container: HTMLElement,
  ) {}

  get zoom(): number {
    return this.currentZoom;
  }

  get translate(): Point {
    return { ...this.currentTranslate };
  }

  /** Viewport size in CSS pixels. */
  get size(): { width: number; height: number } {
    const rect = this.container.getBoundingClientRect();
    return { width: rect.width, height: rect.height };
  }

  /** The model-space rectangle currently visible. */
  get visibleRect(): Rect {
    const { width, height } = this.size;
    return {
      x: -this.currentTranslate.x / this.currentZoom,
      y: -this.currentTranslate.y / this.currentZoom,
      width: width / this.currentZoom,
      height: height / this.currentZoom,
    };
  }

  /** Converts a client (viewport-relative) point to model coordinates. */
  clientToLocal(clientX: number, clientY: number): Point {
    const rect = this.container.getBoundingClientRect();
    return {
      x: (clientX - rect.left - this.currentTranslate.x) / this.currentZoom,
      y: (clientY - rect.top - this.currentTranslate.y) / this.currentZoom,
    };
  }

  localToClient(point: Point): Point {
    const rect = this.container.getBoundingClientRect();
    return {
      x: point.x * this.currentZoom + this.currentTranslate.x + rect.left,
      y: point.y * this.currentZoom + this.currentTranslate.y + rect.top,
    };
  }

  panBy(dx: number, dy: number): void {
    this.apply(this.currentZoom, {
      x: this.currentTranslate.x + dx,
      y: this.currentTranslate.y + dy,
    });
  }

  /**
   * Sets zoom, keeping the given client point pinned.
   *
   * Anchoring matters: zooming toward the pointer is what makes wheel-zoom
   * feel like a camera rather than a slider, and it is the difference
   * between navigating a large graph comfortably and constantly re-panning.
   */
  setZoom(next: number, anchorClient?: Point): void {
    const target = clamp(next, CANVAS.zoom.min, CANVAS.zoom.max);
    if (Math.abs(target - this.currentZoom) < 1e-4) return;

    const rect = this.container.getBoundingClientRect();
    const anchor = anchorClient ?? {
      x: rect.left + rect.width / 2,
      y: rect.top + rect.height / 2,
    };

    // Local point under the anchor must be unchanged after the zoom.
    const localX = (anchor.x - rect.left - this.currentTranslate.x) / this.currentZoom;
    const localY = (anchor.y - rect.top - this.currentTranslate.y) / this.currentZoom;

    this.apply(target, {
      x: anchor.x - rect.left - localX * target,
      y: anchor.y - rect.top - localY * target,
    });
  }

  zoomBy(delta: number, anchorClient?: Point): void {
    // Multiplicative so each step feels the same at every scale; additive
    // steps crawl when zoomed out and lurch when zoomed in.
    this.setZoom(this.currentZoom * (1 + delta), anchorClient);
  }

  zoomIn(anchorClient?: Point): void {
    this.zoomBy(CANVAS.zoom.step, anchorClient);
  }

  zoomOut(anchorClient?: Point): void {
    this.zoomBy(-CANVAS.zoom.step, anchorClient);
  }

  resetZoom(): void {
    this.setZoom(CANVAS.zoom.default);
  }

  /** Centres a model rectangle without changing zoom. */
  centerOn(rect: Rect): void {
    const { width, height } = this.size;
    this.apply(this.currentZoom, {
      x: width / 2 - (rect.x + rect.width / 2) * this.currentZoom,
      y: height / 2 - (rect.y + rect.height / 2) * this.currentZoom,
    });
  }

  /**
   * Frames a rectangle, or the whole graph when none is given.
   *
   * Zoom is capped at 1 so fitting a single small node does not blow it up
   * to fill the screen — "fit" should never look like a mistake.
   */
  fit(rect: Rect | null, padding = CANVAS.fitPadding): void {
    if (!rect || rect.width <= 0 || rect.height <= 0) {
      this.apply(CANVAS.zoom.default, { x: 0, y: 0 });
      return;
    }
    const { width, height } = this.size;
    if (width === 0 || height === 0) return;

    const padded = inflate(rect, padding);
    const scale = clamp(Math.min(width / padded.width, height / padded.height), CANVAS.zoom.min, 1);

    this.apply(scale, {
      x: width / 2 - (padded.x + padded.width / 2) * scale,
      y: height / 2 - (padded.y + padded.height / 2) * scale,
    });
  }

  /**
   * Animated move: frame `rect` at `zoom`, easing rather than cutting.
   *
   * A cut leaves the reader to work out what moved; an ease preserves the
   * sense that this is the same canvas seen from somewhere else, which is the
   * whole reason to follow a run rather than just re-render it. Under
   * `prefers-reduced-motion` it becomes exactly that cut — the destination is
   * the point, the travel is the decoration.
   *
   * Interpolating zoom and translate together (rather than easing zoom and
   * then panning) keeps the framed rectangle on a straight path across the
   * screen; two sequential eases make it swoop.
   *
   * The duration is short on purpose, and not only for feel: every frame
   * emits `changed`, and each card re-measures itself on a zoom change. A
   * long glide is therefore a long re-measure, so the ease is bought in
   * frames, not seconds.
   */
  glideTo(rect: Rect, zoom: number, durationMs = 340): void {
    this.stopGlide();

    const target = this.translationFor(rect, zoom);
    const fromZoom = this.currentZoom;
    const fromTranslate = this.currentTranslate;

    if (durationMs <= 0 || prefersReducedMotion() || typeof requestAnimationFrame !== 'function') {
      this.apply(zoom, target);
      return;
    }

    const started = performance.now();
    const step = (now: number) => {
      const t = Math.min(1, (now - started) / durationMs);
      const eased = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
      this.apply(fromZoom + (zoom - fromZoom) * eased, {
        x: fromTranslate.x + (target.x - fromTranslate.x) * eased,
        y: fromTranslate.y + (target.y - fromTranslate.y) * eased,
      });
      this.glideFrame = t < 1 ? requestAnimationFrame(step) : null;
    };
    this.glideFrame = requestAnimationFrame(step);
  }

  /** Abandons an in-flight `glideTo`, leaving the camera wherever it got to. */
  stopGlide(): void {
    if (this.glideFrame == null) return;
    cancelAnimationFrame(this.glideFrame);
    this.glideFrame = null;
  }

  onChange(handler: (payload: ViewportEvents['changed']) => void): Unsubscribe {
    return this.bus.on('changed', handler);
  }

  /** The translate that puts `rect` in the middle of the viewport at `zoom`. */
  private translationFor(rect: Rect, zoom: number): Point {
    const { width, height } = this.size;
    return {
      x: width / 2 - (rect.x + rect.width / 2) * zoom,
      y: height / 2 - (rect.y + rect.height / 2) * zoom,
    };
  }

  /** Pushes the current transform onto the paper and notifies listeners. */
  private apply(zoom: number, translate: Point): void {
    const zoomChanged = Math.abs(zoom - this.currentZoom) > 1e-4;
    const movedX = Math.abs(translate.x - this.currentTranslate.x) > 0.01;
    const movedY = Math.abs(translate.y - this.currentTranslate.y) > 0.01;
    if (!zoomChanged && !movedX && !movedY) return;

    this.currentZoom = zoom;
    this.currentTranslate = translate;

    this.paper.scale(zoom, zoom);
    this.paper.translate(translate.x, translate.y);

    this.bus.emit('changed', { zoom, translate: { ...translate } });
  }

  dispose(): void {
    this.stopGlide();
    this.bus.dispose();
  }
}

function prefersReducedMotion(): boolean {
  return (
    typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches
  );
}
