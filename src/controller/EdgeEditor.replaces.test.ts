import { describe, expect, it } from 'vitest';
import { TYPE, addNode, makeWorkbench } from '@core/testing/fixtures';

/**
 * `workflow-gallery/77`: dropping a link on an occupied single-slot input
 * replaces the incumbent — `capacityRule`'s answer to "these cannot merge"
 * (see `ConnectionValidator.capacityRule`) — and until now the canvas said
 * nothing about it. The old link just disappeared.
 *
 * `EdgeEditor.connect` is the one place that already knows which edges
 * `verdict.replaces` names *before* it removes them (it builds the
 * `CompositeCommand` from that exact list), so this is where the outgoing
 * `ActionOutcome` should start naming the displaced source — the cheapest of
 * the ticket's sketches ("say it after the fact"), reusing the toast channel
 * `ConnectionFeature`/`CanvasStage` already wire for rejections.
 *
 * A test that only checked "a message exists" would stay green if the
 * message pointed at the wrong link, or named an edge id instead of a node a
 * user recognises — so this asserts the exact sentence and that an ordinary,
 * non-displacing connect still says nothing (matching `announcementFor`'s
 * "a made link speaks for itself").
 */
describe('EdgeEditor.connect names what a replacement displaced', () => {
  it('says which source the new link displaced', () => {
    const workbench = makeWorkbench();
    const first = addNode(workbench, TYPE.textInput);
    workbench.controller.nodes.setTitle(first.id, 'Billing desk');
    const agent = addNode(workbench, TYPE.agent);
    const second = addNode(workbench, TYPE.textInput);

    const firstOutcome = workbench.controller.edges.connect(
      { nodeId: first.id, portId: 'text' },
      { nodeId: agent.id, portId: 'prompt' },
    );
    expect(firstOutcome).toEqual({ ok: true, message: undefined });

    const secondOutcome = workbench.controller.edges.connect(
      { nodeId: second.id, portId: 'text' },
      { nodeId: agent.id, portId: 'prompt' },
    );

    expect(secondOutcome.ok).toBe(true);
    expect(secondOutcome.message).toBe('Replaced the link from Billing desk');
  });

  it('says nothing for an ordinary connect that displaces no one', () => {
    const workbench = makeWorkbench();
    const source = addNode(workbench, TYPE.textInput);
    const agent = addNode(workbench, TYPE.agent);

    const outcome = workbench.controller.edges.connect(
      { nodeId: source.id, portId: 'text' },
      { nodeId: agent.id, portId: 'prompt' },
    );

    expect(outcome).toEqual({ ok: true, message: undefined });
  });
});
