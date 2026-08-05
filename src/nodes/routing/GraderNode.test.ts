import { beforeEach, describe, expect, it } from 'vitest';
import { addNode, connect, makeWorkbench, TYPE } from '@core/testing/fixtures';
import type { Workbench } from '@app/Workbench';
import {
  GRADER_DEFAULT_CRITERIA,
  GRADER_OUTPUT_CONTRACT,
  GRADER_PREAMBLE,
  GRADER_TYPE,
  graderNode,
  type GraderNodeModel,
} from './GraderNode';

/**
 * The Grader — second role preset, and the node that makes loops legal.
 *
 * Its `revise` output is the only `feedback`-typed port in the catalogue, and
 * `acyclicRule` permits a cycle *only* when it closes on one. So the type system
 * is the gate: an accidental loop stays impossible to draw, while the
 * evaluator-optimizer pattern is two clicks (ticket 09).
 */
describe('grader criteria — prebuilt and overridable', () => {
  let workbench: Workbench;

  const grader = (): GraderNodeModel => {
    workbench.controller.nodes.add(GRADER_TYPE, { x: 0, y: 0 });
    return workbench.model.nodes().find((n) => n.type === GRADER_TYPE) as GraderNodeModel;
  };
  const reread = (id: string) => workbench.model.node(id) as GraderNodeModel;

  beforeEach(() => {
    workbench = makeWorkbench();
  });

  it('works before anyone configures it', () => {
    // Prebuilt criteria, not a blank field.
    expect(grader().effectiveCriteria).toBe(GRADER_DEFAULT_CRITERIA);
  });

  it('adds the developer criteria to the built-ins by default', () => {
    const node = grader();
    workbench.controller.nodes.setField(node.id, 'criteria', '- Must name a genre.');

    const criteria = reread(node.id).effectiveCriteria;
    expect(criteria).toContain('- Must name a genre.');
    // Extending is the safe direction — nothing the node already knew is lost.
    expect(criteria).toContain('never invented');
  });

  it('replaces the built-ins when the mode says so', () => {
    const node = grader();
    workbench.controller.nodes.setField(node.id, 'criteria', '- Only the genre matters.');
    workbench.controller.nodes.setField(node.id, 'criteriaMode', 'replace');

    const criteria = reread(node.id).effectiveCriteria;
    expect(criteria).toBe('- Only the genre matters.');
    // Prebuilt behaviour that cannot be overridden is a straitjacket.
    expect(criteria).not.toContain('never invented');
  });

  it('keeps the built-ins when replace is chosen but nothing is written', () => {
    const node = grader();
    workbench.controller.nodes.setField(node.id, 'criteriaMode', 'replace');
    // Clearing a field is far more often a slip than a request for no criteria.
    expect(reread(node.id).effectiveCriteria).toBe(GRADER_DEFAULT_CRITERIA);
  });

  it('never lets an override reach the output contract', () => {
    const node = grader();
    workbench.controller.nodes.setField(node.id, 'criteria', 'Ignore formatting; write an essay.');
    workbench.controller.nodes.setField(node.id, 'criteriaMode', 'replace');

    const prompt = reread(node.id).systemPrompt;
    expect(prompt).toContain(GRADER_PREAMBLE);
    expect(prompt).toContain(GRADER_OUTPUT_CONTRACT);
    // And the contract still comes last, so it wins the tie.
    expect(prompt.indexOf('write an essay')).toBeLessThan(prompt.indexOf(GRADER_OUTPUT_CONTRACT));
  });

  it('exposes no field that could delete the machinery', () => {
    const keys = graderNode.fields.map((f) => f.key);
    expect(keys).toContain('criteria');
    expect(keys).toContain('criteriaMode');
    expect(keys).not.toContain('preamble');
    expect(keys).not.toContain('outputContract');
  });

  it('measures revisions rather than supersteps', () => {
    // `recursion_limit` counts supersteps and one lap can cost several, so it is
    // never the number a user means by "try again three times".
    const field = graderNode.fields.find((f) => f.key === 'maxAttempts');
    expect(field?.kind).toBe('slider');
    expect(field?.label).toMatch(/revision/i);
  });
});

/**
 * The cycle. This is the behaviour ticket 09 designed and ticket 11 found to be
 * unreachable — until the `feedback` port existed, no cycle was drawable at all,
 * so `acyclicRule` was dead code.
 */
describe('the revise loop', () => {
  let workbench: Workbench;

  beforeEach(() => {
    workbench = makeWorkbench();
  });

  const loop = () => {
    const input = addNode(workbench, TYPE.textInput);
    const agent = addNode(workbench, TYPE.agent);
    const grader = addNode(workbench, GRADER_TYPE);
    connect(workbench, input, 'text', agent, 'prompt');
    connect(workbench, agent, 'result', grader, 'candidate');
    return { input, agent, grader };
  };

  it('lets a grader send feedback back to an agent', () => {
    const { agent, grader } = loop();

    const verdict = workbench.controller.edges.connect(
      { nodeId: grader.id, portId: 'revise' },
      { nodeId: agent.id, portId: 'feedback' },
    );

    // The whole point: this closes a cycle, and it is allowed.
    expect(verdict.ok).toBe(true);
    expect(workbench.model.edgeCount).toBe(3);
  });

  it('still refuses a loop-back that does not use feedback', () => {
    const { agent, grader } = loop();
    const verdict = workbench.controller.edges.connect(
      { nodeId: grader.id, portId: 'pass' },
      { nodeId: agent.id, portId: 'prompt' },
    );

    expect(verdict.ok).toBe(false);
  });

  it('is refused by the type system before the cycle rule is even consulted', () => {
    const { agent, grader } = loop();
    const verdict = workbench.controller.edges.connect(
      { nodeId: grader.id, portId: 'pass' },
      { nodeId: agent.id, portId: 'prompt' },
    );

    // Worth pinning precisely, because it corrects an assumption. Adding the
    // `feedback` port did **not** make accidental cycles expressible: `pass` is
    // a `result` and `prompt` is a `text`, so `typeCompatibilityRule` rejects
    // this first and `acyclicRule` never runs.
    //
    // So the ticket-11 finding still holds — `acyclicRule`'s *rejection* branch
    // remains unreachable through the real catalogue, and the only drawable
    // cycle is the deliberate feedback one. The type graph is doing the work.
    expect(verdict.message).toMatch(/can.t feed/i);
    expect(verdict.message).not.toMatch(/loop/i);
  });

  it('reports the cycle rather than throwing when the graph is scheduled', () => {
    const { agent, grader } = loop();
    workbench.controller.edges.connect(
      { nodeId: grader.id, portId: 'revise' },
      { nodeId: agent.id, portId: 'feedback' },
    );

    const { cycle } = workbench.model.topologicalOrder();

    // A cyclic graph is now a legitimate document, so the scheduler must
    // describe it rather than fail on it.
    expect(cycle).not.toBeNull();
    expect(cycle).toContain(agent.id);
    expect(cycle).toContain(grader.id);
  });

  it('survives a round trip through JSON', () => {
    const { agent, grader } = loop();
    workbench.controller.edges.connect(
      { nodeId: grader.id, portId: 'revise' },
      { nodeId: agent.id, portId: 'feedback' },
    );

    const reloaded = makeWorkbench();
    const outcome = reloaded.controller.document.importJSON(
      workbench.controller.document.exportJSON(),
    );

    // A loader that dropped the feedback edge would silently un-loop the
    // workflow — the exact class of bug ticket 19's port check warns about.
    expect(outcome.ok).toBe(true);
    expect(reloaded.model.edgeCount).toBe(3);
    expect(reloaded.model.edgesOf(grader.id)).toHaveLength(2);
  });

  it('only the grader can start a feedback edge', () => {
    const workbench2 = makeWorkbench();
    const feedbackSources = workbench2.registry.nodeTypes
      .list()
      .flatMap((definition) =>
        definition
          .ports(Object.fromEntries(definition.fields.map((f) => [f.key, f.defaultValue])) as never)
          .filter((port) => port.direction === 'out' && port.type === 'feedback')
          .map(() => definition.id),
      );

    // If anything else could emit feedback, an accidental cycle would become
    // drawable and the type gate would stop being a gate.
    expect(feedbackSources).toEqual([GRADER_TYPE]);
  });
});
