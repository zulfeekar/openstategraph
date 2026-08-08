import type { dia } from '@joint/core';
import type { PortRef } from '@core/model/contracts/ports';
import { PaperFeature, type PaperFeatureContext } from './IPaperFeature';

/**
 * Link creation, live validation and the invalid-drop hint.
 *
 * Validation is asked of the controller on every pointer move while a link
 * is being dragged, so the feedback is the *same rule set* that will accept
 * or reject the final drop. Duplicating the rules here — a common shortcut —
 * is how a canvas ends up highlighting a target green and then refusing it.
 *
 * A completed drop is converted into a command rather than kept as the
 * temporary link JointJS drew: the throwaway link is removed and the
 * controller creates a real edge, which the adapter projects back. That keeps
 * the "graph is only ever a projection" invariant intact even for the one
 * gesture that creates cells directly.
 */
export class ConnectionFeature extends PaperFeature {
  readonly id = 'connection';

  /** Reason the current drag would be rejected, for the UI to surface. */
  private rejection: string | null = null;
  private onRejectionChange: ((reason: string | null) => void) | null = null;

  protected onInstall(ctx: PaperFeatureContext): void {
    const { paper, controller, adapter } = ctx;

    this.onPaper('link:connect', ((view: dia.LinkView) => {
      if (adapter.isApplying) return;

      const source = endpointOf(view.model, 'source');
      const target = endpointOf(view.model, 'target');

      // The temporary link is discarded either way; a real edge only exists
      // if the controller accepts the connection.
      view.model.remove({ openstategraphTemp: true });

      if (!source || !target) return;

      const outcome = controller.edges.connect(source, target);
      if (!outcome.ok) this.setRejection(outcome.message ?? 'Invalid connection');
      else this.setRejection(null);
    }) as never);

    // A link dropped on empty canvas simply disappears — `linkPinning: false`
    // already prevents a dangling end, and this clears any stale hint.
    this.onPaper('link:pointerup', (() => this.setRejection(null)) as never);
    this.onPaper('blank:pointerup', (() => this.setRejection(null)) as never);

    /* ---------- hover affordance on ports ---------- */

    this.onPaper('element:magnet:pointerdown', ((
      _view: dia.ElementView,
      _event: dia.Event,
      magnet: SVGElement,
    ) => {
      magnet.closest('.joint-port')?.classList.add('is-dragging');
    }) as never);

    this.onPaper('link:pointerdown', (() => {
      this.ctx.container
        .querySelectorAll('.joint-port.is-dragging')
        .forEach((node) => node.classList.remove('is-dragging'));
    }) as never);

    void paper;
  }

  /** Lets the shell subscribe to validation failures for a toast. */
  observeRejections(handler: (reason: string | null) => void): void {
    this.onRejectionChange = handler;
  }

  private setRejection(reason: string | null): void {
    if (this.rejection === reason) return;
    this.rejection = reason;
    this.onRejectionChange?.(reason);
  }
}

/**
 * Builds the paper's `validateConnection` callback.
 *
 * Lives outside the feature because the paper needs it at construction time,
 * before features install. Reads the port ids straight off the magnets the
 * adapter tagged, so no lookup table has to be kept in step.
 */
export function createConnectionValidator(isValid: (source: PortRef, target: PortRef) => boolean) {
  return function validateConnection(
    sourceView: dia.CellView,
    sourceMagnet: SVGElement,
    targetView: dia.CellView,
    targetMagnet: SVGElement,
  ): boolean {
    const source = refFromMagnet(sourceView, sourceMagnet);
    const target = refFromMagnet(targetView, targetMagnet);
    // No magnet on one end means the pointer is over a card body or blank
    // canvas — not a rejection to explain, just not a connection yet.
    if (!source || !target) return false;
    return isValid(source, target);
  };
}

/** Only output ports may start a link. */
export function validateMagnet(_view: dia.CellView, magnet: SVGElement): boolean {
  return magnet.getAttribute('data-port-direction') === 'out';
}

function refFromMagnet(view: dia.CellView, magnet: SVGElement | null): PortRef | null {
  const portId = magnet?.getAttribute('data-port-id');
  if (!portId) return null;
  return { nodeId: String(view.model.id), portId };
}

function endpointOf(link: dia.Link, end: 'source' | 'target'): PortRef | null {
  const anchor = end === 'source' ? link.source() : link.target();
  if (!anchor?.id || !anchor.port) return null;
  return { nodeId: String(anchor.id), portId: String(anchor.port) };
}
