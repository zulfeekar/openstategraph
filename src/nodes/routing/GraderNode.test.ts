import { beforeEach, describe, expect, it } from 'vitest';
import { addNode, connect, makeWorkbench, TYPE } from '@core/testing/fixtures';
import type { Workbench } from '@app/Workbench';
import {
  GRADER_DEFAULT_CRITERIA,
  GRADER_TYPE,
  createGraderNode,
  type GraderNodeModel,
} from './GraderNode';
import { HUMAN_APPROVAL_TYPE } from './HumanApprovalNode';
import { CredentialStore, ProviderRegistry } from '@core/providers/ProviderRegistry';

/**
 * Materialised once per file. The definition is now built from the
 * `ProviderRegistry` — every model-driven family carries the shared model
 * picker (`../modelField`) — so the tests build one the same way the
 * catalogue does rather than asserting against a shape nothing registers.
 */
const graderNode = createGraderNode(new ProviderRegistry(new CredentialStore(false)));

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
    workbench.controller.nodes.setField(node.id, 'rulesMode', 'replace');

    const criteria = reread(node.id).effectiveCriteria;
    expect(criteria).toBe('- Only the genre matters.');
    // Prebuilt behaviour that cannot be overridden is a straitjacket.
    expect(criteria).not.toContain('never invented');
  });

  it('keeps the built-ins when replace is chosen but nothing is written', () => {
    const node = grader();
    workbench.controller.nodes.setField(node.id, 'rulesMode', 'replace');
    // Clearing a field is far more often a slip than a request for no criteria.
    expect(reread(node.id).effectiveCriteria).toBe(GRADER_DEFAULT_CRITERIA);
  });

  /**
   * What used to be asserted here — that an override cannot reach the output
   * contract — is now asserted where the contract is actually assembled, in
   * `backend/tests/test_prompt_sections_are_delimited.py`. The editor's own
   * `systemPrompt` getter was a consumer-less mirror of `SystemPrompt.render()`
   * and is gone (ticket 39). The reach of the override is still pinned above,
   * on `effectiveCriteria`, which is the layer the developer actually touches.
   */

  it('exposes no field that could delete the machinery', () => {
    const keys = graderNode.fields.map((f) => f.key);
    expect(keys).toContain('criteria');
    expect(keys).toContain('rulesMode');
    expect(keys).not.toContain('preamble');
    expect(keys).not.toContain('outputContract');
  });

  /**
   * `criteriaMode` **is** `rulesMode` under a narrower name — the same verb on
   * the same layers, generalised so all five prompted node types share one
   * switch (`docs/decisions/skill-layer.md`). A document saved before the
   * rename must therefore render the prompt it rendered yesterday.
   *
   * Read-time tolerance would not have been enough, and that is the point of
   * these two: node data is the schema defaults with the document merged over
   * them, and `toJSON` writes the whole record. A grader carrying
   * `criteriaMode: "replace"` would otherwise gain `rulesMode: "extend"` from
   * the new field's default and, on the next save, carry both — with the new
   * key winning on the backend. The document would have changed its own
   * behaviour by being opened.
   */
  it('keeps a document saved with criteriaMode behaving exactly as it did', () => {
    // Exactly what such a document holds: the old key, and no new one.
    const restored = graderNode.create({
      position: { x: 0, y: 0 },
      data: { criteria: '- Only the genre matters.', criteriaMode: 'replace' },
    }) as GraderNodeModel;

    expect(restored.replacesDefaults).toBe(true);
    expect(restored.effectiveCriteria).toBe('- Only the genre matters.');
  });

  it('and re-saves it under the one key, so the two can never disagree', () => {
    const restored = graderNode.create({
      position: { x: 0, y: 0 },
      data: { criteriaMode: 'replace' },
    }) as GraderNodeModel;

    expect(restored.toJSON().data['rulesMode']).toBe('replace');
    expect(restored.toJSON().data).not.toHaveProperty('criteriaMode');
  });

  it('lets an explicit rulesMode win wherever both keys appear', () => {
    // The backend's `_replaces_rules` states the same precedence: the legacy
    // key is a fallback, never a second setting.
    const restored = graderNode.create({
      position: { x: 0, y: 0 },
      data: { rulesMode: 'extend', criteriaMode: 'replace' },
    }) as GraderNodeModel;

    expect(restored.replacesDefaults).toBe(false);
  });

  it('says the budget is this grader\'s own, and counts attempts not revisions', () => {
    // `workflow-gallery` 21. The number is a count of candidates *this* grader
    // judges. It read "Max revisions" over a runtime that checked one
    // graph-wide counter every model node incremented, so the card promised a
    // relationship the number did not have — in both directions at once.
    //
    // `recursion_limit` is still not it either: that counts supersteps and one
    // lap can cost several, which is why the graph keeps its own counter.
    const field = graderNode.fields.find((f) => f.key === 'maxAttempts');
    expect(field?.kind).toBe('slider');
    expect(field?.label).toMatch(/attempt/i);
    expect(field?.label).not.toMatch(/revision/i);
    // The two claims a reader needs and could not get from the label: whose
    // budget it is, and that `n` attempts is `n - 1` revisions.
    expect(field?.hint).toMatch(/this grader/i);
    expect(field?.hint).toMatch(/its own/i);
    expect(field?.hint).toMatch(/3 attempts allows 2 revisions/i);
  });

  it('reads out attempts on the slider, and one attempt is singular', () => {
    const field = graderNode.fields.find((f) => f.key === 'maxAttempts');
    const format = (field as { format?: (v: number) => string }).format;
    expect(format?.(3)).toBe('· 3 attempts');
    expect(format?.(1)).toBe('· 1 attempt');
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

  it('is refused by the cycle rule, naming the feedback port as the way round', () => {
    const { agent, grader } = loop();
    const verdict = workbench.controller.edges.connect(
      { nodeId: grader.id, portId: 'pass' },
      { nodeId: agent.id, portId: 'prompt' },
    );

    // Superseding the ticket-11 note that used to sit here. Until ticket 08,
    // `prompt` refused a `result` outright, so `typeCompatibilityRule` caught
    // this and `acyclicRule`'s rejection branch was unreachable through the
    // real catalogue. Prompt chaining opened `prompt` to `result` — so the
    // cycle rule is now the load-bearing guard, and this pins that it holds:
    // `feedback` is still the only port type a loop may close on.
    expect(verdict.message).toMatch(/loop/i);
    expect(verdict.message).toMatch(/revise/i);
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

  it('only the grader and the human approval gate can start a feedback edge', () => {
    const workbench2 = makeWorkbench();
    const feedbackSources = workbench2.registry.nodeTypes.list().flatMap((definition) =>
      definition
        .ports(Object.fromEntries(definition.fields.map((f) => [f.key, f.defaultValue])) as never)
        .filter((port) => port.direction === 'out' && port.type === 'feedback')
        .map(() => definition.id),
    );

    // If anything else could emit feedback, an accidental cycle would become
    // drawable and the type gate would stop being a gate. `human.approval`'s
    // `rejected` port is the one other deliberate source — a human's reject
    // decision is, like a grader's verdict, a legitimate reason to route
    // feedback upstream.
    expect(feedbackSources).toEqual([GRADER_TYPE, HUMAN_APPROVAL_TYPE]);
  });
});
