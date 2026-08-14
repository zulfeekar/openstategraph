import type { dia } from '@joint/core';
import { intersects, type Rect } from '@core/kernel/geometry';
import { PaperFeature, type PaperFeatureContext } from './IPaperFeature';
import type { PanZoomFeature } from './PanZoomFeature';

/** Movement below this many pixels is treated as a click, not a drag. */
const DRAG_THRESHOLD = 4;

/**
 * Click, shift-click and rubber-band selection, plus the visual feedback.
 *
 * Replaces the commercial selection plugin. Selection state itself lives in
 * the controller, not here — this feature only translates gestures into
 * selection intents and reflects the result onto the DOM. Keeping the state
 * outside means the inspector, the keyboard handler and the toolbar all read
 * one source of truth instead of querying the canvas.
 */
export class SelectionFeature extends PaperFeature {
  readonly id = 'selection';

  private band: HTMLElement | null = null;
  private bandOrigin: { x: number; y: number } | null = null;
  private bandActive = false;

  constructor(private readonly panZoom: PanZoomFeature) {
    super();
  }

  protected onInstall(ctx: PaperFeatureContext): void {
    const { paper, controller, container, viewport } = ctx;

    /* ---------- click selection ---------- */

    // A press on a **field** selects its node, without starting a drag.
    //
    // Every on-card control is wrapped in `data-no-drag`, and the paper guard
    // makes JointJS ignore the whole event so a drag cannot begin inside a
    // textarea. That is right and stays. The side effect was not chosen:
    // because the paper never saw the event, `element:pointerdown` below never
    // fired either, so selection was swallowed along with the drag. On the
    // seeded demo the first card is 67x52 and its textarea fills almost all of
    // it, so "click the node" meant "click the field" far more often than not,
    // and the inspector stayed on the workflow (canvas-feels-right ticket 05).
    //
    // Listened for on the container, since the paper has already declined it.
    // Selection only — the drag guard is a separate question about the same
    // gesture, and this answers neither for the other.
    container.addEventListener('pointerdown', (event: PointerEvent) => {
      const target = event.target as HTMLElement | null;
      if (!target?.closest('[data-no-drag]')) return;
      const card = target.closest('[data-node-id]');
      const nodeId = card?.getAttribute('data-node-id');
      if (!nodeId) return;
      if (controller.selection.hasNode(nodeId)) return;
      controller.selectionActions.selectNodes([nodeId]);
    });

    this.onPaper('element:pointerdown', ((view: dia.ElementView, event: dia.Event) => {
      const nodeId = String(view.model.id);
      const additive = event.shiftKey || event.metaKey || event.ctrlKey;
      if (additive) {
        controller.selectionActions.selectNodes([nodeId], 'toggle');
      } else if (!controller.selection.hasNode(nodeId)) {
        // Clicking an already-selected node keeps the whole selection, so a
        // multi-node drag isn't collapsed the moment it starts.
        controller.selectionActions.selectNodes([nodeId]);
      }
    }) as never);

    this.onPaper('link:pointerdown', ((view: dia.LinkView, event: dia.Event) => {
      const edgeId = String(view.model.id);
      // Only a link the **model** has. While a connection is being drawn,
      // JointJS owns a temporary link cell with an id of its own making, and
      // pressing through it selected that id — so a refused drag left the
      // inspector reporting "Link removed. That link is no longer in the
      // workflow." about a link that was never in it. Selecting something the
      // document does not contain can only ever produce that message.
      if (!controller.model.edges().some((edge) => edge.id === edgeId)) return;
      const additive = event.shiftKey || event.metaKey || event.ctrlKey;
      controller.selection.selectEdges([edgeId], additive ? 'toggle' : 'replace');
    }) as never);

    this.onPaper('blank:pointerdown', ((event: dia.Event, x: number, y: number) => {
      if (this.panZoom.isPanning) return;
      if (!event.shiftKey) controller.selection.clear();
      this.bandOrigin = { x, y };
      this.bandActive = false;
      this.bandStartClient = {
        x: (event.originalEvent as PointerEvent | undefined)?.clientX ?? 0,
        y: (event.originalEvent as PointerEvent | undefined)?.clientY ?? 0,
      };
    }) as never);

    /* ---------- rubber band ---------- */

    this.onDom(container, 'pointermove', ((event: PointerEvent) => {
      if (!this.bandOrigin || this.panZoom.isPanning) return;

      if (!this.bandActive) {
        const dx = Math.abs(event.clientX - this.bandStartClient.x);
        const dy = Math.abs(event.clientY - this.bandStartClient.y);
        // Wait for real movement so a plain click on blank canvas doesn't
        // flash a zero-size band.
        if (dx < DRAG_THRESHOLD && dy < DRAG_THRESHOLD) return;
        this.bandActive = true;
        this.showBand();
      }

      const current = viewport.clientToLocal(event.clientX, event.clientY);
      const rect = normalise(this.bandOrigin, current);
      this.positionBand(rect);
    }) as never);

    const finishBand = () => {
      if (this.bandActive && this.bandOrigin) {
        const rect = this.lastBandRect;
        if (rect) {
          const hits = paper.model
            .getElements()
            .filter((element) => intersects(rect, toRect(element)))
            // A container fully wrapping the band shouldn't be swept up —
            // the user is selecting inside it, not selecting it.
            .filter((element) => !enclosesFully(toRect(element), rect))
            .map((element) => String(element.id));
          controller.selectionActions.selectNodes(hits, this.bandAdditive ? 'add' : 'replace');
        }
      }
      this.hideBand();
      this.bandOrigin = null;
      this.bandActive = false;
    };

    this.onDom(container, 'pointerup', finishBand as never);
    this.onDom(container, 'pointercancel', finishBand as never);
    this.onDom(container, 'pointerleave', finishBand as never);

    /* ---------- reflect selection onto the DOM ---------- */

    this.addTeardown(
      controller.selection.on(({ nodes, edges }) => {
        for (const element of paper.model.getElements()) {
          const view = element.findView(paper);
          view?.el.classList.toggle('is-selected', nodes.includes(String(element.id)));
        }
        for (const link of paper.model.getLinks()) {
          const view = link.findView(paper);
          view?.el.classList.toggle('is-selected', edges.includes(String(link.id)));
        }
      }),
    );
  }

  private bandStartClient = { x: 0, y: 0 };
  private bandAdditive = false;
  private lastBandRect: Rect | null = null;

  private showBand(): void {
    if (this.band) return;
    const band = document.createElement('div');
    band.className = 'selection-band';
    this.ctx.container.appendChild(band);
    this.band = band;
  }

  private positionBand(rect: Rect): void {
    this.lastBandRect = rect;
    if (!this.band) return;
    const { zoom, translate } = this.ctx.viewport;
    // Painted in viewport pixels rather than inside the transformed canvas
    // so its border stays 1px at every zoom level.
    this.band.style.transform = `translate3d(${rect.x * zoom + translate.x}px, ${
      rect.y * zoom + translate.y
    }px, 0)`;
    this.band.style.width = `${rect.width * zoom}px`;
    this.band.style.height = `${rect.height * zoom}px`;
  }

  private hideBand(): void {
    this.band?.remove();
    this.band = null;
    this.lastBandRect = null;
  }

  override dispose(): void {
    this.hideBand();
    super.dispose();
  }
}

function normalise(a: { x: number; y: number }, b: { x: number; y: number }): Rect {
  return {
    x: Math.min(a.x, b.x),
    y: Math.min(a.y, b.y),
    width: Math.abs(a.x - b.x),
    height: Math.abs(a.y - b.y),
  };
}

function toRect(element: dia.Element): Rect {
  const position = element.position();
  const size = element.size();
  return { x: position.x, y: position.y, width: size.width, height: size.height };
}

function enclosesFully(outer: Rect, inner: Rect): boolean {
  return (
    outer.x <= inner.x &&
    outer.y <= inner.y &&
    outer.x + outer.width >= inner.x + inner.width &&
    outer.y + outer.height >= inner.y + inner.height
  );
}
