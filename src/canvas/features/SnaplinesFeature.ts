import type { dia } from '@joint/core';
import type { Rect } from '@core/kernel/geometry';
import { PaperFeature, type PaperFeatureContext } from './IPaperFeature';

/** Alignment tolerance in model units. */
const SNAP_DISTANCE = 6;

interface Guide {
  readonly axis: 'x' | 'y';
  /** Model-space coordinate of the guide line. */
  readonly at: number;
  /** Extent along the other axis, so the line spans only what it aligns. */
  readonly from: number;
  readonly to: number;
}

/**
 * Alignment guides while dragging, and snapping onto them.
 *
 * Replaces the commercial snaplines plugin. Compares the dragged node's
 * three edges per axis (near, centre, far) against every other node's, which
 * is what allows "left edges line up", "centres line up" and "this node's
 * right meets that node's left" to all be felt as the same gesture.
 *
 * Snapping adjusts the element directly rather than through a command: the
 * drag is still in flight, and `DragCommitFeature` reads the final position
 * when the pointer comes up. One gesture, one undo entry.
 */
export class SnaplinesFeature extends PaperFeature {
  readonly id = 'snaplines';

  private layer: HTMLElement | null = null;
  private dragging: dia.Element | null = null;

  protected onInstall(ctx: PaperFeatureContext): void {
    const { paper } = ctx;

    this.onPaper('element:pointerdown', ((view: dia.ElementView) => {
      this.dragging = view.model;
    }) as never);

    this.onGraph('change:position', ((element: dia.Element, _position: unknown, opt: { ui?: boolean; dyflowFollow?: boolean }) => {
      // Only the element under the pointer drives guides; followers and
      // programmatic moves must not.
      if (!opt?.ui || opt.dyflowFollow) return;
      if (this.dragging?.id !== element.id) return;
      this.update(element);
    }) as never);

    const clear = () => {
      this.dragging = null;
      this.clearGuides();
    };

    this.onPaper('element:pointerup', clear as never);
    this.onPaper('blank:pointerup', clear as never);

    void paper;
  }

  private update(element: dia.Element): void {
    const moving = rectOf(element);
    const others = this.ctx.graph
      .getElements()
      .filter((candidate) => candidate.id !== element.id)
      // A container the node is being dragged inside would align against its
      // own frame on every axis, which is noise rather than guidance.
      .filter((candidate) => candidate.id !== element.getParentCell()?.id)
      .map(rectOf);

    const guides: Guide[] = [];
    let snapDx = 0;
    let snapDy = 0;

    // Vertical guides (aligning x).
    const movingX = [moving.x, moving.x + moving.width / 2, moving.x + moving.width];
    for (const other of others) {
      const otherX = [other.x, other.x + other.width / 2, other.x + other.width];
      for (const mx of movingX) {
        for (const ox of otherX) {
          if (Math.abs(mx - ox) > SNAP_DISTANCE) continue;
          if (snapDx === 0) snapDx = ox - mx;
          guides.push({
            axis: 'x',
            at: ox,
            from: Math.min(moving.y, other.y),
            to: Math.max(moving.y + moving.height, other.y + other.height),
          });
        }
      }
    }

    // Horizontal guides (aligning y).
    const movingY = [moving.y, moving.y + moving.height / 2, moving.y + moving.height];
    for (const other of others) {
      const otherY = [other.y, other.y + other.height / 2, other.y + other.height];
      for (const my of movingY) {
        for (const oy of otherY) {
          if (Math.abs(my - oy) > SNAP_DISTANCE) continue;
          if (snapDy === 0) snapDy = oy - my;
          guides.push({
            axis: 'y',
            at: oy,
            from: Math.min(moving.x, other.x),
            to: Math.max(moving.x + moving.width, other.x + other.width),
          });
        }
      }
    }

    if (snapDx !== 0 || snapDy !== 0) {
      // `ui: false` keeps this out of the follower logic in DragCommit —
      // it is a correction to the leader, not a new gesture.
      element.translate(snapDx, snapDy, { dyflowSnap: true });
    }

    this.renderGuides(guides);
  }

  private renderGuides(guides: readonly Guide[]): void {
    if (guides.length === 0) {
      this.clearGuides();
      return;
    }

    const layer = this.ensureLayer();
    const { zoom, translate } = this.ctx.viewport;
    layer.replaceChildren();

    // Deduplicate: three edges times three edges produces the same line
    // repeatedly, and stacking them makes a 1px guide look like a 3px one.
    const seen = new Set<string>();

    for (const guide of guides) {
      const key = `${guide.axis}:${Math.round(guide.at)}`;
      if (seen.has(key)) continue;
      seen.add(key);

      const line = document.createElement('div');
      line.className = `snapline snapline--${guide.axis}`;
      if (guide.axis === 'x') {
        line.style.transform = `translate3d(${guide.at * zoom + translate.x}px, ${
          guide.from * zoom + translate.y
        }px, 0)`;
        line.style.height = `${(guide.to - guide.from) * zoom}px`;
      } else {
        line.style.transform = `translate3d(${guide.from * zoom + translate.x}px, ${
          guide.at * zoom + translate.y
        }px, 0)`;
        line.style.width = `${(guide.to - guide.from) * zoom}px`;
      }
      layer.appendChild(line);
    }
  }

  private ensureLayer(): HTMLElement {
    if (!this.layer) {
      const layer = document.createElement('div');
      layer.className = 'snapline-layer';
      this.ctx.container.appendChild(layer);
      this.layer = layer;
    }
    return this.layer;
  }

  private clearGuides(): void {
    this.layer?.remove();
    this.layer = null;
  }

  override dispose(): void {
    this.clearGuides();
    super.dispose();
  }
}

function rectOf(element: dia.Element): Rect {
  const position = element.position();
  const size = element.size();
  return { x: position.x, y: position.y, width: size.width, height: size.height };
}
