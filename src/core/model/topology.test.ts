import { beforeEach, describe, expect, it } from 'vitest';
import type { Workbench } from '@app/Workbench';
import {
  addNode,
  connect,
  LOOPABLE_TYPE,
  makeWorkbench,
  registerLoopableType,
  TYPE,
} from '@core/testing/fixtures';
import { closestEdgeToPoint } from './topology';

/**
 * Execution order and graph queries.
 *
 * The scheduler decides what runs and when. Its failure modes are quiet: a
 * wrong order produces a node reading a value its upstream has not written
 * yet, which surfaces as a confusing empty result rather than an error.
 */
describe('WorkflowModel.topologicalOrder', () => {
  let workbench: Workbench;

  beforeEach(() => {
    workbench = makeWorkbench();
  });

  it('returns an empty order for an empty graph', () => {
    const { order, cycle } = workbench.model.topologicalOrder();
    expect(order).toEqual([]);
    expect(cycle).toBeNull();
  });

  it('orders a linear chain upstream-first', () => {
    const input = addNode(workbench, TYPE.textInput);
    const agent = addNode(workbench, TYPE.agent);
    const output = addNode(workbench, TYPE.output);
    connect(workbench, input, 'text', agent, 'prompt');
    connect(workbench, agent, 'result', output, 'result');

    const { order } = workbench.model.topologicalOrder();

    expect(order.indexOf(input.id)).toBeLessThan(order.indexOf(agent.id));
    expect(order.indexOf(agent.id)).toBeLessThan(order.indexOf(output.id));
  });

  it('places a node after every one of its dependencies, not just the first', () => {
    // A join: two inputs must both precede the agent.
    const prompt = addNode(workbench, TYPE.textInput);
    const skill = addNode(workbench, TYPE.markdownFile);
    const tool = addNode(workbench, TYPE.redditSearch);
    const agent = addNode(workbench, TYPE.agent);
    connect(workbench, prompt, 'text', agent, 'prompt');
    connect(workbench, skill, 'skill', agent, 'skill');
    connect(workbench, tool, 'tool', agent, 'tools');

    const { order } = workbench.model.topologicalOrder();
    const agentAt = order.indexOf(agent.id);

    for (const dependency of [prompt.id, skill.id, tool.id]) {
      expect(order.indexOf(dependency)).toBeLessThan(agentAt);
    }
  });

  it('includes disconnected nodes', () => {
    addNode(workbench, TYPE.textInput);
    addNode(workbench, TYPE.output);
    const { order } = workbench.model.topologicalOrder();
    // An orphan is not an error — it simply produces nothing.
    expect(order).toHaveLength(2);
  });

  it('seeds in insertion order so an unconstrained graph runs as it was built', () => {
    const first = addNode(workbench, TYPE.textInput);
    const second = addNode(workbench, TYPE.textInput);
    const third = addNode(workbench, TYPE.textInput);

    const { order } = workbench.model.topologicalOrder();

    // Arbitrary ordering would make runs hard to reason about; matching
    // build order is the least surprising choice.
    expect(order).toEqual([first.id, second.id, third.id]);
  });

  it('excludes annotations and containers, which never execute', () => {
    const agent = addNode(workbench, TYPE.agent);
    const note = addNode(workbench, TYPE.note);
    const group = addNode(workbench, TYPE.group);

    const { order } = workbench.model.topologicalOrder();

    expect(order).toContain(agent.id);
    expect(order).not.toContain(note.id);
    expect(order).not.toContain(group.id);
  });

  it('is not stalled by an edge touching a non-executable node', () => {
    // A container is excluded from the schedule, so an edge involving one
    // must be skipped rather than counted as an unmet dependency.
    const input = addNode(workbench, TYPE.textInput);
    const agent = addNode(workbench, TYPE.agent);
    const group = addNode(workbench, TYPE.group);
    workbench.model.setNodeParent(agent.id, group.id);
    connect(workbench, input, 'text', agent, 'prompt');

    const { order, cycle } = workbench.model.topologicalOrder();

    expect(cycle).toBeNull();
    expect(order).toHaveLength(2);
  });

  describe('cycles', () => {
    beforeEach(() => registerLoopableType(workbench));

    it('reports the offending nodes instead of throwing', () => {
      const a = addNode(workbench, LOOPABLE_TYPE);
      const b = addNode(workbench, LOOPABLE_TYPE);
      connect(workbench, a, 'out', b, 'in');
      connect(workbench, b, 'out', a, 'in');

      const { cycle } = workbench.model.topologicalOrder();

      // Returning the cycle rather than throwing is deliberate: the UI has to
      // highlight the offending nodes, and a cyclic graph is a legitimate
      // intermediate state while the user is building.
      expect(cycle).not.toBeNull();
      expect(cycle).toContain(a.id);
      expect(cycle).toContain(b.id);
    });

    it('still orders the acyclic part of a partly cyclic graph', () => {
      const clean = addNode(workbench, LOOPABLE_TYPE);
      const a = addNode(workbench, LOOPABLE_TYPE);
      const b = addNode(workbench, LOOPABLE_TYPE);
      connect(workbench, a, 'out', b, 'in');
      connect(workbench, b, 'out', a, 'in');

      const { order, cycle } = workbench.model.topologicalOrder();

      expect(order).toContain(clean.id);
      expect(cycle).not.toContain(clean.id);
    });
  });
});

/**
 * Adjacency queries.
 *
 * Maintained as an incremental index rather than recomputed, because
 * validation walks a port's neighbours on every pointer move while a link is
 * being dragged. Worth pinning down that the index stays correct after
 * removals.
 */
describe('WorkflowModel adjacency', () => {
  let workbench: Workbench;

  beforeEach(() => {
    workbench = makeWorkbench();
  });

  it('reports predecessors and successors', () => {
    const input = addNode(workbench, TYPE.textInput);
    const agent = addNode(workbench, TYPE.agent);
    connect(workbench, input, 'text', agent, 'prompt');

    expect(workbench.model.predecessorsOf(agent.id).map((n) => n.id)).toEqual([input.id]);
    expect(workbench.model.successorsOf(input.id).map((n) => n.id)).toEqual([agent.id]);
  });

  it('deduplicates a neighbour reached by two edges', () => {
    const input = addNode(workbench, TYPE.textInput);
    const output = addNode(workbench, TYPE.output);
    // Two distinct links between the same pair of nodes.
    connect(workbench, input, 'text', output, 'result');
    const agent = addNode(workbench, TYPE.agent);
    connect(workbench, input, 'text', agent, 'prompt');
    connect(workbench, agent, 'result', output, 'result');

    expect(workbench.model.predecessorsOf(output.id)).toHaveLength(2);
  });

  it('drops an edge from the index when it is removed', () => {
    const input = addNode(workbench, TYPE.textInput);
    const agent = addNode(workbench, TYPE.agent);
    const edge = connect(workbench, input, 'text', agent, 'prompt');

    workbench.model.removeEdge(edge.id);

    expect(workbench.model.edgesOf(agent.id)).toHaveLength(0);
    expect(workbench.model.predecessorsOf(agent.id)).toHaveLength(0);
  });

  it('drops a removed node’s edges from its neighbour’s index', () => {
    const input = addNode(workbench, TYPE.textInput);
    const agent = addNode(workbench, TYPE.agent);
    connect(workbench, input, 'text', agent, 'prompt');

    workbench.model.removeNode(input.id);

    // A stale entry here would leave validation consulting a phantom link.
    expect(workbench.model.edgesOf(agent.id)).toHaveLength(0);
  });

  it('walks a container’s descendants transitively', () => {
    const outer = addNode(workbench, TYPE.group);
    const inner = addNode(workbench, TYPE.group);
    const agent = addNode(workbench, TYPE.agent);
    workbench.model.setNodeParent(inner.id, outer.id);
    workbench.model.setNodeParent(agent.id, inner.id);

    const ids = workbench.model.descendantsOf(outer.id).map((n) => n.id);
    expect(ids).toContain(inner.id);
    expect(ids).toContain(agent.id);
  });

  it('refuses to embed a container inside its own subtree', () => {
    const outer = addNode(workbench, TYPE.group);
    const inner = addNode(workbench, TYPE.group);
    workbench.model.setNodeParent(inner.id, outer.id);

    workbench.model.setNodeParent(outer.id, inner.id);

    // Allowing this would make descendantsOf recurse forever.
    expect(workbench.model.node(outer.id)?.parentId).toBeNull();
  });
});

/**
 * Ticket 25's splice-insert drop gesture: "is this drop point near an
 * existing link." Tested against plain model data (node centres), not a
 * live canvas — the approximation this function deliberately makes.
 */
describe('closestEdgeToPoint', () => {
  let workbench: Workbench;

  beforeEach(() => {
    workbench = makeWorkbench();
    registerLoopableType(workbench);
  });

  it('finds the edge whose node-centre line passes near the point', () => {
    const a = addNode(workbench, LOOPABLE_TYPE, { at: { x: 0, y: 0 } });
    const b = addNode(workbench, LOOPABLE_TYPE, { at: { x: 400, y: 0 } });
    const edge = connect(workbench, a, 'out', b, 'in');

    const midpoint = {
      x: (a.position.x + a.size.width / 2 + b.position.x + b.size.width / 2) / 2,
      y: (a.position.y + a.size.height / 2 + b.position.y + b.size.height / 2) / 2,
    };

    const found = closestEdgeToPoint(
      (id) => workbench.model.node(id),
      workbench.model.edges(),
      midpoint,
      20,
    );
    expect(found).toBe(edge.id);
  });

  it('returns null when nothing is within the given distance', () => {
    const a = addNode(workbench, LOOPABLE_TYPE, { at: { x: 0, y: 0 } });
    const b = addNode(workbench, LOOPABLE_TYPE, { at: { x: 400, y: 0 } });
    connect(workbench, a, 'out', b, 'in');

    const found = closestEdgeToPoint(
      (id) => workbench.model.node(id),
      workbench.model.edges(),
      { x: 200, y: 500 },
      20,
    );
    expect(found).toBeNull();
  });

  it('picks the closer of two candidate edges', () => {
    const a = addNode(workbench, LOOPABLE_TYPE, { at: { x: 0, y: 0 } });
    const b = addNode(workbench, LOOPABLE_TYPE, { at: { x: 400, y: 0 } });
    const c = addNode(workbench, LOOPABLE_TYPE, { at: { x: 0, y: 200 } });
    const near = connect(workbench, a, 'out', b, 'in');
    connect(workbench, a, 'out', c, 'in');

    const nearMidpoint = {
      x: (a.position.x + a.size.width / 2 + b.position.x + b.size.width / 2) / 2,
      y: (a.position.y + a.size.height / 2 + b.position.y + b.size.height / 2) / 2,
    };

    const found = closestEdgeToPoint(
      (id) => workbench.model.node(id),
      workbench.model.edges(),
      nearMidpoint,
      300,
    );
    expect(found).toBe(near.id);
  });
});
