import { Err, type Result } from '@core/kernel/Result';
import { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import { defineNode } from '@core/model/ModelRegistry';
import type { INodeDefinition } from '@core/model/contracts/node';
import type { ExecutionContext, INodeExecutor, PortOutputs } from '@core/execution/INodeExecutor';
import { CATEGORY, PORT } from '../vocabulary';

export const GRADER_TYPE = 'route.grader';

const FIELD_CRITERIA = 'criteria';
const FIELD_MODE = 'criteriaMode';
const FIELD_MAX_ATTEMPTS = 'maxAttempts';
const FIELD_TIER = 'tier';

/** Locked. What a grader *is* — not an editable field. */
export const GRADER_PREAMBLE =
  'You are a grader. You judge whether a candidate answer is good enough to ' +
  'return to the user. You never rewrite it yourself.';

/**
 * Prebuilt criteria, so a grader works before anyone configures it.
 *
 * Mirrors `BaseGrader.DEFAULT_CRITERIA` in Python. A developer **extends** these
 * by default, or **replaces** them by switching the mode — prebuilt behaviour
 * that cannot be overridden is a straitjacket.
 */
export const GRADER_DEFAULT_CRITERIA = [
  '- The answer must address the question that was asked.',
  '- Figures must come from the supplied data, never invented.',
  '- An answer that is empty, truncated or an error is a FAIL.',
].join('\n');

/** Locked, and rendered **last** so criteria cannot countermand it. */
export const GRADER_OUTPUT_CONTRACT =
  'Reply with PASS or FAIL on the first line. If FAIL, add one short line ' +
  'saying exactly what to change. Nothing else.';

export class GraderNodeModel extends AbstractNodeModel {
  /** The developer's criteria. The only authorable part of the prompt. */
  get criteria(): string {
    return this.getText(FIELD_CRITERIA);
  }

  /** True when the developer's criteria replace the prebuilt ones. */
  get replacesDefaults(): boolean {
    return this.getText(FIELD_MODE) === 'replace';
  }

  /**
   * The criteria the model actually sees.
   *
   * Replacing with an *empty* string falls back to the defaults: clearing a
   * field is far more often a slip than a deliberate request for no criteria.
   */
  get effectiveCriteria(): string {
    const mine = this.criteria.trim();
    if (this.replacesDefaults && mine) return mine;
    if (!mine) return GRADER_DEFAULT_CRITERIA;
    return `${GRADER_DEFAULT_CRITERIA}\n${mine}`;
  }

  /**
   * The whole prompt, assembled — preamble, criteria, contract **last**.
   *
   * Exposed so the inspector can show the locked parts read-only beside the
   * editable one. A developer writing criteria needs to see what the machinery
   * already says, or they duplicate and contradict it.
   */
  get systemPrompt(): string {
    return [GRADER_PREAMBLE, `Criteria:\n${this.effectiveCriteria}`, GRADER_OUTPUT_CONTRACT].join(
      '\n\n',
    );
  }
}

/**
 * Judges a candidate answer and either passes it on or sends feedback back.
 *
 * The second **role preset**, and the node that makes loops legal: its
 * `revise` output is the only `feedback`-typed port in the catalogue, and
 * `acyclicRule` permits a cycle *only* when it closes on one. So an accidental
 * loop stays impossible to draw while an evaluator-optimizer loop is two clicks
 * — the type system is the gate, not a flag (ticket 09).
 *
 * Compiles to a conditional edge: `pass` continues, `revise` returns upstream.
 */
export const graderNode: INodeDefinition = defineNode(
  {
    id: GRADER_TYPE,
    category: CATEGORY.agent,
    label: 'Grader',
    description: 'Checks an answer, and sends it back with feedback if it falls short.',
    iconId: 'node-grader',
    accent: 'green',
    keywords: ['grade', 'evaluate', 'check', 'critic', 'verify', 'judge', 'quality'],
    defaultSize: { width: 268, height: 210 },
    fields: [
      {
        // Structured rubric rows (ticket 66): each is judged explicitly, a
        // failed REQUIRED row is a revise. Composes with the criteria —
        // the backend renders it as machinery context, so `replace` on the
        // criteria never deletes it.
        kind: 'repeatable-group',
        key: 'rubric',
        label: 'Rubric',
        addLabel: 'Add rubric row',
        maxRows: 10,
        onCard: false,
        group: 'Judgement',
        fields: [
          {
            kind: 'text',
            key: 'criterion',
            label: 'Criterion',
            placeholder: 'e.g. Cites a figure from the executed rows',
            defaultValue: '',
          },
          { kind: 'toggle', key: 'required', label: 'Required', defaultValue: true },
        ],
      },
      {
        kind: 'textarea',
        key: FIELD_CRITERIA,
        label: 'Your criteria',
        // Criteria only. The preamble and output contract are locked, because a
        // grader whose verdict cannot be parsed is a broken node.
        placeholder: '- Must name a specific genre, not an artist.',
        defaultValue: '',
        minRows: 3,
      },
      {
        kind: 'select',
        key: FIELD_MODE,
        label: 'Criteria mode',
        defaultValue: 'extend',
        options: [
          { value: 'extend', label: 'Add to the built-in criteria' },
          { value: 'replace', label: 'Replace the built-in criteria' },
        ],
      },
      {
        kind: 'slider',
        key: FIELD_MAX_ATTEMPTS,
        label: 'Max revisions',
        defaultValue: 3,
        min: 1,
        max: 6,
        step: 1,
        onCard: false,
        // Revisions, not supersteps. `recursion_limit` counts supersteps and one
        // lap of a loop can cost several, so it is never the number a user means
        // here — which is why the graph keeps its own attempt counter.
        format: (value) => `· ${value} max`,
      },
      {
        kind: 'select',
        key: FIELD_TIER,
        label: 'Runtime',
        defaultValue: 'react',
        onCard: false,
        options: [
          { value: 'react', label: 'Agent · create_agent' },
          { value: 'deep', label: 'Deep agent · create_deep_agent' },
          { value: 'custom', label: 'Custom · hand-written node' },
        ],
      },
    ],
    ports: [
      {
        id: 'candidate',
        direction: 'in',
        type: PORT.result,
        label: 'candidate',
        description: 'The answer to judge.',
      },
      {
        id: 'pass',
        direction: 'out',
        type: PORT.result,
        label: 'pass',
        branch: true,
        description: 'Taken when the answer meets the criteria.',
      },
      {
        id: 'revise',
        direction: 'out',
        type: PORT.feedback,
        label: 'revise',
        branch: true,
        description:
          'Feedback sent back upstream when the answer falls short. Wire this to an ' +
          'agent’s feedback input to form a revision loop.',
      },
    ],
  },
  GraderNodeModel,
);

/**
 * Browser-preview executor — refuses, like the Router's.
 *
 * A grader compiles to a conditional edge in the Python runtime, and the browser
 * must not execute (ticket 07). It exists rather than being omitted because a
 * `standard` node with no registered executor is **silently skipped** by the
 * preview engine, so the run would look successful while nothing was graded.
 */
export const graderExecutor: INodeExecutor = {
  id: graderNode.id,
  execute(ctx: ExecutionContext): Promise<Result<PortOutputs, string>> {
    ctx.log('Grading is evaluated by the Python runtime, not the browser preview.');
    return Promise.resolve(
      Err(
        'This Grader compiles to a LangGraph conditional edge and runs in the Python ' +
          'runtime. Use “Run” against the backend to evaluate it.',
      ),
    );
  },
};
