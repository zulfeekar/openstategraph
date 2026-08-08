import { PaperFeature, type PaperFeatureContext } from './IPaperFeature';

/** Middle mouse button, per the DOM `PointerEvent.button` numbering. */
const MIDDLE_BUTTON = 1;

/**
 * Wheel, trackpad, space-drag and middle-drag navigation.
 *
 * Four gestures are supported because users arrive with different habits and
 * hardware, and a canvas that only honours one of them feels broken to
 * everyone else:
 *
 *  - **Ctrl/⌘ + wheel** and a trackpad pinch → zoom about the pointer
 *  - **Plain wheel / two-finger scroll** → pan
 *  - **Space + drag** → pan from anywhere, including over a node
 *  - **Middle-drag** → pan without a modifier
 *
 * Dragging blank canvas is deliberately *not* pan: it is the rubber-band
 * selection gesture (see `SelectionFeature`), which is the more frequent
 * action and the one users expect from every other editor.
 */
export class PanZoomFeature extends PaperFeature {
  readonly id = 'pan-zoom';

  private spaceHeld = false;
  private panning = false;
  private lastPointer = { x: 0, y: 0 };

  protected onInstall(ctx: PaperFeatureContext): void {
    const { container, viewport } = ctx;

    this.onDom(
      container,
      'wheel',
      ((event: WheelEvent) => {
        // Always prevent default: the browser would otherwise scroll the page
        // or trigger its own zoom on a pinch.
        event.preventDefault();

        if (event.ctrlKey || event.metaKey) {
          // Trackpad pinch arrives as ctrl+wheel with small deltas; the
          // divisor keeps a pinch from jumping several zoom steps at once.
          viewport.zoomBy(-event.deltaY / 240, { x: event.clientX, y: event.clientY });
          return;
        }

        // Shift converts a vertical wheel into horizontal panning, which is
        // the only way to pan sideways with a plain mouse.
        const [dx, dy] = event.shiftKey
          ? [-event.deltaY, -event.deltaX]
          : [-event.deltaX, -event.deltaY];
        viewport.panBy(dx, dy);
      }) as never,
      { passive: false },
    );

    this.onDom(window, 'keydown', ((event: KeyboardEvent) => {
      if (event.code !== 'Space' || this.spaceHeld) return;
      // Space is a legitimate character in a prompt field, so only claim it
      // when focus is not in a text control.
      if (isTextEntry(event.target)) return;
      event.preventDefault();
      this.spaceHeld = true;
      container.dataset['panReady'] = 'true';
    }) as never);

    this.onDom(window, 'keyup', ((event: KeyboardEvent) => {
      if (event.code !== 'Space') return;
      this.spaceHeld = false;
      delete container.dataset['panReady'];
    }) as never);

    // Losing focus while space is held would otherwise strand the canvas in
    // pan mode with no key-up ever arriving.
    this.onDom(window, 'blur', (() => {
      this.spaceHeld = false;
      this.panning = false;
      delete container.dataset['panReady'];
      delete container.dataset['panning'];
    }) as never);

    this.onDom(
      container,
      'pointerdown',
      ((event: PointerEvent) => {
        const wantsPan = event.button === MIDDLE_BUTTON || (this.spaceHeld && event.button === 0);
        if (!wantsPan) return;
        event.preventDefault();
        event.stopPropagation();
        this.panning = true;
        this.lastPointer = { x: event.clientX, y: event.clientY };
        container.dataset['panning'] = 'true';
        container.setPointerCapture(event.pointerId);
      }) as never,
      { capture: true },
    );

    this.onDom(container, 'pointermove', ((event: PointerEvent) => {
      if (!this.panning) return;
      viewport.panBy(event.clientX - this.lastPointer.x, event.clientY - this.lastPointer.y);
      this.lastPointer = { x: event.clientX, y: event.clientY };
    }) as never);

    const endPan = (event: PointerEvent) => {
      if (!this.panning) return;
      this.panning = false;
      delete container.dataset['panning'];
      if (container.hasPointerCapture(event.pointerId)) {
        container.releasePointerCapture(event.pointerId);
      }
    };

    this.onDom(container, 'pointerup', endPan as never);
    this.onDom(container, 'pointercancel', endPan as never);
  }

  /** True while a pan gesture owns the pointer — selection must stand down. */
  get isPanning(): boolean {
    return this.panning || this.spaceHeld;
  }
}

export function isTextEntry(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable;
}
