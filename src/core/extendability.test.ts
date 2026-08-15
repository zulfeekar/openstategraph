/**
 * "Extend by registering, never by editing the engine" — walked, not asserted.
 *
 * CLAUDE.md's **O**: "Every extension point is a `Registry<T>`: node types,
 * executors, providers, connection rules, validation rules… A new capability
 * must not require touching `core/`." That is the kind of claim that stays
 * true in prose long after it has stopped being true in code — `f738e3e`
 * ("A new node family had to edit core/") is this repository's own precedent.
 *
 * So this file is a **walk**: it builds a `Workbench` exactly as the app does,
 * then adds one node type, one tool and one provider that no shipped module
 * knows about, and checks each one reaches the surfaces a real capability has
 * to reach — palette, serialisation, executor lookup, connection rules. The
 * imports above are the assertion that matters: nothing here imports from a
 * `core/` module it had to modify, and adding these three took no edit to any
 * file under `src/core/`.
 *
 * **Deliberately the editor half only** — but the compiler half now holds too.
 * When this walk was written it did not: `NodeRuntime._builders` was a private
 * dict literal, not a registry, so a node *family* the compiler had never
 * heard of compiled to `_passthrough` — it ran and did nothing. Install-
 * experience ticket 08 made contributed families the
 * `openstategraph.node_families` entry-point group, with the built-in table
 * un-shadowable; that half is walked in `backend/tests/test_node_families.py`,
 * and `backend/tests/test_production_audit_2026_08_15.py` keeps pinning the
 * case nothing implements, which still reports itself rather than forwarding.
 */
import { describe, expect, it } from 'vitest';
import { Workbench } from '@app/Workbench';
import { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import type { INodeDefinition } from '@core/model/contracts/node';
import type { INodeExecutor } from '@core/execution/INodeExecutor';
import { Ok, type Result } from '@core/kernel/Result';
import {
  AbstractLLMProvider,
  type CompletionResult,
  type ModelDescriptor,
  ZERO_USAGE,
} from '@core/providers/ILLMProvider';

/** A concrete node model, supplied by the extender — the ladder's last rung. */
class SentimentNode extends AbstractNodeModel {}

const sentimentNode: INodeDefinition = {
  id: 'analyse.sentiment',
  kind: 'standard',
  category: 'routing',
  label: 'Sentiment',
  description: 'A third-party node type, added without touching core/.',
  iconId: 'node-text-input',
  accent: 'violet',
  fields: [{ kind: 'text', key: 'rules', label: 'Rules', defaultValue: '' }],
  defaultSize: { width: 200, height: 100 },
  ports: () => [
    { id: 'prompt', direction: 'in', type: 'text', label: 'in' },
    { id: 'result', direction: 'out', type: 'result', label: 'out' },
  ],
  create: (init) => new SentimentNode(sentimentNode, init),
};

const sentimentExecutor: INodeExecutor = {
  id: 'analyse.sentiment',
  async execute() {
    return Ok({ text: 'positive' });
  },
};

describe('a new node type lands by registration only', () => {
  it('reaches the palette, the serializer and the executor lookup', () => {
    const workbench = new Workbench();
    const before = workbench.registry.nodeTypes.list().length;

    workbench.registry.nodeTypes.register(sentimentNode);
    workbench.engine.executors.register(sentimentExecutor);

    expect(workbench.registry.nodeTypes.list().length).toBe(before + 1);

    const node = workbench.registry.nodeTypes
      .require('analyse.sentiment')
      .create({ position: { x: 0, y: 0 } });
    workbench.controller.model.addNode(node);

    expect(workbench.registry.nodeTypes.list().some((d) => d.id === 'analyse.sentiment')).toBe(
      true,
    );
    expect(
      workbench.controller.model.toJSON().nodes.some((n) => n.type === 'analyse.sentiment'),
    ).toBe(true);
    expect(workbench.engine.executors.get('analyse.sentiment')).toBeDefined();
  });

  it('is not reported as an unknown type by the workflow validator', () => {
    const workbench = new Workbench();
    workbench.registry.nodeTypes.register(sentimentNode);
    workbench.engine.executors.register(sentimentExecutor);
    workbench.controller.model.addNode(
      workbench.registry.nodeTypes
        .require('analyse.sentiment')
        .create({ position: { x: 0, y: 0 } }),
    );

    // The rule that would fire if registration were not enough.
    expect(workbench.workflowValidator.validate().some((d) => d.code === 'unknown-node-type')).toBe(
      false,
    );
  });
});

describe('a new tool lands by registration only', () => {
  it('is drawable onto a shipped agent without editing a connection rule', () => {
    const workbench = new Workbench();
    const toolNode: INodeDefinition = {
      ...sentimentNode,
      id: 'tool.weather',
      label: 'Weather',
      ports: () => [{ id: 'tool', direction: 'out', type: 'tool', label: 'tool' }],
      create: (init) => new SentimentNode(toolNode, init),
    };
    workbench.registry.nodeTypes.register(toolNode);
    workbench.engine.executors.register({
      id: 'tool.weather',
      async execute() {
        return Ok({ text: 'sunny' });
      },
    });

    const agent = workbench.registry.nodeTypes
      .require('agent.llm')
      .create({ position: { x: 0, y: 0 } });
    const tool = workbench.registry.nodeTypes
      .require('tool.weather')
      .create({ position: { x: 0, y: 200 } });
    workbench.controller.model.addNode(agent);
    workbench.controller.model.addNode(tool);

    // The `tools` bus takes many links and is typed, so a brand-new tool is
    // accepted by the *type*, never by a list of known tool ids.
    const verdict = workbench.connectionValidator.validate(
      { nodeId: tool.id, portId: 'tool' },
      { nodeId: agent.id, portId: 'tools' },
    );
    expect(verdict.ok).toBe(true);
  });
});

describe('a new provider lands by registration only', () => {
  it('joins the registry the model picker reads', () => {
    const workbench = new Workbench();
    // Every abstract member supplied, nothing cast away: the ladder's contract
    // is what a third party has to satisfy, so the walk has to satisfy it too.
    class AcmeProvider extends AbstractLLMProvider {
      readonly id = 'acme';
      readonly label = 'Acme';
      readonly requiresApiKey = false;
      readonly models: readonly ModelDescriptor[] = [
        {
          id: 'acme:big',
          label: 'Acme Big',
          providerId: 'acme',
          contextWindow: 128_000,
          maxOutputTokens: 4_096,
          supportsTools: true,
        },
      ];
      async complete(): Promise<Result<CompletionResult, string>> {
        return Ok({
          text: 'hi',
          toolCalls: [],
          usage: ZERO_USAGE,
          stopReason: 'end_turn',
        });
      }
    }
    const before = workbench.providers.list().length;
    workbench.providers.register(new AcmeProvider());

    expect(workbench.providers.list().length).toBe(before + 1);
    expect(workbench.providers.get('acme')).toBeDefined();
  });
});
