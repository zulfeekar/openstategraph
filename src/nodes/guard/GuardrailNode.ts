import { Err, type Result } from '@core/kernel/Result';
import { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import { defineNode } from '@core/model/ModelRegistry';
import type { FieldValue } from '@core/model/contracts/fields';
import type { INodeDefinition } from '@core/model/contracts/node';
import type { ExecutionContext, INodeExecutor, PortOutputs } from '@core/execution/INodeExecutor';
import { CATEGORY, PORT } from '../vocabulary';
import { validateDetector } from './detectorPattern';

export const GUARDRAIL_TYPE = 'guard.policy';

const FIELD_POLICY = 'policy';
const FIELD_BLOCKED_MESSAGE = 'blockedMessage';
const FIELD_POLICY_NOTE = 'policyNote';

/**
 * The entity types LangChain's own detectors cover, in the order the card
 * offers them.
 *
 * Mirrored from `openstategraph.abc.guardrail.BUILTIN_ENTITIES`, which in turn
 * asserts itself against the library's table — so this list is two hops from
 * the thing that actually detects, and a release adding `phone` fails a
 * Python test rather than leaving a card that quietly cannot deliver it.
 *
 * **No phone, no national ID, no postal address.** Those need a pattern, which
 * is what the `detector` column is for.
 */
export const GUARDRAIL_BUILTIN_ENTITIES = [
  'email',
  'credit_card',
  'ip',
  'mac_address',
  'url',
] as const;

/**
 * What a row may do about what it finds.
 *
 * Four are LangChain's. **`pass` is ours**, and it is the row the owner's
 * requirement is written in: a user gives an email address to look up a
 * customer, so email *inbound* must pass or the product cannot do its job,
 * while the same email *outbound* is customer data leaving the building. One
 * entity, two answers — which is why the unit of policy is `entity ×
 * direction` and not `entity`.
 *
 * Middleware expresses "allowed" as a rule nobody wrote. A canvas cannot: an
 * absent row and a deliberate exemption look identical, and the deliberate
 * one is a decision somebody should be able to read off the card.
 */
export const GUARDRAIL_STRATEGIES = ['pass', 'redact', 'mask', 'hash', 'block'] as const;

/** One row of the policy table. */
export interface PolicyRow {
  id: string;
  entity: string;
  strategy: string;
  /** A regular expression, for an entity the library has no detector for. */
  detector: string;
  [key: string]: FieldValue;
}

/**
 * What the machinery says, shown read-only beside the part a developer owns.
 *
 * The prompt-composition rule generalised past prompts: the original
 * `RouterNode` bug was an editable field pre-filled with machinery, so the
 * first thing anyone did — clear it and write their own — broke the node.
 * The refusal here is genuinely the developer's copy to write, so what they
 * need is to *see* the default rather than be handed it in a box.
 */
export const GUARDRAIL_LOCKED_NOTE =
  'Detection is LangChain’s: credit cards are Luhn-checked, and this node ' +
  'never runs a pattern of ours. Direction is where you place this node — ' +
  'after Input, or before Output — not a setting. A blocked message leaves ' +
  'by the blocked port; the default refusal names the category and never the ' +
  'value. These shapes are not prompt-injection screening.';

export class GuardrailNodeModel extends AbstractNodeModel {
  /** The rows a developer configured, in the order they apply. */
  get policy(): PolicyRow[] {
    const raw = this.getField<FieldValue>(FIELD_POLICY);
    if (!Array.isArray(raw)) return [];
    return raw
      .filter((row): row is PolicyRow => typeof row === 'object' && row !== null)
      .map((row) => ({
        id: String(row.id ?? ''),
        entity: String(row.entity ?? ''),
        strategy: String(row.strategy ?? 'redact'),
        detector: String(row.detector ?? ''),
      }));
  }

  /** The developer's own refusal copy, or `''` for the built-in one. */
  get blockedMessage(): string {
    return this.getText(FIELD_BLOCKED_MESSAGE);
  }

  /**
   * The policy, in one line, on the card.
   *
   * A guardrail with an empty table enforces nothing, and a card that reads
   * like a working guard while enforcing nothing is the worst outcome
   * available here — so the empty case says so in as many words rather than
   * falling back to the type's description.
   */
  override get subtitle(): string {
    const rows = this.policy.filter((row) => row.entity.trim());
    if (rows.length === 0) return 'No rules yet — nothing is checked.';
    return rows.map((row) => `${row.entity} → ${row.strategy}`).join(', ');
  }
}

/**
 * A workflow's PII and content policy, in one visible place.
 *
 * ## Why a node rather than middleware on each agent
 *
 * The shipped Chinook document has three agents, so middleware means three
 * copies of one policy and three chances to miss one. More than that: a
 * refusal becomes part of the drawing instead of a behaviour you hope is on,
 * which is this product's whole thesis applied to policy.
 *
 * ## Direction is not a setting
 *
 * LangChain's `PIIMiddleware` has three booleans — `applyToInput`,
 * `applyToOutput`, `applyToToolResults`. Two of them are, on a canvas, simply
 * *where you put this node*: after Input, or before Output. The third has no
 * wire to sit on, because it happens inside an agent's loop, so it stays
 * middleware on the agent base. That is why there is no direction control
 * here and must never be one — a flag that can disagree with the wire is the
 * `advisor`/`audience` defect drawn on a canvas.
 *
 * ## What it does not do
 *
 * These are deterministic shapes, not judgement. Nothing here detects a
 * jailbreak or an injected instruction — see `docs/decisions/injection-screening.md`.
 *
 * Compiles to a real state-transforming graph node plus a conditional edge
 * (`compile/node_runtime.py`'s `_guardrail`), never to an agent.
 */
export const guardrailNode: INodeDefinition = defineNode(
  {
    id: GUARDRAIL_TYPE,
    category: CATEGORY.agent,
    label: 'Guardrail',
    description: 'Applies a PII policy to whatever passes through, and refuses what it must.',
    iconId: 'node-guardrail',
    accent: 'red',
    keywords: [
      'guardrail',
      'pii',
      'redact',
      'mask',
      'block',
      'policy',
      'privacy',
      'safety',
      'email',
      'credit card',
      'compliance',
    ],
    defaultSize: { width: 268, height: 200 },
    fields: [
      {
        // Entity x strategy, one row each — never a global toggle. The
        // *direction* half of `entity x direction` comes from where the node
        // sits, so it is not a column.
        kind: 'repeatable-group',
        key: FIELD_POLICY,
        label: 'Policy',
        addLabel: 'Add rule',
        maxRows: 12,
        // A guardrail's whole value is that the policy is readable without
        // opening anything, so unlike the Grader's rubric this one is on the
        // card.
        onCard: true,
        defaultValue: [
          // A working default rather than a blank table, following the
          // Grader's prebuilt criteria: the two entities a shipped workflow
          // most often leaks, at the two strategies that suit them. A
          // developer changes `redact` to `pass` on the instance they place
          // inbound — which is the owner's email-lookup case, said on a card.
          { id: 'g1', entity: 'email', strategy: 'redact', detector: '' },
          { id: 'g2', entity: 'credit_card', strategy: 'block', detector: '' },
        ],
        fields: [
          {
            // A combobox, not a select: the built-ins are the list, and a
            // custom entity name is a thing you type. The same argument
            // `ComboboxFieldSchema` records for a mount slug — a listbox
            // would make `phone` unreachable.
            kind: 'combobox',
            key: 'entity',
            label: 'Entity',
            defaultValue: '',
            placeholder: 'email',
            options: GUARDRAIL_BUILTIN_ENTITIES.map((entity) => ({
              value: entity,
              label: entity,
            })),
            emptyHint: 'Anything else needs a pattern below.',
          },
          {
            kind: 'select',
            key: 'strategy',
            label: 'Strategy',
            defaultValue: 'redact',
            options: [
              { value: 'pass', label: 'Pass · leave it alone' },
              { value: 'redact', label: 'Redact · [REDACTED_EMAIL]' },
              { value: 'mask', label: 'Mask · ****-****-****-1234' },
              { value: 'hash', label: 'Hash · deterministic' },
              { value: 'block', label: 'Block · refuse, take the blocked wire' },
            ],
          },
          {
            // A **regular expression**, and that is a portability decision
            // recorded at `abc/guardrail.py`'s `GuardrailRule`: a stored
            // Python lambda would kill portability and serialisability in one
            // move, while a pattern is declarative data with a published
            // grammar — the same reason `Reducer` is a name, not a function.
            // A paragraph field for a one-line value, deliberately (ticket
            // 26): a pattern is long, and the alternative to wrapping it is a
            // box that scrolls sideways through the developer's own regex.
            // Checked here, before it is ever saved (guardrails ticket 05):
            // until then the first thing that looked at this value was
            // `screen()`, inside a run, and a missing `)` arrived as an
            // exception rather than as a sentence. What "invalid" means lives
            // in one place and is pinned across both languages — see
            // `detectorPattern.ts`.
            kind: 'textarea',
            key: 'detector',
            label: 'Pattern',
            defaultValue: '',
            placeholder: 'only for an entity LangChain has no detector for',
            minRows: 1,
            maxRows: 4,
            mono: true,
            validate: validateDetector,
          },
        ],
      },
      {
        kind: 'readonly',
        key: FIELD_POLICY_NOTE,
        label: 'What the machinery already does',
        defaultValue: GUARDRAIL_LOCKED_NOTE,
        onCard: false,
        group: 'Policy',
      },
      {
        // The developer's own words. Unlike an output contract this really is
        // theirs — a refusal is a message to a person, not a shape the
        // machinery has to parse — so it is editable and starts empty.
        kind: 'textarea',
        key: FIELD_BLOCKED_MESSAGE,
        label: 'Your refusal message',
        placeholder: 'Leave empty to name the category that was found.',
        defaultValue: '',
        minRows: 2,
        maxRows: 8,
        onCard: false,
        group: 'Policy',
      },
    ],
    ports: [
      {
        id: 'content',
        direction: 'in',
        type: PORT.result,
        label: 'content',
        description: 'Whatever should be checked before it goes any further.',
      },
      {
        id: 'allowed',
        direction: 'out',
        type: PORT.result,
        label: 'allowed',
        branch: true,
        description: 'The content, with every rule applied, on its way to the next step.',
      },
      {
        id: 'blocked',
        direction: 'out',
        type: PORT.result,
        label: 'blocked',
        branch: true,
        description:
          'Taken when a rule blocks. Wire this to an Output node so the refusal reaches ' +
          'the user along a visible path instead of vanishing.',
      },
    ],
  },
  GuardrailNodeModel,
);

/**
 * Browser-preview executor — refuses, like the Router's and the Grader's.
 *
 * Exists rather than being omitted because a `standard` node with no
 * registered executor is **silently skipped** by the preview engine, and a
 * skipped guardrail is the one failure mode worth designing against: the run
 * would look successful while nothing was checked.
 */
export const guardrailExecutor: INodeExecutor = {
  id: GUARDRAIL_TYPE,
  execute(ctx: ExecutionContext): Promise<Result<PortOutputs, string>> {
    ctx.log('The policy is applied by the Python runtime, not the browser preview.');
    return Promise.resolve(
      Err(
        'This Guardrail compiles to a LangGraph node using LangChain’s own detectors and ' +
          'runs in the Python runtime. Use “Run” against the backend to apply it.',
      ),
    );
  },
};
