import { Err, type Result } from '@core/kernel/Result';
import { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import { defineNode } from '@core/model/ModelRegistry';
import type { INodeDefinition, NodeInit } from '@core/model/contracts/node';
import type { ExecutionContext, INodeExecutor, PortOutputs } from '@core/execution/INodeExecutor';
import type { ProviderRegistry } from '@core/providers/ProviderRegistry';
import { CATEGORY, PORT } from '../vocabulary';
import { modelField } from '../modelField';
import { SKILL_PORT, replacesRules, rulesModeField, withMigratedRulesMode } from '../skillLayer';

export const GRADER_TYPE = 'route.grader';

const FIELD_CRITERIA = 'criteria';
const FIELD_MAX_ATTEMPTS = 'maxAttempts';
const FIELD_TIER = 'tier';

/** Locked. What a grader *is* — not an editable field. */
export const GRADER_PREAMBLE =
  'You are a grader. You judge whether a candidate answer is good enough to ' +
  'return to the user. You never rewrite it yourself.';

/**
 * Prebuilt criteria, so a grader works before anyone configures it.
 *
 * **Mirrors `BaseGrader.PROMPT.default_rules`** — the ClassVar, not the
 * `DEFAULT_CRITERIA` this comment used to name, which install-experience 19
 * deleted — and is pinned to it by
 * `backend/tests/test_prompt_mirror_contract.py` (ticket 38). A developer
 * **extends** these by default, or **replaces** them by switching the mode;
 * prebuilt behaviour that cannot be overridden is a straitjacket.
 *
 * **The fourth bullet is the one that was missing here**, and it was not
 * cosmetic. It was added to Python after a live trace on 2026-08-11 in which a
 * correct honest decline was graded FAIL, the retries came back empty, and the
 * revision loop destroyed the right answer it already held. The editor showed
 * a developer three bullets while their run obeyed four.
 */
export const GRADER_DEFAULT_CRITERIA = [
  '- The answer must address the question that was asked.',
  '- Figures must come from the supplied data, never invented.',
  '- An answer that is empty, truncated or an error is a FAIL.',
  '- An answer that honestly declines — stating it cannot be produced, and ' +
    'why — is a PASS. It is a correct answer, not a failed one, and retrying ' +
    'it cannot make the missing capability appear.',
].join('\n');

/** Locked, and rendered **last** so criteria cannot countermand it. */
export const GRADER_OUTPUT_CONTRACT =
  'Reply with PASS or FAIL on the first line. If FAIL, add one short line ' +
  'saying exactly what to change. Nothing else.';

export class GraderNodeModel extends AbstractNodeModel {
  /**
   * The Grader is the one node type whose saved documents can carry the
   * pre-generalisation `criteriaMode`, because it is the one type that ever
   * declared it. Rewriting it here — before `AbstractNodeModel` merges the new
   * field's `extend` default over the record — is what keeps such a document
   * behaving exactly as it did; see `withMigratedRulesMode` for why read-time
   * tolerance would not have been enough.
   */
  constructor(definition: INodeDefinition, init: NodeInit) {
    super(definition, withMigratedRulesMode(init));
  }

  /**
   * True when the developer's criteria replace the prebuilt ones.
   *
   * The one derived read that stays: it is not a mirror of anything Python
   * composes, it is the editor reading its **own** document — `rulesMode`
   * with the pre-generalisation `criteriaMode` as a fallback — which is the
   * migration the constructor above depends on.
   */
  get replacesDefaults(): boolean {
    return replacesRules(this.data);
  }

  /**
   * There is deliberately no `systemPrompt` getter here (ticket 39), and no
   * `effectiveCriteria` either (ticket 42). See the note in `RouterNode.ts`:
   * the editor assembles no prompt of its own and composes no rules layers of
   * its own, and `backend/tests/test_prompt_mirror_contract.py` fails if
   * either returns.
   *
   * `effectiveCriteria` was the layering half of the same mirror — extend by
   * newline, replace keeps the developer's text, an empty override falls back
   * — and it knew **two** of Python's three layers. `effective_rules()`
   * composes `default_rules` → `rules` → `skill` under one replace/extend
   * switch, and this Grader has a `skill` port, so a grader with a wired skill
   * had no TypeScript answer at all. Nothing read it but its own unit test;
   * every promise it made is asserted against the runtime in
   * `backend/tests/test_grader.py` and `backend/tests/test_skill_layer.py`.
   */
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
export function createGraderNode(providers: ProviderRegistry): INodeDefinition {
  return defineNode(
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
        modelField(providers),
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
              // A criterion is a sentence, and the field beside it holding the
              // same kind of content is already a paragraph (ticket 26).
              kind: 'textarea',
              key: 'criterion',
              label: 'Criterion',
              placeholder: 'e.g. Cites a figure from the executed rows',
              defaultValue: '',
              minRows: 2,
              maxRows: 6,
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
          maxRows: 14,
        },
        // Was `criteriaMode`, declared here and nowhere else. It is the same
        // switch over the same layers — the generalisation only adds a third
        // layer (a wired skill) above — so it is now the shared declaration
        // in `../skillLayer`, on the card as before because the criteria it
        // modifies are on the card.
        rulesModeField({ onCard: true }),
        {
          kind: 'slider',
          key: FIELD_MAX_ATTEMPTS,
          // Attempts, and **this grader's own**. Both halves of that were
          // wrong on the card until `workflow-gallery` 21.
          //
          // Not supersteps: `recursion_limit` counts those and one lap of a
          // loop can cost several, so it is never the number a user means
          // here — which is why the graph keeps its own counter.
          //
          // Not revisions either, and not the graph's: the runtime checked a
          // single graph-wide integer that every model-driven node
          // incremented once per invocation, so "3 max" bought a number of
          // laps that depended on the shape of the graph around it, and a
          // second grader in series inherited the first stage's spend. The
          // count is per grader now, and it counts candidates *judged* — so
          // `n` allows `n - 1` revisions, which is what the hint says rather
          // than what the label implies.
          label: 'Max attempts',
          hint:
            'How many candidates this grader will judge before it passes one ' +
            'through. Its own budget — another grader in the same workflow ' +
            'gets its own. 3 attempts allows 2 revisions.',
          defaultValue: 3,
          min: 1,
          max: 6,
          step: 1,
          onCard: false,
          format: (value) => `· ${value} ${value === 1 ? 'attempt' : 'attempts'}`,
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
        // A grader composes a prompt, so it takes a skill like every other
        // model-driven type — one declaration, in `../skillLayer`.
        { ...SKILL_PORT },
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
}

/**
 * Browser-preview executor — refuses, like the Router's.
 *
 * A grader compiles to a conditional edge in the Python runtime, and the browser
 * must not execute (ticket 07). It exists rather than being omitted because a
 * `standard` node with no registered executor is **silently skipped** by the
 * preview engine, so the run would look successful while nothing was graded.
 */
export const graderExecutor: INodeExecutor = {
  id: GRADER_TYPE,
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
