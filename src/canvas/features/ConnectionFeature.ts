import type { dia } from '@joint/core';
import { announcementFor } from '@controller/explainConnection';
import type { PortRef } from '@core/model/contracts/ports';
import { PaperFeature, type PaperFeatureContext } from './IPaperFeature';
import {
  availableTargets,
  DomPortMarker,
  PORT_AFFORDANCE,
  type IPortMarker,
} from './portAffordance';

/**
 * Link creation, live validation, the connection affordance and the
 * invalid-drop hint.
 *
 * Validation is asked of the controller on every pointer move while a link
 * is being dragged, so the feedback is the *same rule set* that will accept
 * or reject the final drop. Duplicating the rules here — a common shortcut —
 * is how a canvas ends up highlighting a target green and then refusing it.
 * The affordance below asks that same `canConnect`, for the same reason.
 *
 * A completed drop is converted into a command rather than kept as the
 * temporary link JointJS drew: the throwaway link is removed and the
 * controller creates a real edge, which the adapter projects back. That keeps
 * the "graph is only ever a projection" invariant intact even for the one
 * gesture that creates cells directly.
 *
 * **The temporary link is also the affordance's clock.** A link appearing in
 * the graph that the adapter did not put there *is* a drag in flight, and its
 * removal — whether it landed, was refused, or was dropped on blank canvas —
 * *is* the end of one. JointJS publishes no event for either moment and marks
 * no class on the link, so the graph's own `add`/`remove` is the only honest
 * signal; see `portAffordance.ts` for what was measured.
 */
export class ConnectionFeature extends PaperFeature {
  readonly id = 'connection';

  /** Reason the current drag would be rejected, for the UI to surface. */
  private rejection: string | null = null;
  private onRejectionChange: ((reason: string | null) => void) | null = null;

  private marker: IPortMarker | null = null;
  private connecting = false;
  /**
   * The reason the last port under the pointer refused, and whether this
   * gesture ever made a link.
   *
   * Recorded rather than announced, because `validateConnection` runs on
   * every pointer move across every magnet — announcing there would fire a
   * message per port crossed. `announcementFor` decides what to do with it
   * once the pointer is released.
   */
  private lastRefusal: string | null = null;
  private connectedThisGesture = false;

  /**
   * @param createMarker how the affordance reaches the canvas. Injected so the
   *   feature's decisions can be exercised without a DOM.
   */
  constructor(
    private readonly createMarker: (paperEl: HTMLElement) => IPortMarker = (paperEl) =>
      new DomPortMarker(paperEl),
  ) {
    super();
  }

  protected onInstall(ctx: PaperFeatureContext): void {
    const { paper, controller, adapter } = ctx;
    this.marker = this.createMarker(paper.el as HTMLElement);

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
      else {
        this.connectedThisGesture = true;
        this.setRejection(null);
      }
    }) as never);

    // The end of the gesture is where a refusal is finally said out loud.
    //
    // It cannot be said earlier: `validateConnection` is consulted on every
    // pointer move over every magnet, so a drag across a card would fire one
    // message per port. It must not be said for a *successful* link either —
    // the edge appearing on the canvas is that feedback — nor for a drag
    // released over blank canvas, where no rule refused anything.
    // `announcementFor` holds those three cases.
    const finish = () => {
      const say = announcementFor({
        connected: this.connectedThisGesture,
        lastRefusal: this.lastRefusal,
      });
      this.setRejection(say);
      this.lastRefusal = null;
      this.connectedThisGesture = false;
    };
    this.onPaper('link:pointerup', finish as never);
    this.onPaper('blank:pointerup', finish as never);

    /* ---------- the connection affordance ---------- */

    // Pressing a port is not yet a drag (`magnetThreshold: 'onleave'`), but it
    // is already a statement of intent, so the origin grows straight away.
    this.onPaper('element:magnet:pointerdown', ((
      _view: dia.ElementView,
      _event: dia.Event,
      magnet: SVGElement,
    ) => {
      magnet.closest('.joint-port')?.classList.add(PORT_AFFORDANCE.origin);
      // A gesture is under way from here, so the pointer-up below always has
      // something to undo — a press that never becomes a drag included.
      this.connecting = true;
    }) as never);

    this.onGraph('add', ((cell: dia.Cell) => {
      if (adapter.isApplying || !cell.isLink()) return;
      const origin = endpointOf(cell as dia.Link, 'source');
      if (origin) this.beginConnecting(origin);
    }) as never);

    this.onGraph('remove', ((cell: dia.Cell) => {
      if (cell.isLink()) this.endConnecting();
    }) as never);

    // Belt and braces: a pointer released anywhere ends the gesture, so a
    // dropped event can never leave the canvas frozen mid-invitation.
    this.onPaper('link:pointerup', (() => this.endConnecting()) as never);
    this.onPaper('blank:pointerup', (() => this.endConnecting()) as never);
    this.onDom(document, 'pointerup', () => this.endConnecting());

    this.addTeardown(() => this.endConnecting());
  }

  /** Lets the shell subscribe to validation failures for a toast. */
  observeRejections(handler: (reason: string | null) => void): void {
    this.onRejectionChange = handler;
  }

  private beginConnecting(origin: PortRef): void {
    const marker = this.marker;
    if (!marker) return;
    this.connecting = true;
    marker.apply(
      origin,
      availableTargets(origin, marker.listPorts(), (source, target) =>
        this.ctx.controller.edges.canConnect(source, target),
      ),
    );
  }

  private endConnecting(): void {
    if (!this.connecting) return;
    this.connecting = false;
    this.marker?.clear();
  }

  /**
   * Records why the port currently under the pointer would refuse.
   *
   * Written by `createConnectionValidator` on every pointer move. Kept, not
   * announced — see `finish` above.
   */
  noteRefusal(reason: string | null): void {
    this.lastRefusal = reason;
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
export function createConnectionValidator(
  explain: (source: PortRef, target: PortRef) => { ok: boolean; reason?: string },
  noteRefusal: (reason: string | null) => void = () => {},
) {
  return function validateConnection(
    sourceView: dia.CellView,
    sourceMagnet: SVGElement,
    targetView: dia.CellView,
    targetMagnet: SVGElement,
  ): boolean {
    const source = refFromMagnet(sourceView, sourceMagnet);
    const target = refFromMagnet(targetView, targetMagnet);
    // No magnet on one end means the pointer is over a card body or blank
    // canvas — not a rejection to explain, just not a connection yet. The
    // recorded reason is cleared so releasing here says nothing.
    if (!source || !target) {
      noteRefusal(null);
      return false;
    }
    // The **verdict**, not `verdict.ok`. Returning a bare boolean is what
    // made every refusal silent: JointJS refuses on `false`, so `link:connect`
    // never fires and the reason the rule computed is thrown away here.
    const verdict = explain(source, target);
    noteRefusal(verdict.ok ? null : (verdict.reason ?? 'That connection is not allowed'));
    return verdict.ok;
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
