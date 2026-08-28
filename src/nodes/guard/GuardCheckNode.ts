import { Err, type Result } from '@core/kernel/Result';
import { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import { defineNode } from '@core/model/ModelRegistry';
import type { INodeDefinition } from '@core/model/contracts/node';
import type { ExecutionContext, INodeExecutor, PortOutputs } from '@core/execution/INodeExecutor';
import { CATEGORY, PORT } from '../vocabulary';

export const GUARD_CHECK_TYPE = 'guard.check';

const FIELD_CHECK = 'check';
const FIELD_MAX_ATTEMPTS = 'maxAttempts';

export class GuardCheckNodeModel extends AbstractNodeModel {
  /** The package function this check runs, e.g. `validate_sql` for `function.validate_sql`. */
  get check(): string {
    return this.getText(FIELD_CHECK);
  }

  override get subtitle(): string {
    const check = this.check.trim();
    return check ? `checks: ${check}` : 'No check named yet.';
  }
}

/**
 * `route.grader`'s mechanical sibling (`launch-readiness` 65): answers the
 * same `pass`/`revise` question a grader does, but by calling a package
 * function instead of a model.
 *
 * ## Why a sibling family, not a widened `function.*` node
 *
 * `function.*` emits `result` — a transform, one output, no branch. Making a
 * function node sometimes emit `feedback` would mean two different port
 * shapes for one type depending on configuration, which is exactly what
 * "cardinality belongs to the port, not the node" (`CLAUDE.md`) forbids for a
 * node whose *kind* of output changes rather than its cardinality. A grader
 * and a guard answer the same question — one by judgement, one by
 * computation — so `CLAUDE.md`'s families rule makes that a sibling under a
 * shared port shape, not a flag on `function.*`.
 *
 * ## The type gate is untouched
 *
 * `revise` is `PORT.feedback`, the same port type a grader's `revise`
 * already declares, and `acyclicRule` (`src/core/validation/ConnectionValidator.ts`)
 * gates on **port type**, not on node type — so this node closes a loop
 * exactly the way a grader does, and an accidental cycle stays exactly as
 * inexpressible as it was before this type existed. No change to `core/`.
 *
 * ## Termination
 *
 * Same two ceilings as a grader: `maxAttempts` (this node's own lap budget)
 * and the step-budget floor (`compile/node_runtime.py`'s
 * `step_budget_floor_for`), both forcing a `pass` rather than looping
 * forever — a guard that always emitted `revise` would violate "a cycle must
 * contain a conditional edge that can end it", so both ceilings apply here
 * exactly as they do on `route.grader`.
 *
 * Compiles to a conditional edge in the Python runtime
 * (`compile/node_runtime.py`'s `_guard_check`), never to a model call.
 */
export const guardCheckNode: INodeDefinition = defineNode(
  {
    id: GUARD_CHECK_TYPE,
    category: CATEGORY.agent,
    label: 'Guard',
    description: 'Runs a package function against the candidate and routes pass/revise. No model.',
    iconId: 'node-guardrail',
    accent: 'green',
    keywords: ['guard', 'check', 'validate', 'deterministic', 'verify', 'function', 'grade'],
    defaultSize: { width: 268, height: 190 },
    fields: [
      {
        kind: 'text',
        key: FIELD_CHECK,
        label: 'Check',
        placeholder: 'validate_sql',
        hint:
          'The package function to run, named the way `function.<name>` names it — this ' +
          'node calls that same function, not a model. It returns "" for pass or a ' +
          'non-empty string for the feedback sent back on `revise`. Three checks need no ' +
          'function behind them: `numbers_in_prose` (every figure in the answer came ' +
          'from something this run retrieved), `row_counts_in_prose` (a figure that ' +
          'came from a bare COUNT(*) is published as rows, not as things) and ' +
          '`zero_outside_coverage` (an answer reporting none of something asked about a ' +
          'period the table says it does not hold — so the zero is not a measurement). ' +
          'A package function of the same name still wins.',
        defaultValue: '',
        onCard: true,
      },
      {
        kind: 'slider',
        key: FIELD_MAX_ATTEMPTS,
        label: 'Max attempts',
        hint:
          'How many candidates this guard will check before it passes one through ' +
          'regardless. Its own budget, like a grader’s.',
        defaultValue: 3,
        min: 1,
        max: 6,
        step: 1,
        onCard: false,
        format: (value) => `· ${value} ${value === 1 ? 'attempt' : 'attempts'}`,
      },
    ],
    ports: [
      {
        id: 'candidate',
        direction: 'in',
        type: PORT.result,
        label: 'candidate',
        description: 'The value to check.',
      },
      {
        id: 'pass',
        direction: 'out',
        type: PORT.result,
        label: 'pass',
        branch: true,
        description: 'Taken when the check returns nothing to fix.',
      },
      {
        id: 'revise',
        direction: 'out',
        type: PORT.feedback,
        label: 'revise',
        branch: true,
        description:
          'The check’s own message, sent back upstream when it finds something to ' +
          'fix. Wire this the same way a grader’s `revise` is wired. Left unwired, a ' +
          'revise verdict ships as a pass.',
      },
    ],
  },
  GuardCheckNodeModel,
);

/**
 * Browser-preview executor — refuses, like the Grader's and the Guardrail's.
 *
 * A guard compiles to a conditional edge evaluated by the Python runtime, and
 * the browser preview must not execute it — a `standard` node with no
 * registered executor is silently skipped, which would make an unchecked run
 * look successful.
 */
export const guardCheckExecutor: INodeExecutor = {
  id: GUARD_CHECK_TYPE,
  execute(ctx: ExecutionContext): Promise<Result<PortOutputs, string>> {
    ctx.log('The check runs in the Python runtime, not the browser preview.');
    return Promise.resolve(
      Err(
        'This Guard compiles to a LangGraph conditional edge and calls a package function ' +
          'in the Python runtime. Use “Run” against the backend to evaluate it.',
      ),
    );
  },
};
