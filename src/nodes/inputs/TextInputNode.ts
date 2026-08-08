import { Ok, type Result } from '@core/kernel/Result';
import { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import { defineNode } from '@core/model/ModelRegistry';
import type { INodeDefinition } from '@core/model/contracts/node';
import type { ExecutionContext, INodeExecutor, PortOutputs } from '@core/execution/INodeExecutor';
import { CATEGORY, PORT } from '../vocabulary';

export const TEXT_INPUT_TYPE = 'input.text';

const FIELD_PROMPT = 'prompt';

/**
 * The starting prompt for a run.
 *
 * Keeps the type description as its subtitle rather than echoing the prompt:
 * the prompt is already the largest thing on the card, and repeating it in the
 * header just crowds the title.
 */
export class TextInputNodeModel extends AbstractNodeModel {
  get prompt(): string {
    return this.getText(FIELD_PROMPT);
  }
}

export const textInputNode: INodeDefinition = defineNode(
  {
    id: TEXT_INPUT_TYPE,
    category: CATEGORY.inputs,
    label: 'Text Input',
    description: 'The starting prompt for the flow.',
    iconId: 'node-text-input',
    accent: 'amber',
    keywords: ['prompt', 'question', 'query', 'user'],
    defaultSize: { width: 252, height: 176 },
    fields: [
      {
        kind: 'textarea',
        key: FIELD_PROMPT,
        label: 'Prompt',
        placeholder: 'What should the agent do?',
        defaultValue: '',
        minRows: 3,
        validate: (value) => (value.trim().length === 0 ? 'Enter a prompt for the agent' : null),
      },
    ],
    ports: [
      {
        id: 'text',
        direction: 'out',
        type: PORT.text,
        label: 'text',
        description: 'The prompt text, sent downstream verbatim.',
      },
    ],
  },
  TextInputNodeModel,
);

export const textInputExecutor: INodeExecutor = {
  id: textInputNode.id,
  execute(ctx: ExecutionContext): Promise<Result<PortOutputs, string>> {
    const node = ctx.node as TextInputNodeModel;
    const prompt = node.prompt.trim();
    ctx.log(`Sending ${prompt.length} characters downstream`);
    return Promise.resolve(Ok({ text: prompt }));
  },
};
