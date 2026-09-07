import { beforeEach, describe, expect, it } from 'vitest';
import { addNode, connect, makeWorkbench, TYPE } from '@core/testing/fixtures';
import type { Workbench } from '@app/Workbench';
import { GUARD_CHECK_TYPE, type GuardCheckNodeModel } from './GuardCheckNode';

/**
 * `route.grader`'s mechanical sibling (`launch-readiness` 65): same
 * `pass`/`revise` port shape, no model. These tests pin the editor half of
 * the fix — the port shape and the cycle it is allowed to close — mirroring
 * `GraderNode.test.ts`'s "the revise loop" suite so the two families stay
 * provably symmetric.
 */
describe('guard check — port shape', () => {
  let workbench: Workbench;

  const guard = (): GuardCheckNodeModel => {
    workbench.controller.nodes.add(GUARD_CHECK_TYPE, { x: 0, y: 0 });
    return workbench.model.nodes().find((n) => n.type === GUARD_CHECK_TYPE) as GuardCheckNodeModel;
  };

  beforeEach(() => {
    workbench = makeWorkbench();
  });

  it('names the check on the card, or says none is named', () => {
    const g = guard();
    expect(g.subtitle).toBe('No check named yet.');
    workbench.controller.nodes.setField(g.id, 'check', 'validate_sql');
    const reread = workbench.model.node(g.id) as GuardCheckNodeModel;
    expect(reread.subtitle).toBe('checks: validate_sql');
  });
});

describe('the guard revise loop', () => {
  let workbench: Workbench;

  beforeEach(() => {
    workbench = makeWorkbench();
  });

  const loop = () => {
    const input = addNode(workbench, TYPE.textInput);
    const agent = addNode(workbench, TYPE.agent);
    const guardNode = addNode(workbench, GUARD_CHECK_TYPE);
    connect(workbench, input, 'text', agent, 'prompt');
    connect(workbench, agent, 'result', guardNode, 'candidate');
    return { input, agent, guardNode };
  };

  it('lets a guard send feedback back to an agent, deterministically', () => {
    const { agent, guardNode } = loop();

    const verdict = workbench.controller.edges.connect(
      { nodeId: guardNode.id, portId: 'revise' },
      { nodeId: agent.id, portId: 'feedback' },
    );

    // The whole point: a mechanical check closes a loop, no model in it.
    expect(verdict.ok).toBe(true);
    expect(workbench.model.edgeCount).toBe(3);
  });

  it('still refuses a loop-back through the pass port — an accidental cycle stays inexpressible', () => {
    const { agent, guardNode } = loop();
    const verdict = workbench.controller.edges.connect(
      { nodeId: guardNode.id, portId: 'pass' },
      { nodeId: agent.id, portId: 'prompt' },
    );

    // Same gate a grader is held to: `pass` is an ordinary `result` port, so
    // only `revise` — the one `feedback`-typed port — may close a cycle.
    // `acyclicRule` never had to change for this node type to exist.
    expect(verdict.ok).toBe(false);
    expect(verdict.message).toMatch(/loop/i);
  });

  it('reports the cycle rather than throwing when the graph is scheduled', () => {
    const { agent, guardNode } = loop();
    workbench.controller.edges.connect(
      { nodeId: guardNode.id, portId: 'revise' },
      { nodeId: agent.id, portId: 'feedback' },
    );

    const { cycle } = workbench.model.topologicalOrder();
    expect(cycle).not.toBeNull();
    expect(cycle).toContain(agent.id);
    expect(cycle).toContain(guardNode.id);
  });
});
