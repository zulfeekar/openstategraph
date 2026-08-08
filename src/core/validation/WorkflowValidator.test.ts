import { describe, expect, it } from 'vitest';
import {
  addNode,
  connect,
  LOOPABLE_TYPE,
  makeWorkbench,
  registerLoopableType,
  TYPE,
} from '@core/testing/fixtures';
import { acyclicGraphRule, hasOutputRule, singleDefaultWorkerRule } from './WorkflowValidator';

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

/**
 * Found live: the diagnostics panel showed 11 identical "X is part of a
 * loop" `error`s for the intent-routed demo's real, intentional revise
 * loops (a grader's `revise` port feeding back into its own agent, with a
 * `pass` port that escapes the same cycle) — reading exactly as broken as
 * a real, unescapable infinite loop, even though the backend runs it fine.
 * CLAUDE.md's own rule: a cycle needs a conditional edge to be valid at
 * all. `acyclicGraphRule` now tells the two shapes apart.
 */
describe('acyclicGraphRule', () => {
  it('downgrades an escapable loop (one with a way out) to a warning', () => {
    const workbench = makeWorkbench();
    registerLoopableType(workbench);
    const a = addNode(workbench, LOOPABLE_TYPE);
    const b = addNode(workbench, LOOPABLE_TYPE, { at: { x: 200, y: 0 } });
    const c = addNode(workbench, LOOPABLE_TYPE, { at: { x: 400, y: 0 } });
    connect(workbench, a, 'out', b, 'in');
    connect(workbench, b, 'out', a, 'in');
    // `a`'s escape hatch — the same shape as a grader's `pass` port.
    connect(workbench, a, 'out', c, 'in');

    const diagnostics = acyclicGraphRule.check({ model: workbench.model, registry: workbench.registry });
    expect(diagnostics).toHaveLength(2);
    for (const d of diagnostics) {
      expect(d.severity).toBe('warning');
      expect(d.code).toBe('escapable-loop');
    }
  });

  it('keeps an unescapable loop (no way out at all) as a blocking error', () => {
    const workbench = makeWorkbench();
    registerLoopableType(workbench);
    const a = addNode(workbench, LOOPABLE_TYPE);
    const b = addNode(workbench, LOOPABLE_TYPE, { at: { x: 200, y: 0 } });
    connect(workbench, a, 'out', b, 'in');
    connect(workbench, b, 'out', a, 'in');

    const diagnostics = acyclicGraphRule.check({ model: workbench.model, registry: workbench.registry });
    expect(diagnostics).toHaveLength(2);
    for (const d of diagnostics) {
      expect(d.severity).toBe('error');
      expect(d.code).toBe('cycle');
    }
  });
});

/**
 * Ticket 37: unlabelled/unrecognised subtasks dispatch to the default worker
 * archetype. The compiler takes the first wired claimant, so a second card's
 * "Default worker" toggle is silently inert — worth a warning, not an error.
 */
describe('singleDefaultWorkerRule', () => {
  it('says nothing for zero or one default claim', () => {
    const workbench = makeWorkbench();
    const orchestrator = addNode(workbench, TYPE.orchestrator);
    const weather = addNode(workbench, TYPE.worker, { data: { default: true } });
    const countries = addNode(workbench, TYPE.worker, { at: { x: 200, y: 0 } });
    connect(workbench, orchestrator, 'workers', weather, 'dispatch');
    connect(workbench, orchestrator, 'workers', countries, 'dispatch');

    const diagnostics = singleDefaultWorkerRule.check({
      model: workbench.model,
      registry: workbench.registry,
    });
    expect(diagnostics).toEqual([]);
  });

  it('warns on every card when two workers both claim the default', () => {
    const workbench = makeWorkbench();
    const orchestrator = addNode(workbench, TYPE.orchestrator);
    const weather = addNode(workbench, TYPE.worker, { data: { default: true } });
    const countries = addNode(workbench, TYPE.worker, {
      at: { x: 200, y: 0 },
      data: { default: true },
    });
    connect(workbench, orchestrator, 'workers', weather, 'dispatch');
    connect(workbench, orchestrator, 'workers', countries, 'dispatch');

    const diagnostics = singleDefaultWorkerRule.check({
      model: workbench.model,
      registry: workbench.registry,
    });
    expect(diagnostics).toHaveLength(2);
    for (const d of diagnostics) {
      expect(d.severity).toBe('warning');
      expect(d.code).toBe('multiple-default-workers');
    }
  });
});
