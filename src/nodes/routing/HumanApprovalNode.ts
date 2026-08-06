import { Err, type Result } from '@core/kernel/Result';
import { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import { defineNode } from '@core/model/ModelRegistry';
import type { INodeDefinition } from '@core/model/contracts/node';
import type {
  ExecutionContext,
  INodeExecutor,
  PortOutputs,
} from '@core/execution/INodeExecutor';
import { CATEGORY, PORT } from '../vocabulary';

export const HUMAN_APPROVAL_TYPE = 'human.approval';

const FIELD_MESSAGE = 'message';

export class HumanApprovalNodeModel extends AbstractNodeModel {
  get message(): string {
    return this.getText(FIELD_MESSAGE) || 'Approve this result?';
  }
}

/**
 * Pauses a run for a human decision, then dispatches on it — same
 * node-decides/edge-dispatches split as the Router and the Grader, the
 * difference being *who* decides: a human, resumed via LangGraph's
 * `Command(resume=...)`, instead of an LLM's own judgement.
 *
 * Compiles to `interrupt()` plus a conditional edge (`workflow_compiler.py`'s
 * `HUMAN_APPROVAL_TYPE` branch). Like the Grader and the Router, this node
 * cannot run in the browser preview — a paused graph needs a checkpointer and
 * a resume call only the backend can provide.
 */
export const humanApprovalNode: INodeDefinition = defineNode(
  {
    id: HUMAN_APPROVAL_TYPE,
    category: CATEGORY.agent,
    label: 'Human approval',
    description: 'Pauses the run and waits for a person to approve or reject the candidate.',
    iconId: 'node-human-approval',
    accent: 'amber',
    keywords: ['approve', 'human', 'review', 'pause', 'interrupt', 'gate'],
    defaultSize: { width: 268, height: 180 },
    fields: [
      {
        kind: 'textarea',
        key: FIELD_MESSAGE,
        label: 'Prompt shown to the reviewer',
        placeholder: 'OK to publish?',
        defaultValue: '',
        minRows: 2,
      },
    ],
    ports: [
      {
        id: 'candidate',
        direction: 'in',
        type: PORT.result,
        label: 'candidate',
        description: 'The answer to review.',
      },
      {
        id: 'approved',
        direction: 'out',
        type: PORT.result,
        label: 'approved',
        description: 'Taken when the reviewer approves.',
      },
      {
        id: 'rejected',
        direction: 'out',
        type: PORT.feedback,
        label: 'rejected',
        description: 'Taken when the reviewer rejects, optionally carrying feedback.',
      },
    ],
  },
  HumanApprovalNodeModel,
);

/**
 * Browser-preview executor — refuses, like the Router's and the Grader's.
 *
 * Exists rather than being omitted because a `standard` node with no
 * registered executor is silently skipped by the preview engine, which
 * would make an unreviewed run look like it had been reviewed.
 */
export const humanApprovalExecutor: INodeExecutor = {
  id: humanApprovalNode.id,
  execute(ctx: ExecutionContext): Promise<Result<PortOutputs, string>> {
    ctx.log('Human approval pauses the real LangGraph run and needs a checkpointer.');
    return Promise.resolve(
      Err(
        'This node pauses the run via `interrupt()` and resumes via `Command(resume=...)` ' +
          'on the Python runtime. Use the Chat panel against the backend, not the canvas preview.',
      ),
    );
  },
};
