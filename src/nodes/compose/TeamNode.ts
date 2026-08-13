import { Err, type Result } from '@core/kernel/Result';
import { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import { defineNode } from '@core/model/ModelRegistry';
import type { INodeDefinition } from '@core/model/contracts/node';
import type { ExecutionContext, INodeExecutor, PortOutputs } from '@core/execution/INodeExecutor';
import { CATEGORY, PORT } from '../vocabulary';
import { OVERRIDES_FIELD } from './overridesField';

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
 * The card carries a second, *derived* line beneath that contract: a census
 * of the referenced document — "1 supervisor · 1 worker · 1 grader · 3 tools
 * — loops until its grader passes" — registered as a card body
 * (`view/nodes/CompositionBody`) and computed by the pure
 * `summarizeComposition`. It restores orientation without reopening the box:
 * a reader learns what the team costs and whether it loops, and still cannot
 * see or edit an atom inside it. Nothing is shown while the slug is unset;
 * an unresolvable slug says so plainly.
 *
 * Drill-in is the ordinary load path: open the referenced workflow from the
 * Workflows panel. A dedicated breadcrumb affordance is recorded on ticket
 * 56 as follow-up UX, not blocking the mechanism.
 */
export class TeamNodeModel extends AbstractNodeModel {
  /** The team package's slug, e.g. `sourcing-team`. */
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
    category: CATEGORY.compose,
    label: 'Team',
    // States what Team *adds*, rather than restating what Workflow already
    // is: the same mount, plus an outcome the card shows and a revision loop
    // read out of the child document. Deliberately not "parallel" or
    // "multi-agent" — the loop note is earned from the child's grader wiring,
    // and a grader-less document can be mounted here today (ticket 03).
    description:
      'The same isolated mount, plus a stated outcome — its card shows what the child is expected to deliver, and whether that child really loops until a grader passes.',
    // Its own glyph. One shared icon across two violet cards in one category
    // was the single visual channel available, spent on making them look
    // identical (ticket 02). A target, not a crowd: what distinguishes a Team
    // is the outcome it promises, not a headcount nothing verifies.
    iconId: 'node-team',
    accent: 'violet',
    keywords: ['team', 'crew', 'group', 'subgraph', 'workflow', 'loop', 'outcome'],
    defaultSize: { width: 252, height: 190 },
    fields: [
      {
        kind: 'text',
        key: FIELD_WORKFLOW,
        label: 'Team workflow slug',
        placeholder: 'e.g. sourcing-team',
        defaultValue: '',
      },
      {
        kind: 'textarea',
        key: FIELD_OUTCOME,
        label: 'Expected outcome (documentation)',
        // The placeholder said "enforced by its grader", which is the defect
        // rather than a description of it: this value never reaches the
        // compiler — `_subgraph` reads `workflow` and `overrides` and nothing
        // else — so a user wrote a constraint, reasonably believed it bound
        // the run, and got no signal that it did not. The RouterNode lesson in
        // a different field: a surface presenting a machine-owned promise as
        // if it were configuration (ticket 03).
        placeholder: 'What this team is expected to deliver, in your words.',
        hint: 'Shown on the card so a reader knows what this box is for. It does not constrain the run — enforcement lives in the child workflow’s own grader criteria, and the card says so when that grader is missing or never revises.',
        defaultValue: '',
        onCard: true,
      },
      OVERRIDES_FIELD,
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
