import { Ok, type Result } from '@core/kernel/Result';
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

const FIELD_TEXT = 'text';

export const STATIC_OUTPUT_TYPE = 'output.static';

/**
 * An exit that prints a sentence you wrote, whatever reached it.
 *
 * `osg-agent-experience/55`. Its sibling `output.formatted` prints what
 * reaches it and has no text field, and that stays true: a `text` on *that*
 * node has two possible readings and neither serves the case that asked for
 * it — a fallback (`text` only when nothing arrives) never fires on an
 * ask-back branch, which always carries the user's own question, and an
 * override (`text` wins) lets a typed field silently discard a run's answer
 * at the one node where "the run's answer" is defined.
 *
 * Two node types have neither problem, because the ambiguity has nowhere to
 * live, and a reader can see which behaviour is in force from the canvas
 * rather than from a field's precedence rule.
 */
export class StaticOutputNodeModel extends AbstractNodeModel {
  get text(): string {
    return this.getText(FIELD_TEXT).trim();
  }
}

export const staticOutputNode: INodeDefinition = defineNode(
  {
    id: STATIC_OUTPUT_TYPE,
    category: CATEGORY.output,
    label: 'Static Output',
    description: 'Prints a sentence you write — for a branch that must say something.',
    iconId: 'node-output',
    accent: 'green',
    keywords: ['static', 'fixed', 'ask back', 'message', 'sink', 'reply'],
    defaultSize: { width: 252, height: 232 },
    fields: [
      {
        kind: 'textarea',
        key: FIELD_TEXT,
        label: 'Text',
        placeholder: 'What should this branch say?',
        defaultValue: '',
        minRows: 3,
        maxRows: 12,
      },
    ],
    ports: [
      {
        id: 'when',
        direction: 'in',
        type: PORT.result,
        label: 'when',
        // Required, and that is the cardinality question answered rather than
        // dodged: the port is not the sentence, it is how a branch *reaches*
        // this exit. A static output nothing wires to is never scheduled, so
        // it is not a reply — it is dead text on the canvas.
        required: true,
        // Many, unlike the sink beside it. Two branches that both end in
        // "ask the user to name a window" are one reply, and forcing a second
        // copy of the sentence to say so would be the duplication the node
        // exists to remove.
        maxConnections: null,
        description: 'Wired so a branch can end here. Its value is not printed.',
      },
    ],
  },
  StaticOutputNodeModel,
);

export const staticOutputExecutor: INodeExecutor = {
  id: STATIC_OUTPUT_TYPE,

  execute(ctx: ExecutionContext): Promise<Result<PortOutputs, string>> {
    const node = ctx.node as StaticOutputNodeModel;
    // Deliberately never reads `when`. The compiler's builder does not either,
    // and an executor that quietly preferred an arriving value would put the
    // two-semantics defect back one layer down, where nothing looks for it.
    const text = node.text;
    ctx.log(text.length > 0 ? `Printed ${text.length} characters` : 'No text set');
    return Promise.resolve(Ok({ [DISPLAY_KEY]: text }));
  },
};
