import { Err, type Result } from '@core/kernel/Result';
import { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import { defineNode } from '@core/model/ModelRegistry';
import type { INodeDefinition } from '@core/model/contracts/node';
import type { ExecutionContext, INodeExecutor, PortOutputs } from '@core/execution/INodeExecutor';
import { CATEGORY, PORT } from '../vocabulary';
import { OVERRIDES_FIELD } from './overridesField';

export const SUBGRAPH_TYPE = 'workflow.subgraph';

const FIELD_WORKFLOW = 'workflow';

/**
 * Another workflow, run as one node of this one — ticket 34.
 *
 * This is the composition mechanism CLAUDE.md's vocabulary promises
 * ("workflow composition = subgraphs"): the backend compiles the referenced
 * workflow's own document and invokes it with an explicit state mapping —
 * this node's input text becomes the child's question, and only the child's
 * final answer flows back out. The child never sees this workflow's other
 * state, mirroring the subagent-isolation rule: it receives a task and
 * reports a result.
 *
 * The reference is the child's **slug** — data, never code — so the document
 * stays serialisable and vendor-neutral. Because the slug is all the card
 * would otherwise show, a registered card body
 * (`view/nodes/CompositionBody`) annotates it with a census of the
 * referenced document — node-type counts in the palette's own vocabulary,
 * derived by the pure `summarizeComposition`. Unlike a Team's, this one
 * never claims a loop: a plain mount promises no outcome. A workflow that (transitively)
 * includes itself is refused by the compiler at build time with the chain
 * spelled out.
 */
export class SubgraphNodeModel extends AbstractNodeModel {
  /** The referenced workflow's slug, e.g. `chinook-assistant`. */
  get workflowSlug(): string {
    return this.getText(FIELD_WORKFLOW);
  }
}

export const subgraphNode: INodeDefinition = defineNode(
  {
    id: SUBGRAPH_TYPE,
    category: CATEGORY.compose,
    label: 'Workflow',
    // Isolation is the thing a reader cannot guess and the thing that decides
    // whether this is the right node: the child sees a task and reports a
    // result, never this graph's state, messages or tools. "Runs another
    // workflow as a single step" said none of that (ticket 02).
    description:
      'Another workflow, run as one isolated step — task in, answer out. It brings its own state, tools and knowledge, and by reference: change the original and every mount of it changes.',
    iconId: 'node-subgraph',
    accent: 'violet',
    keywords: ['subgraph', 'workflow', 'compose', 'nest', 'call', 'reuse'],
    defaultSize: { width: 252, height: 150 },
    fields: [
      {
        kind: 'text',
        key: FIELD_WORKFLOW,
        label: 'Workflow slug',
        placeholder: 'e.g. chinook-assistant',
        defaultValue: '',
      },
      OVERRIDES_FIELD,
    ],
    ports: [
      {
        id: 'input',
        direction: 'in',
        type: PORT.result,
        label: 'input',
        required: true,
        description: 'Becomes the child workflow’s question.',
      },
      {
        id: 'result',
        direction: 'out',
        type: PORT.result,
        label: 'result',
        description: 'The child workflow’s final answer.',
      },
    ],
  },
  SubgraphNodeModel,
);

/**
 * Refuses honestly in the browser preview: a child workflow's tools and
 * models live behind the backend, and pretending to run it here would
 * produce exactly the plausible-but-empty result this codebase treats as
 * worse than an error. Same stance as Orchestrator/Worker.
 */
export const subgraphExecutor: INodeExecutor = {
  id: SUBGRAPH_TYPE,

  async execute(ctx: ExecutionContext): Promise<Result<PortOutputs, string>> {
    const node = ctx.node as SubgraphNodeModel;
    const target = node.workflowSlug.trim() || '(none selected)';
    return Err(
      `The Workflow node runs "${target}" on the backend — use Chat to execute this graph.`,
    );
  },
};
