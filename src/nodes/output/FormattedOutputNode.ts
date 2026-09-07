import { Err, Ok, type Result } from '@core/kernel/Result';
import { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import { defineNode } from '@core/model/ModelRegistry';
import type { INodeDefinition } from '@core/model/contracts/node';
import {
  DISPLAY_KEY,
  type ExecutionContext,
  type INodeExecutor,
  type PortOutputs,
} from '@core/execution/INodeExecutor';
import { CATEGORY, PORT } from '../vocabulary';

const FIELD_FORMAT = 'format';

export type OutputFormat = 'markdown' | 'plain' | 'json';

export class FormattedOutputNodeModel extends AbstractNodeModel {
  get format(): OutputFormat {
    const value = this.getText(FIELD_FORMAT);
    return value === 'plain' || value === 'json' ? value : 'markdown';
  }
}

export const formattedOutputNode: INodeDefinition = defineNode(
  {
    id: 'output.formatted',
    category: CATEGORY.output,
    label: 'Formatted Output',
    description: 'Renders the result as Markdown.',
    iconId: 'node-output',
    accent: 'green',
    keywords: ['result', 'render', 'markdown', 'display', 'sink'],
    // Wider and taller than the input nodes: the rendered result is the point
    // of this node, and a three-column table wraps every cell at 252px. Height
    // then grows further from the measured content.
    defaultSize: { width: 320, height: 300 },
    fields: [
      {
        kind: 'select',
        key: FIELD_FORMAT,
        label: 'Format',
        // Inspector-only: the card is already showing the rendered result,
        // and a picker above it would crowd out the content.
        onCard: false,
        options: [
          { value: 'markdown', label: 'Markdown' },
          { value: 'plain', label: 'Plain text' },
          { value: 'json', label: 'JSON' },
        ],
        defaultValue: 'markdown',
      },
    ],
    ports: [
      {
        id: 'result',
        direction: 'in',
        type: PORT.result,
        label: 'result',
        required: true,
        description: 'The value to render.',
      },
    ],
  },
  FormattedOutputNodeModel,
);

export const formattedOutputExecutor: INodeExecutor = {
  id: formattedOutputNode.id,

  execute(ctx: ExecutionContext): Promise<Result<PortOutputs, string>> {
    const node = ctx.node as FormattedOutputNodeModel;
    const incoming = ctx.input<unknown>('result');

    if (incoming == null || incoming === '') {
      return Promise.resolve(Err('Nothing arrived on the result port'));
    }

    const rendered = format(incoming, node.format);
    ctx.log(`Rendered ${rendered.length} characters as ${node.format}`);

    // A sink has no output ports, so the rendered text is published under
    // the reserved display key for the card to show.
    return Promise.resolve(Ok({ [DISPLAY_KEY]: rendered }));
  },
};

function format(value: unknown, as: OutputFormat): string {
  if (as === 'json') {
    if (typeof value === 'string') {
      // Pretty-print a JSON string rather than quoting it again.
      try {
        return JSON.stringify(JSON.parse(value) as unknown, null, 2);
      } catch {
        return JSON.stringify(value, null, 2);
      }
    }
    return JSON.stringify(value, null, 2);
  }

  const text = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
  if (as === 'plain') {
    // Strip the Markdown that the model was asked to produce, rather than
    // rendering it — the user explicitly chose plain text.
    return text
      .replace(/^#{1,6}\s+/gm, '')
      .replace(/\*\*(.+?)\*\*/g, '$1')
      .replace(/[*_`]/g, '')
      .trim();
  }
  return text;
}
