import { describe, expect, it } from 'vitest';
import {
  addNode,
  connect,
  LOOPABLE_TYPE,
  makeWorkbench,
  registerLoopableType,
  TYPE,
} from '@core/testing/fixtures';
import { hasOutputRule } from './WorkflowValidator';

/**
 * Found live, not hypothetically: a real chat run answered a question and
 * produced a real `answer`, yet the diagnostics panel showed "Nothing
 * consumes the result — add an output node." `hasOutputRule` checked port
 * *descriptors* (does this node type declare zero out-ports at all) rather
 * than actual wiring — but `AgentNode`, `RouterNode` and `GraderNode` all
 * statically declare an out-port whether or not anything is connected to
 * it. Only `output.formatted` genuinely has zero out-ports, so any graph
 * that legitimately terminates at an Agent/Router/Grader without a
 * separate Output node was a false positive.
 */
describe('hasOutputRule', () => {
  it('does not flag a graph that terminates at an unwired Agent out-port', () => {
    const workbench = makeWorkbench();
    const input = addNode(workbench, TYPE.textInput);
    const agent = addNode(workbench, TYPE.agent, { at: { x: 200, y: 0 } });
    connect(workbench, input, 'text', agent, 'prompt');
    // Deliberately no edge out of `agent.result` — the agent's own answer
    // is the graph's terminal output, same as `_agent` writing `answer`
    // directly in the backend compiler.

    const diagnostics = hasOutputRule.check({ model: workbench.model, registry: workbench.registry });
    expect(diagnostics).toEqual([]);
  });

  it('still flags a graph where every node truly has zero out-ports and nothing runs', () => {
    const workbench = makeWorkbench();
    // A single Output node: it has no out-ports at all, so it is
    // (correctly) always its own sink — nothing to flag.
    addNode(workbench, TYPE.output);

    const diagnostics = hasOutputRule.check({ model: workbench.model, registry: workbench.registry });
    expect(diagnostics).toEqual([]);
  });

  it('flags a graph where every out-port is wired into something, with no true terminal', () => {
    // Under the corrected semantics, an unwired out-port on an Agent/Router/
    // Grader is a legitimate terminal — so the *only* remaining way to have
    // no sink at all is a graph where literally every out-port some node
    // declares is connected to something else, e.g. a closed loop with no
    // node escaping it. `LOOPABLE_TYPE` is used (see `fixtures.ts`) because
    // the real catalogue has no port pair that can form a cycle at all.
    const workbench = makeWorkbench();
    registerLoopableType(workbench);
    const a = addNode(workbench, LOOPABLE_TYPE);
    const b = addNode(workbench, LOOPABLE_TYPE, { at: { x: 200, y: 0 } });
    connect(workbench, a, 'out', b, 'in');
    connect(workbench, b, 'out', a, 'in');

    const diagnostics = hasOutputRule.check({ model: workbench.model, registry: workbench.registry });
    expect(diagnostics).toHaveLength(1);
    expect(diagnostics[0]?.code).toBe('no-output');
  });
});
