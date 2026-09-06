import { describe, expect, it } from 'vitest';
import { addNode, connect, makeWorkbench, TYPE } from '@core/testing/fixtures';
import { describeEdge } from './edgeDescription';

/**
 * Ticket 24 — a link could be drawn and never removed.
 *
 * The gesture worked all along: clicking a link *did* select it in the model.
 * Nothing said so. The inspector had two modes, node and document, and a
 * selected link fell through to "Nothing selected · Click a node to edit it",
 * so the one channel that could have reported the selection denied it — while
 * the shortcuts drawer advertised "Delete selection ⌫" for a selection the
 * user had no way to believe in.
 *
 * This is the content of the missing third mode.
 */
describe('describeEdge', () => {
  const seed = () => {
    const workbench = makeWorkbench();
    const input = addNode(workbench, TYPE.textInput, { at: { x: 0, y: 0 } });
    const agent = addNode(workbench, TYPE.agent, { at: { x: 400, y: 0 } });
    connect(workbench, input, 'text', agent, 'prompt');
    const edge = workbench.model.edgesOf(agent.id)[0]!;
    return { workbench, input, agent, edge };
  };

  it('names both ends, by node title and port label', () => {
    const { workbench, edge } = seed();

    const described = describeEdge(workbench.model, edge.id);

    expect(described).toMatchObject({
      sourcePort: 'text',
      targetPort: 'prompt',
    });
    expect(described?.sourceNode).toBeTruthy();
    expect(described?.targetNode).toBeTruthy();
  });

  it('follows a rename rather than reporting the title the link was drawn with', () => {
    const { workbench, input, edge } = seed();
    workbench.controller.nodes.setTitle(input.id, 'Customer question');

    expect(describeEdge(workbench.model, edge.id)?.sourceNode).toBe('Customer question');
  });

  it('reports the source port type — what the link colour encodes', () => {
    const { workbench, edge } = seed();

    expect(describeEdge(workbench.model, edge.id)?.type).toBe('text');
  });

  it('is null for a link that has been removed, so the panel can fall back', () => {
    const { workbench, edge } = seed();
    workbench.controller.edges.disconnect([edge.id]);

    expect(describeEdge(workbench.model, edge.id)).toBeNull();
  });
});
