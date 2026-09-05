import { Err, type Result } from '@core/kernel/Result';
import { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import { defineNode } from '@core/model/ModelRegistry';
import type { NodeData } from '@core/model/contracts/fields';
import type { INodeDefinition } from '@core/model/contracts/node';
import type { IPortDescriptor } from '@core/model/contracts/ports';
import type { ExecutionContext, INodeExecutor, PortOutputs } from '@core/execution/INodeExecutor';
import { CATEGORY, PORT } from '../vocabulary';
import { type BranchEntry, MAX_BRANCHES, branchesOf } from './RouterNode';

export const ROUTE_CHECK_TYPE = 'route.check';

const FIELD_CHECK = 'check';
const FIELD_BRANCHES = 'branches';

/**
 * The port a name nothing declares takes.
 *
 * A **static** port, which is the one place this branch table differs from a
 * classifier's. A classifier's `fallback` is a *field naming one of its own
 * branches*, because the fallback is something the model must be told about —
 * it is a sentence in the composed prompt. There is no prompt here and nobody
 * to tell, so the honest shape is a port that always exists: a developer sees
 * on the canvas where an unrecognised answer goes, instead of discovering it
 * in the compiler's first-destination default.
 */
export const FALLBACK_PORT = 'fallback';

const DEFAULT_BRANCHES: BranchEntry[] = [
  { id: 'b1', name: 'ask_back' },
  { id: 'b2', name: 'answer' },
];

export class RouteCheckNodeModel extends AbstractNodeModel {
  /** The package function this fork runs, e.g. `needs_a_date_range`. */
  get check(): string {
    return this.getText(FIELD_CHECK);
  }

  /** The branch table, read through the classifier's own migration-tolerant reader. */
  get branches(): readonly BranchEntry[] {
    return branchesOf(this.data, DEFAULT_BRANCHES);
  }

  override get subtitle(): string {
    const check = this.check.trim();
    return check ? `checks: ${check}` : 'No check named yet.';
  }
}

/**
 * `route.classifier`'s mechanical sibling (`osg-agent-experience` 42).
 *
 * ## What it is for
 *
 * The owner's rule is that a question naming no date range is asked back
 * rather than answered on an assumed window, and a workflow already had the
 * fact for free — a `resolve.vocabulary` reports the range as uncovered
 * without calling anybody. Nothing could turn that fact into a route to an
 * output. `guard.check` routes `pass`/`revise`, but `revise` is a `feedback`
 * port and an `output.formatted` takes `result`; a Router can name an
 * `ask_back` branch, but a **model** picks it, and on the first live run it
 * picked a data branch and never asked. A deterministic fact was demoted to a
 * model's judgement because no node carried it.
 *
 * ## Why a sibling rather than a flag on either neighbour
 *
 * - Not a mode of `route.classifier`: that node's substance is a composed
 *   prompt — preamble, branch list, the developer's rules, a locked output
 *   contract. A "no model" switch would make every one of those fields dead
 *   configuration on half the instances, which is the Interface-Segregation
 *   failure `CLAUDE.md` names.
 * - Not a mode of `guard.check`: its outputs would change **kind** with
 *   configuration — two ports typed `result`/`feedback` on one setting, n
 *   ports typed `result` on another. Cardinality belongs to the port; a
 *   port's *type* does not vary at runtime at all.
 *
 * What the two checks genuinely share — resolve `function.<name>`, call it,
 * turn a raised exception into data — is a collaborator on the Python side
 * (`compile/nodes/named_check.py`), never a common ancestor.
 *
 * ## Every way out is `result`-typed, and that is the whole ticket
 *
 * A grader's and a guard's `revise` is `feedback`, which only a node
 * declaring a `feedback` input accepts. That is right for a loop and it is
 * exactly what an ask-back cannot use, because the thing an ask-back wants
 * downstream is an output. Here every branch carries the same `result` a
 * function or an agent emits.
 *
 * Compiles to `add_conditional_edges` in the Python runtime
 * (`compile/nodes/route_check.py`), never to a model call.
 */
export const routeCheckNode: INodeDefinition = defineNode(
  {
    id: ROUTE_CHECK_TYPE,
    category: CATEGORY.agent,
    label: 'Check router',
    description:
      'Runs a package function against the candidate and takes the branch it names. No model.',
    iconId: 'node-router',
    accent: 'green',
    keywords: [
      'route',
      'check',
      'branch',
      'deterministic',
      'function',
      'switch',
      'ask back',
      'fork',
    ],
    defaultSize: { width: 268, height: 210 },
    fields: [
      {
        kind: 'text',
        key: FIELD_CHECK,
        label: 'Check',
        placeholder: 'needs_a_date_range',
        hint:
          'The package function to run, named the way `function.<name>` names it — this ' +
          'node calls that same function, not a model. It returns the name of one of the ' +
          'branches below; anything else, including nothing at all, takes the fallback. ' +
          'A branch’s own id is accepted as well as its name, and case and surrounding ' +
          'space are forgiven.',
        defaultValue: '',
        onCard: true,
      },
      {
        kind: 'repeatable-group',
        key: FIELD_BRANCHES,
        label: 'Branches',
        defaultValue: DEFAULT_BRANCHES,
        addLabel: 'Add branch',
        maxRows: MAX_BRANCHES,
        fields: [
          {
            kind: 'text',
            key: 'name',
            label: 'Branch name',
            placeholder: 'e.g. ask_back',
            defaultValue: '',
            validate: (value) => (value.trim() ? null : 'Name required'),
          },
        ],
        // Each entry becomes an output port, so this field is what shapes the node.
        validate: (value) => {
          if (!Array.isArray(value) || value.length === 0) return 'Add at least one branch';
          return null;
        },
      },
    ],
    ports: (data: Readonly<NodeData>): IPortDescriptor[] => {
      const inputs: IPortDescriptor[] = [
        {
          id: 'candidate',
          direction: 'in',
          type: PORT.result,
          label: 'candidate',
          description: 'The value the check reads.',
        },
      ];

      // Declaration order is preserved, because the order the user typed the
      // branches in is the order they expect to see them down the card. The
      // port id uses the stable `id`, not the name, so a rename keeps its edge
      // — the classifier's own reader is reused rather than copied.
      const outputs = branchesOf(data, DEFAULT_BRANCHES).map((entry): IPortDescriptor => ({
        id: `branch:${entry.id}`,
        direction: 'out',
        type: PORT.result,
        label: entry.name,
        // One way out per branch. `maxConnections` is derived from this
        // rather than written beside it (`osg-agent-experience` 38): the
        // compiled plan keys a conditional destination by branch, so a
        // second edge would replace the first with nothing to report it.
        branch: true,
        description: `Taken when the check returns "${entry.name}".`,
      }));

      return [
        ...inputs,
        ...outputs,
        {
          id: FALLBACK_PORT,
          direction: 'out',
          type: PORT.result,
          label: 'fallback',
          branch: true,
          description:
            'Taken when the check returns a name no branch declares, returns nothing, or ' +
            'raises. Left unwired, the run takes the first branch instead and says so.',
        },
      ];
    },
  },
  RouteCheckNodeModel,
);

/**
 * Browser-preview executor — refuses, like the Router's and the Guard's.
 *
 * The fork compiles to a LangGraph conditional edge evaluated by the Python
 * runtime, and a `standard` node with no registered executor is *silently
 * skipped* in preview — which would make an unrouted run look successful.
 */
export const routeCheckExecutor: INodeExecutor = {
  id: ROUTE_CHECK_TYPE,
  execute(ctx: ExecutionContext): Promise<Result<PortOutputs, string>> {
    ctx.log('The check runs in the Python runtime, not the browser preview.');
    return Promise.resolve(
      Err(
        'This Check router compiles to a LangGraph conditional edge and calls a package ' +
          'function in the Python runtime. Use “Run” against the backend to evaluate it.',
      ),
    );
  },
};
