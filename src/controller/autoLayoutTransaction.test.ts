import { beforeEach, describe, expect, it } from 'vitest';
import { addNode, connect, makeWorkbench } from '@core/testing/fixtures';
import type { Workbench } from '@app/Workbench';

/**
 * One Cmd-Z reverses an arrangement *and* the frames re-wrapped around it.
 *
 * `AutoLayout` moves cards and then resizes every container to fit its
 * children again. Those are two different commands, and if they landed as two
 * history entries a user would undo the layout and be left looking at frames
 * fitted to positions nothing occupies any more — a state they never asked for
 * and cannot get out of in one step.
 *
 * The layout itself needs dagre and a JointJS graph, so what is asserted here
 * is the mechanism `AutoLayout` relies on: that `history.transact` composes a
 * batch move and a resize into a single undoable step. The arrangement was
 * verified in a browser separately; this is the part that can silently regress.
 */
describe('a move and a resize inside one transaction', () => {
  let workbench: Workbench;

  beforeEach(() => {
    workbench = makeWorkbench();
  });

  it('undoes as a single step', () => {
    const frame = addNode(workbench, 'annotate.group', { at: { x: 0, y: 0 } });
    const card = addNode(workbench, 'input.text', { at: { x: 10, y: 10 } });
    workbench.controller.grouping.setParent(card.id, frame.id);

    const framePosition = { ...frame.position };
    const frameSize = { ...frame.size };
    const cardPosition = { ...card.position };
    const depthBefore = undoDepth(workbench);

    workbench.controller.history.transact('Auto layout', () => {
      workbench.controller.nodes.move([{ nodeId: card.id, position: { x: 400, y: 300 } }], false);
      workbench.controller.nodes.resize(frame.id, { width: 340, height: 470 });
      workbench.controller.nodes.move([{ nodeId: frame.id, position: { x: 360, y: 172 } }], false);
    });

    // Everything landed.
    expect(card.position).toEqual({ x: 400, y: 300 });
    expect(frame.size).toEqual({ width: 340, height: 470 });
    expect(frame.position).toEqual({ x: 360, y: 172 });
    // …as exactly one entry, which is the property under test.
    expect(undoDepth(workbench)).toBe(depthBefore + 1);

    workbench.controller.history.undo();

    expect(card.position).toEqual(cardPosition);
    expect(frame.position).toEqual(framePosition);
    expect(frame.size).toEqual(frameSize);
  });

  it('redoes as a single step too', () => {
    const frame = addNode(workbench, 'annotate.group', { at: { x: 0, y: 0 } });
    const card = addNode(workbench, 'input.text', { at: { x: 10, y: 10 } });
    workbench.controller.grouping.setParent(card.id, frame.id);

    workbench.controller.history.transact('Auto layout', () => {
      workbench.controller.nodes.move([{ nodeId: card.id, position: { x: 400, y: 300 } }], false);
      workbench.controller.nodes.resize(frame.id, { width: 340, height: 470 });
    });
    workbench.controller.history.undo();
    workbench.controller.history.redo();

    expect(card.position).toEqual({ x: 400, y: 300 });
    expect(frame.size).toEqual({ width: 340, height: 470 });
  });

  it('records nothing when the arrangement changed nothing', () => {
    // `AutoLayout` returns before opening a transaction when there is no move
    // and no resize to make. Re-running Arrange on an already-arranged canvas
    // must not stack empty entries a user then has to undo one by one.
    addNode(workbench, 'input.text', { at: { x: 10, y: 10 } });
    const depthBefore = undoDepth(workbench);
    expect(depthBefore).toBeGreaterThanOrEqual(0);
    // No transact call at all — the guard is in AutoLayout, asserted here as
    // the contract it depends on: an empty transaction adds no entry either.
    workbench.controller.history.transact('Auto layout', () => {});
    expect(undoDepth(workbench)).toBe(depthBefore);
  });
});

/**
 * Arrange replaces every waypoint, and one Cmd-Z brings the hand-routing back.
 *
 * This is the promise that makes the replacement acceptable. A hand-placed
 * point is chosen against where the cards were; once they have all moved it is
 * a point in space nobody chose, and a run detouring through it reads as a
 * defect. So the layout clears them — but inside the *same* transaction as the
 * moves, so the discard is one undo away and never silent.
 */
describe('waypoints when the arrangement re-runs', () => {
  let workbench: Workbench;

  beforeEach(() => {
    workbench = makeWorkbench();
  });

  it('restores hand-placed points in the same step that restores the positions', () => {
    const input = addNode(workbench, 'input.text', { at: { x: 40, y: 200 } });
    const agent = addNode(workbench, 'agent.llm', { at: { x: 400, y: 200 } });
    connect(workbench, input, 'text', agent, 'prompt');
    const edge = workbench.model.edges()[0]!;

    workbench.controller.edges.setVertices(edge.id, [{ x: 220, y: 40 }]);
    const depthBefore = undoDepth(workbench);

    // What `AutoLayout` emits: the moves and the cleared waypoints together.
    workbench.controller.history.transact('Auto layout', () => {
      workbench.controller.nodes.move([{ nodeId: agent.id, position: { x: 700, y: 200 } }], false);
      workbench.controller.edges.setVertices(edge.id, []);
    });

    expect(edge.vertices).toEqual([]);
    expect(undoDepth(workbench)).toBe(depthBefore + 1);

    workbench.controller.history.undo();

    expect(edge.vertices).toEqual([{ x: 220, y: 40 }]);
    expect(agent.position).toEqual({ x: 400, y: 200 });
  });

  it('collapses a drag — one change per frame — into a single undo step', () => {
    const input = addNode(workbench, 'input.text', { at: { x: 40, y: 200 } });
    const agent = addNode(workbench, 'agent.llm', { at: { x: 400, y: 200 } });
    connect(workbench, input, 'text', agent, 'prompt');
    const edge = workbench.model.edges()[0]!;
    const depthBefore = undoDepth(workbench);

    for (const y of [40, 60, 80, 100]) {
      workbench.controller.edges.setVertices(edge.id, [{ x: 220, y }]);
    }

    expect(edge.vertices).toEqual([{ x: 220, y: 100 }]);
    expect(undoDepth(workbench)).toBe(depthBefore + 1);

    workbench.controller.history.undo();
    // Back to *before the gesture*, not to the frame before last.
    expect(edge.vertices).toEqual([]);
  });
});

/** How many entries the stack would pop, measured by popping and restoring. */
function undoDepth(workbench: Workbench): number {
  let depth = 0;
  while (workbench.controller.history.canUndo) {
    workbench.controller.history.undo();
    depth += 1;
  }
  for (let index = 0; index < depth; index += 1) workbench.controller.history.redo();
  return depth;
}
