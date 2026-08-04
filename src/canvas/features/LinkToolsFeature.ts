import { dia, linkTools } from '@joint/core';
import { PaperFeature, type PaperFeatureContext } from './IPaperFeature';

/**
 * Contextual tools on a link: a delete button, and draggable vertices.
 *
 * Attached on hover and on selection, removed when neither applies. Tools are
 * heavy views — mounting one per link up front would put hundreds of unused
 * DOM nodes and handlers on a large canvas — so they are created on demand
 * and torn down immediately.
 */
export class LinkToolsFeature extends PaperFeature {
  readonly id = 'link-tools';

  private hovered: string | null = null;

  protected onInstall(ctx: PaperFeatureContext): void {
    const { paper, controller } = ctx;

    this.onPaper('link:mouseenter', ((view: dia.LinkView) => {
      this.hovered = String(view.model.id);
      this.attach(view);
    }) as never);

    this.onPaper('link:mouseleave', ((view: dia.LinkView) => {
      this.hovered = null;
      // Keep the tools if the link is selected — the user is working on it.
      if (controller.selection.hasEdge(String(view.model.id))) return;
      view.removeTools();
    }) as never);

    this.addTeardown(
      controller.selection.on(({ edges }) => {
        for (const link of paper.model.getLinks()) {
          const view = link.findView(paper) as dia.LinkView | undefined;
          if (!view) continue;
          const id = String(link.id);
          if (edges.includes(id) || this.hovered === id) this.attach(view);
          else view.removeTools();
        }
      }),
    );

    // A re-render (or an import) drops tool views; clear the hover memory so
    // the next mouseenter re-attaches rather than being treated as current.
    this.onGraph('reset', (() => {
      this.hovered = null;
    }) as never);
  }

  private attach(view: dia.LinkView): void {
    const { controller } = this.ctx;
    const edgeId = String(view.model.id);

    view.addTools(
      new dia.ToolsView({
        name: 'link-hover',
        tools: [
          new linkTools.Vertices({ snapRadius: 8, redundancyRemoval: true }),
          new linkTools.Remove({
            distance: '50%',
            markup: [
              {
                tagName: 'circle',
                selector: 'button',
                attributes: {
                  r: 9,
                  fill: 'var(--color-bg-surface)',
                  stroke: 'var(--color-border-strong)',
                  'stroke-width': 1,
                  cursor: 'pointer',
                },
              },
              {
                tagName: 'path',
                selector: 'icon',
                attributes: {
                  d: 'M -3 -3 3 3 M -3 3 3 -3',
                  fill: 'none',
                  stroke: 'var(--color-danger)',
                  'stroke-width': 1.6,
                  'stroke-linecap': 'round',
                  'pointer-events': 'none',
                },
              },
            ],
            // Routed through the controller so removing a link is undoable
            // like every other edit, rather than JointJS deleting the cell.
            action: () => controller.disconnect([edgeId]),
          }),
        ],
      }),
    );
  }
}
