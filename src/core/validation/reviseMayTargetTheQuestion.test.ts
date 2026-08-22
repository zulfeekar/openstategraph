import { beforeEach, describe, expect, it } from 'vitest';
import type { Workbench } from '@app/Workbench';
import { addNode, connect, makeWorkbench, TYPE } from '@core/testing/fixtures';
import type { AbstractNodeModel } from '@core/model/AbstractNodeModel';

/**
 * `organisms-first-class/37` — may a grader's `revise` edge land on a node
 * *upstream* of the candidate's producer, rather than on the producer itself?
 *
 * LangChain's `agentic-rag.mdx` grades **retrieved context** and routes to
 * `rewrite_question`, which edges back to the model node. Ours is written
 * around "is this *answer* good enough" — same two nodes, different subject.
 *
 * The answer this file pins is **yes, and it always was**: `acyclicRule` gates
 * on the *port type* and never asks who produced the candidate, exactly as
 * CLAUDE.md's "cycles are gated by port type" says it should. So the shape is
 * config, not a mechanism — and the thing worth pinning is that the three
 * inverses which make the gate a gate are still inverses.
 */
describe('a revise edge may reshape the question (organisms-first-class/37)', () => {
  let workbench: Workbench;
  let input: AbstractNodeModel;
  let rewrite: AbstractNodeModel;
  let retrieve: AbstractNodeModel;
  let grader: AbstractNodeModel;
  let output: AbstractNodeModel;

  beforeEach(() => {
    workbench = makeWorkbench();
    input = addNode(workbench, TYPE.textInput);
    rewrite = addNode(workbench, TYPE.agent);
    retrieve = addNode(workbench, TYPE.agent);
    grader = addNode(workbench, TYPE.grader);
    output = addNode(workbench, TYPE.output);

    // `in1 → rewrite1 → retrieve1 → grader1 → out1`, the shipped
    // `agentic-rag-rewrite` topology minus its knowledge tool.
    connect(workbench, input, 'text', rewrite, 'prompt');
    connect(workbench, rewrite, 'result', retrieve, 'prompt');
    connect(workbench, retrieve, 'result', grader, 'candidate');
    connect(workbench, grader, 'pass', output, 'result');
  });

  const validate = (
    from: AbstractNodeModel,
    fromPort: string,
    to: AbstractNodeModel,
    toPort: string,
  ) =>
    workbench.connectionValidator.validate(
      { nodeId: from.id, portId: fromPort },
      { nodeId: to.id, portId: toPort },
    );

  it('closes the loop two nodes upstream of the candidate’s producer', () => {
    // `retrieve1` produced the candidate; the feedback goes to `rewrite1`,
    // which shapes the question `retrieve1` will be asked next lap.
    expect(validate(grader, 'revise', rewrite, 'feedback').ok).toBe(true);
  });

  it('draws it through the controller, not only in the verdict', () => {
    const verdict = workbench.controller.edges.connect(
      { nodeId: grader.id, portId: 'revise' },
      { nodeId: rewrite.id, portId: 'feedback' },
    );

    expect(verdict.ok).toBe(true);
    expect(workbench.model.edgesInto({ nodeId: rewrite.id, portId: 'feedback' })).toHaveLength(1);
  });

  it('and the document validates, because the cycle has an escape', () => {
    connect(workbench, grader, 'revise', rewrite, 'feedback');
    const cycleFindings = workbench.workflowValidator
      .validate()
      .filter((finding) => finding.code === 'cycle');

    expect(cycleFindings).toEqual([]);
  });

  it('still closes on the producer — the evaluator-optimizer shape is unchanged', () => {
    expect(validate(grader, 'revise', retrieve, 'feedback').ok).toBe(true);
  });

  describe('the gate is still a gate', () => {
    it('refuses an accidental cycle, which is what the type gate buys', () => {
      // Nothing but `feedback` closes a loop, so an ordinary result-into-prompt
      // link back up the chain stays inexpressible.
      const verdict = validate(retrieve, 'result', rewrite, 'prompt');
      expect(verdict).toMatchObject({ ok: false });
      if (!verdict.ok) expect(verdict.reason).toMatch(/loop/i);
    });

    it('refuses a cycle with no way out of it, wherever the feedback lands', () => {
      // CLAUDE.md's "a cycle must contain at least one conditional edge" is
      // satisfied by construction here — every `feedback` source is a branch —
      // so the live half of that rule is the *escape*: a grader whose only
      // edge is `revise` leaves the cycle by nothing, and no verdict ends the
      // run. Moving the feedback upstream must not buy an exemption from it.
      const bench = makeWorkbench();
      const shaper = addNode(bench, TYPE.agent);
      const producer = addNode(bench, TYPE.agent);
      const judge = addNode(bench, TYPE.grader);
      connect(bench, shaper, 'result', producer, 'prompt');
      connect(bench, producer, 'result', judge, 'candidate');
      connect(bench, judge, 'revise', shaper, 'feedback');

      const codes = bench.workflowValidator.validate().map((finding) => finding.code);
      expect(codes).toContain('cycle');
    });

    it('refuses feedback into a family that declares no feedback input', () => {
      // A Router shapes input too, but it has no `feedback` port — so the
      // doc's shape is available to the families that declare one, and
      // extending it to the rest is a node-family change, not a rule change.
      const router = addNode(workbench, TYPE.router);
      expect(validate(grader, 'revise', router, 'question').ok).toBe(false);
      expect(router.ports.some((port) => port.type === 'feedback')).toBe(false);
    });
  });
  describe('the guidance a developer reads before drawing it', () => {
    // The condition the ticket records is prose, not a rule: the feedback is
    // written *about an answer*, and a node that must change the *question*
    // only does so because its Rules say to. Two port descriptions are where a
    // developer meets that, so they are pinned — from the descriptors, never
    // from source bytes.
    const describeOf = (node: AbstractNodeModel, portId: string) =>
      node.ports.find((port) => port.id === portId)?.description ?? '';

    it('does not tell the developer the target must be an agent that answered', () => {
      const copy = describeOf(grader, 'revise');
      expect(copy).toMatch(/reshapes the question/i);
      expect(copy).not.toMatch(/wire this to an agent/i);
    });

    it('tells the receiving agent that the choice is its own to declare', () => {
      const copy = describeOf(rewrite, 'feedback');
      expect(copy).toMatch(/Rules/);
      expect(copy).toMatch(/change the question/i);
    });
  });
});
