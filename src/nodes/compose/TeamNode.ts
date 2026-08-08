import { Err, type Result } from '@core/kernel/Result';
import { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import { defineNode } from '@core/model/ModelRegistry';
import type { INodeDefinition } from '@core/model/contracts/node';
import type { ExecutionContext, INodeExecutor, PortOutputs } from '@core/execution/INodeExecutor';
import { CATEGORY, PORT } from '../vocabulary';

export const TEAM_TYPE = 'team.workflow';

const FIELD_WORKFLOW = 'workflow';
const FIELD_OUTCOME = 'outcome';

/**
 * A Team — a workflow that loops until it meets its outcome, mounted as one
 * node of this one (ticket 52, built by ticket 56).
 *
 * A Team *is* a subgraph reference: the same slug-as-data mechanism as
 * `workflow.subgraph`, compiled by the same backend path, with the same
 * isolation (the child sees a task, reports a result, and nothing else).
 * What earns it a distinct type is the contract it surfaces: a Team's card
 * states its **expected outcome** — the gist of the grader criteria that
 * close the child's loop — so the parent view answers "what does this box
 * achieve" without drilling in. The prebuilt team package
 * (`scripts/new_team.py`) ships supervisor + default worker + grader wired
 * into that loop, per the user's minimum-viable-prebuilt rule.
 *
 * Drill-in is the ordinary load path: open the referenced workflow from the
 * Workflows panel. A dedicated breadcrumb affordance is recorded on ticket
 * 56 as follow-up UX, not blocking the mechanism.
 */
export class TeamNodeModel extends AbstractNodeModel {
  /** The team package's slug, e.g. `research-team`. */
  get workflowSlug(): string {
    return this.getText(FIELD_WORKFLOW);
  }

  /** What the team is expected to deliver — display + documentation, the
   * enforcing copy lives in the child's grader criteria. */
  get outcome(): string {
    return this.getText(FIELD_OUTCOME);
  }
}

export const teamNode: INodeDefinition = defineNode(
  {
    id: TEAM_TYPE,
    category: CATEGORY.agent,
    label: 'Team',
    description: 'A workflow that loops until it meets its outcome, run as one step.',
    iconId: 'node-subgraph',
    accent: 'violet',
    keywords: ['team', 'crew', 'group', 'subgraph', 'workflow', 'loop', 'outcome'],
    defaultSize: { width: 252, height: 190 },
    fields: [
      {
        kind: 'text',
        key: FIELD_WORKFLOW,
        label: 'Team workflow slug',
        placeholder: 'e.g. research-team',
        defaultValue: '',
      },
      {
        kind: 'textarea',
        key: FIELD_OUTCOME,
        label: 'Expected outcome',
        placeholder: 'What this team must deliver — enforced by its grader.',
        defaultValue: '',
        onCard: true,
      },
    ],
    ports: [
      {
        id: 'input',
        direction: 'in',
        type: PORT.result,
        label: 'task',
        required: true,
        description: 'Becomes the team’s question — its entry point.',
      },
      {
        id: 'result',
        direction: 'out',
        type: PORT.result,
        label: 'outcome',
        description: 'The team’s final, grader-approved answer.',
      },
    ],
  },
  TeamNodeModel,
);

/** Same honest refusal as `workflow.subgraph`: the team's members, tools and
 * grader live behind the backend; Chat is the way to run it. */
export const teamExecutor: INodeExecutor = {
  id: TEAM_TYPE,
  execute(ctx: ExecutionContext): Promise<Result<PortOutputs, string>> {
    const node = ctx.node as TeamNodeModel;
    const slug = node.workflowSlug.trim();
    return Promise.resolve(
      Err(
        slug
          ? `The team "${slug}" runs on the backend — use Chat to run this workflow.`
          : 'This Team node has no workflow slug configured.',
      ),
    );
  },
};
