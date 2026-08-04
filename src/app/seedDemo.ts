import { EdgeModel } from '@core/model/EdgeModel';
import type { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import type { NodeInit } from '@core/model/contracts/node';
import type { Workbench } from './Workbench';
import { NODE_TYPE } from '@nodes/index';

/**
 * The workflow the editor opens with.
 *
 * Reproduces the reference layout: two inputs feeding an agent that sits
 * inside a titled setup frame, a Reddit tool wired to the agent's tool bus,
 * and a formatted output node rendering the result.
 *
 * Built by writing straight to the model rather than through commands, so
 * opening the app leaves an empty undo stack — the first Cmd-Z a user presses
 * should undo *their* first edit, not dismantle the example. It runs
 * end-to-end against the mock provider with no credentials.
 */
export function seedDemoWorkflow(workbench: Workbench): void {
  const { model, registry } = workbench;

  const create = (typeId: string, init: NodeInit): AbstractNodeModel => {
    const definition = registry.nodeTypes.require(typeId);
    const node = definition.create(init) as AbstractNodeModel;
    model.addNode(node);
    return node;
  };

  model.transact(() => {
    const textInput = create(NODE_TYPE.textInput, {
      position: { x: 40, y: 200 },
      data: {
        prompt: 'Give me the most trending topics in the React community on Reddit.',
      },
    });

    const skill = create(NODE_TYPE.markdownFile, {
      position: { x: 40, y: 480 },
      data: {
        filename: 'agent-skill.md',
        instruction:
          'You are a senior React analyst. Summarise the findings as a clean Markdown table.',
      },
    });

    // The frame is created before the agent so it renders behind it, and is
    // sized to leave room for its notes above the embedded card: 340 wide
    // gives the 252px card an even 44px gutter each side.
    const group = create(NODE_TYPE.group, {
      position: { x: 400, y: 20 },
      size: { width: 340, height: 470 },
      data: {
        title: '🤖 AI agent setup',
        notes: [
          '1. **Choose a model**',
          '2. **Set token budget**',
          '3. **Connect prompt & skill**',
          '4. **Add agent tools**',
          '5. **Run & view result**',
          '',
          '💡 Tip: runs with mock data by default — add your Anthropic or OpenAI key to use a real LLM.',
        ].join('\n'),
      },
    });

    // Sits below the frame's notes, which need roughly 240px for the title
    // plus the six-step list.
    const agent = create(NODE_TYPE.agent, {
      position: { x: 444, y: 260 },
    });
    model.setNodeParent(agent.id, group.id);

    const tool = create(NODE_TYPE.redditSearch, {
      position: { x: 444, y: 570 },
      data: { subreddit: 'reactjs', topicLimit: 10 },
    });

    const output = create(NODE_TYPE.formattedOutput, {
      position: { x: 810, y: 250 },
    });

    // Wired directly rather than through `controller.connect`: the seed is
    // known-valid, and going through commands would fill the undo stack.
    const connect = (
      source: AbstractNodeModel,
      sourcePort: string,
      target: AbstractNodeModel,
      targetPort: string,
    ) => {
      model.addEdge(
        new EdgeModel({
          source: { nodeId: source.id, portId: sourcePort },
          target: { nodeId: target.id, portId: targetPort },
        }),
      );
    };

    connect(textInput, 'text', agent, 'prompt');
    connect(skill, 'skill', agent, 'skill');
    connect(tool, 'tool', agent, 'tools');
    connect(agent, 'result', output, 'result');

    model.setName('React trend report');
  });
}
