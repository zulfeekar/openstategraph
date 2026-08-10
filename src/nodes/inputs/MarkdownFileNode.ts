import { Ok, type Result } from '@core/kernel/Result';
import { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import { defineNode } from '@core/model/ModelRegistry';
import type { INodeDefinition } from '@core/model/contracts/node';
import { BINDING_SIDE } from '@core/model/contracts/ports';
import type { ExecutionContext, INodeExecutor, PortOutputs } from '@core/execution/INodeExecutor';
import { CATEGORY, PORT } from '../vocabulary';

const FIELD_FILENAME = 'filename';
const FIELD_CONTENT = 'content';
const FIELD_INSTRUCTION = 'instruction';

/**
 * A Markdown instruction file — the agent's skill.
 *
 * Carries two related fields: the picked file's name and content, plus an
 * editable instruction. The instruction wins when present, so a user can
 * load a file and then tweak it without the edit being silently discarded
 * on the next run.
 */
export class MarkdownFileNodeModel extends AbstractNodeModel {
  get filename(): string {
    return this.getText(FIELD_FILENAME);
  }

  get instruction(): string {
    const inline = this.getText(FIELD_INSTRUCTION).trim();
    return inline.length > 0 ? inline : this.getText(FIELD_CONTENT).trim();
  }
}

export const markdownFileNode: INodeDefinition = defineNode(
  {
    id: 'input.markdown',
    category: CATEGORY.inputs,
    label: 'Markdown File',
    description: 'A Markdown instruction file for the agent.',
    iconId: 'node-markdown',
    accent: 'orange',
    keywords: ['skill', 'system', 'instruction', 'md', 'file', 'persona'],
    defaultSize: { width: 252, height: 232 },
    fields: [
      {
        kind: 'file',
        key: FIELD_FILENAME,
        label: 'Markdown file',
        accept: '.md,.markdown,.txt',
        contentKey: FIELD_CONTENT,
        actionLabel: 'Replace',
        defaultValue: 'agent-skill.md',
      },
      {
        kind: 'textarea',
        key: FIELD_INSTRUCTION,
        label: 'Instruction',
        placeholder: 'How should the agent behave?',
        defaultValue: '',
        minRows: 3,
      },
    ],
    ports: [
      {
        id: 'skill',
        direction: 'out',
        type: PORT.skill,
        label: 'skill',
        // A skill is *bound* to an agent, not a stage in the flow — so it
        // leaves across the reading axis, exactly like a tool does. It had
        // drifted onto the flow-output side, which made a binding look like
        // a step.
        side: BINDING_SIDE.provider,
        description: 'Becomes the agent’s system instruction.',
      },
    ],
  },
  MarkdownFileNodeModel,
);

export const markdownFileExecutor: INodeExecutor = {
  id: markdownFileNode.id,
  execute(ctx: ExecutionContext): Promise<Result<PortOutputs, string>> {
    const node = ctx.node as MarkdownFileNodeModel;
    const instruction = node.instruction;
    ctx.log(
      instruction.length > 0
        ? `Loaded skill from ${node.filename || 'inline instruction'}`
        : 'No instruction set — the agent will run without a skill',
    );
    return Promise.resolve(Ok({ skill: instruction }));
  },
};
