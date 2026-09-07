import { describe, expect, it } from 'vitest';
import { CredentialStore, ProviderRegistry } from '@core/providers/ProviderRegistry';
import type { INodeDefinition } from '@core/model/contracts/node';
import { BINDING_SIDE, resolvePortSide, sideOf } from '@core/model/contracts/ports';
import { isBindingEdge } from '@canvas/layout/bindingLayout';
import { defaultsFrom } from '@core/model/contracts/fields';
import { addNode, makeWorkbench } from '@core/testing/fixtures';
import { createAgentNode } from '@nodes/agent/AgentNode';
import { createWorkerNode } from '@nodes/orchestrate/WorkerNode';
import { createOrchestratorNode } from '@nodes/orchestrate/OrchestratorNode';
import { createRouterNode } from '@nodes/routing/RouterNode';
import { createGraderNode } from '@nodes/routing/GraderNode';
import { markdownFileNode } from '@nodes/inputs/MarkdownFileNode';
import { planPortLayout } from '@view/nodes/portLayout';
import { RULES_MODE_KEY, SKILL_PORT_ID } from '@nodes/skillLayer';

/**
 * A skill is an **input**, and both ends of the wire say so.
 *
 * This file previously pinned the opposite, and the reversal is the point.
 * Declaring `skill` a binding (`BINDING_SIDE.consumer`) took the markdown card
 * out of the flow ranks and hung it on its consumer's shelf, which stopped its
 * line climbing across the Text Input above it — a real gain, recorded in
 * `docs/decisions/edge-legibility.md`. It also put the dot on the card's bottom
 * edge while the footer legend went on listing `prompt`, `feedback`, `skill` as
 * the card's inputs: two dots, three labels, and a hole in the left stack that
 * only a special "offside" style could paper over.
 *
 * Three cards feed an agent and three wires arrive; they arrive from the left.
 * `tools` stays a bus, because a bus genuinely gathers many and its pill is the
 * drawn language for that — a skill is one file on one wire and never had that
 * reason, only a tool's company. The crossings the shelf was suppressing come
 * back, and are ticket 09's obstacle-avoiding router to solve rather than the
 * port catalogue's.
 *
 * These tests pin both halves on the reading axis, and pin the things the move
 * could plausibly have broken.
 */

const providers = new ProviderRegistry(new CredentialStore(false));
const agentNode = createAgentNode(providers);
const workerNode = createWorkerNode(providers);
const orchestratorNode = createOrchestratorNode(providers);
const routerNode = createRouterNode(providers);
const graderNode = createGraderNode(providers);

/**
 * The five node types that compose a prompt, and therefore the five that take
 * a skill. A tool or an I/O atom has none, so a port there would be a control
 * reaching nothing.
 */
const MODEL_DRIVEN: ReadonlyArray<readonly [string, INodeDefinition]> = [
  ['agent.llm', agentNode],
  ['orchestrate.worker', workerNode],
  ['orchestrate.supervisor', orchestratorNode],
  ['route.classifier', routerNode],
  ['route.grader', graderNode],
];

/** `ports` is a function of node data — cardinality can vary with config. */
const portOf = (definition: INodeDefinition, id: string) => {
  const port = definition
    .ports(defaultsFrom(definition.fields) as never)
    .find((entry) => entry.id === id);
  if (!port) throw new Error(`no port ${id} on ${definition.id}`);
  return port;
};

describe('a skill travels the reading axis at both ends', () => {
  it('the markdown file sends it downstream, like any other output', () => {
    expect(sideOf(portOf(markdownFileNode, 'skill'))).toBe('right');
  });

  it.each(MODEL_DRIVEN)('%s takes it on the left, beside prompt', (_label, definition) => {
    expect(sideOf(portOf(definition, SKILL_PORT_ID))).toBe('left');
  });

  it.each(MODEL_DRIVEN)('%s gives it a dot on its own footer row', (_label, definition) => {
    // The defect the reversal exists to fix: the legend lists every port, so a
    // port drawn off the flank leaves a labelled row with no dot beside it.
    const ports = definition.ports(defaultsFrom(definition.fields) as never);
    const plan = planPortLayout(ports, 'horizontal');
    const row = plan.rows.find((entry) => entry.port.id === SKILL_PORT_ID);
    expect(row?.anchor).toBe('left');
    // And it is not sorted below the flank ports, since it is one of them now.
    const left = plan.rows.filter((entry) => entry.column === 'in' && entry.anchor === 'left');
    expect(left.map((entry) => entry.port.id)).toContain(SKILL_PORT_ID);
  });

  it.each(MODEL_DRIVEN)('%s takes a skill at all', (_label, definition) => {
    // Ticket 05: the Router, the Grader and the Supervisor had none, while the
    // compiler read `plan.skill_bindings` for all five. A missing capability
    // raises nothing — it simply never happens — so it had to be looked for.
    const port = definition
      .ports(defaultsFrom(definition.fields) as never)
      .find((p) => p.id === SKILL_PORT_ID);
    expect(port?.direction).toBe('in');
  });

  it.each(MODEL_DRIVEN)('%s honours the one extend/replace mode', (_label, definition) => {
    // Declared once, in `skillLayer.ts`. Five copies of a select is the
    // defect `modelField.ts` was created to undo, pre-made.
    const field = definition.fields.find((f) => f.key === RULES_MODE_KEY);
    expect(field?.kind).toBe('select');
    expect(field?.defaultValue).toBe('extend');
  });

  it('and no node shows two competing mode controls', () => {
    // `criteriaMode` **is** `rulesMode` under a narrower name. Keeping both
    // would be two spellings of one switch — the duplication-of-knowledge
    // defect the decision record rejects by name.
    for (const [, definition] of MODEL_DRIVEN) {
      expect(definition.fields.map((f) => f.key)).not.toContain('criteriaMode');
    }
  });

  it('the layout classifier reads the wire as flow again — the accepted cost', () => {
    // One field, `side`, still drives both the dot and this classification, so
    // moving the dot moves the card: the markdown file is a ranked predecessor
    // once more rather than a card on the agent's shelf. That is the trade the
    // reversal accepts, not an oversight — see `bindingLayout.isBindingEdge`
    // for why a separate `role` would make the picture worse, not better.
    expect(
      isBindingEdge({
        source: { nodeId: 'md1', side: sideOf(portOf(markdownFileNode, 'skill')), portRank: 0 },
        target: { nodeId: 'agent1', side: sideOf(portOf(agentNode, 'skill')), portRank: 1 },
      }),
    ).toBe(false);
  });

  it('while a tool bound to the same agent is still equipment', () => {
    // The shelf is not gone, only narrowed to the ports that earn it. If this
    // ever goes false, the reversal has taken the bus with it.
    expect(
      isBindingEdge({
        source: { nodeId: 'tool1', side: BINDING_SIDE.provider, portRank: 0 },
        target: { nodeId: 'agent1', side: sideOf(portOf(agentNode, 'tools')), portRank: 2 },
      }),
    ).toBe(true);
  });

  it('and still refuses a wire whose ends disagree', () => {
    // The guard that makes the "both ends" rule worth having: an ordinary
    // result arriving at a bus-shaped port is a stage, not equipment.
    expect(
      isBindingEdge({
        source: { nodeId: 'agent1', side: 'right', portRank: 0 },
        target: { nodeId: 'agent2', side: BINDING_SIDE.consumer, portRank: 1 },
      }),
    ).toBe(false);
  });
});

describe('what the side change must not have altered', () => {
  it('a skill still takes exactly one file', () => {
    // `tools` is a bus (`maxConnections: null`); a skill is one instruction
    // file. Sharing an edge with the bus must not make it behave like one.
    expect(portOf(agentNode, 'skill').maxConnections ?? 1).toBe(1);
  });

  it('it stays a plain dot — the card renders a single pill', () => {
    expect(portOf(agentNode, 'skill').appearance).toBeUndefined();
    expect(portOf(agentNode, 'tools').appearance).toBe('pill');
  });

  it('and the skill now rotates with the inputs, while the bus keeps its own axis', () => {
    const skill = portOf(agentNode, 'skill');
    const prompt = portOf(agentNode, 'prompt');
    const tools = portOf(agentNode, 'tools');
    // One rotation rule, unchanged; what changed is which group `skill` is in.
    expect(resolvePortSide(skill, 'horizontal')).toBe(resolvePortSide(prompt, 'horizontal'));
    expect(resolvePortSide(skill, 'vertical')).toBe(resolvePortSide(prompt, 'vertical'));
    expect(resolvePortSide(tools, 'horizontal')).toBe('bottom');
    expect(resolvePortSide(skill, 'horizontal')).not.toBe(resolvePortSide(tools, 'horizontal'));
    expect(resolvePortSide(skill, 'vertical')).not.toBe(resolvePortSide(tools, 'vertical'));
  });

  it.each(['route.classifier', 'route.grader', 'orchestrate.supervisor'])(
    'a tool still cannot be dropped into %s’s new skill port',
    (type) => {
      // Validation is side-blind — no connection rule reads `port.side` — so
      // type compatibility refuses this for the reason it always did. Pinned
      // for the three ports that did not exist yesterday, because "the rule
      // never read `side`" is an argument, and this is evidence.
      const workbench = makeWorkbench();
      const consumer = addNode(workbench, type);
      const tool = addNode(workbench, 'tool.web-search');
      const verdict = workbench.controller.edges.connect(
        { nodeId: tool.id, portId: 'tool' },
        { nodeId: consumer.id, portId: SKILL_PORT_ID },
      );
      expect(verdict.ok).toBe(false);
    },
  );

  it.each(['route.classifier', 'route.grader', 'orchestrate.supervisor'])(
    'but a markdown file wires into %s’s skill port',
    (type) => {
      const workbench = makeWorkbench();
      const consumer = addNode(workbench, type);
      const markdown = addNode(workbench, 'input.markdown');
      const verdict = workbench.controller.edges.connect(
        { nodeId: markdown.id, portId: SKILL_PORT_ID },
        { nodeId: consumer.id, portId: SKILL_PORT_ID },
      );
      expect(verdict.ok).toBe(true);
    },
  );

  it('a tool still cannot be dropped into the skill port', () => {
    // Validation is side-blind — no connection rule reads `port.side` — so
    // type compatibility refuses this for exactly the reason it always did.
    // Pinned anyway: the two ports have been on one edge and are now on two,
    // and neither arrangement is what decides this.
    const workbench = makeWorkbench();
    const agent = addNode(workbench, 'agent.llm');
    const tool = addNode(workbench, 'tool.web-search');
    const verdict = workbench.controller.edges.connect(
      { nodeId: tool.id, portId: 'tool' },
      { nodeId: agent.id, portId: 'skill' },
    );
    expect(verdict.ok).toBe(false);
  });

  it('and a markdown file still cannot be dropped into the tool bus', () => {
    const workbench = makeWorkbench();
    const agent = addNode(workbench, 'agent.llm');
    const markdown = addNode(workbench, 'input.markdown');
    const verdict = workbench.controller.edges.connect(
      { nodeId: markdown.id, portId: 'skill' },
      { nodeId: agent.id, portId: 'tools' },
    );
    expect(verdict.ok).toBe(false);
  });

  it('but the legitimate wire still connects', () => {
    const workbench = makeWorkbench();
    const agent = addNode(workbench, 'agent.llm');
    const markdown = addNode(workbench, 'input.markdown');
    const verdict = workbench.controller.edges.connect(
      { nodeId: markdown.id, portId: 'skill' },
      { nodeId: agent.id, portId: 'skill' },
    );
    expect(verdict.ok).toBe(true);
  });
});
