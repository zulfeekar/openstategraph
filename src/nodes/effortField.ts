import type { FieldOption, NodeData, SelectFieldSchema } from '@core/model/contracts/fields';
import type { INodeDefinition } from '@core/model/contracts/node';
import type { ProviderRegistry } from '@core/providers/ProviderRegistry';
import { extendFields } from '@core/model/ModelRegistry';

import { MODEL_FIELD_KEY } from './modelField';

/**
 * The key the backend's `_resolve_model(data)` reads for reasoning depth.
 * One spelling, shared — `openstategraph/reasoning.py::REASONING_EFFORT_KEY`.
 */
export const REASONING_EFFORT_FIELD_KEY = 'reasoningEffort';

/**
 * The empty selection: "however hard this model thinks by default".
 *
 * Empty, not `'medium'`, and the difference is load-bearing rather than
 * stylistic. A provider's documented default is not always the middle tier —
 * `claude-sonnet-4-6` defaults to `high` — so seeding the field with a level
 * would *change* every existing node's behaviour the day this shipped, while
 * looking like a display default. Empty also means the parameter is not sent
 * at all, which is the only value guaranteed not to break a model that has no
 * reasoning: see `apply_reasoning_effort`, which refuses to send anything for
 * a blank.
 */
export const MODEL_DEFAULT_EFFORT = '';

/**
 * The tiers offered when nobody knows better.
 *
 * The three every provider with the standard `reasoning_effort` parameter
 * spells the same way, and deliberately the *intersection* rather than the
 * union: `minimal` is real on OpenAI and Gemini and a validation error on
 * Anthropic, `max` is real on Anthropic and unknown to OpenAI. Offering the
 * union would put a tier in the picker that some models refuse — the picker
 * is a fallback for the unknown case, and a fallback should not be the
 * riskiest option on the list.
 *
 * This list is used only where capability is genuinely unknown. Where a
 * provider declares its own (`ILLMProvider.reasoningEffortLevels`), that wins.
 */
export const COMMON_EFFORT_LEVELS = ['low', 'medium', 'high'] as const;

const TIER_LABELS: Readonly<Record<string, string>> = {
  minimal: 'Minimal — fastest',
  low: 'Low — fastest',
  medium: 'Medium',
  high: 'High — most thorough',
  xhigh: 'Extra high',
  max: 'Max — slowest',
};

function labelFor(level: string): string {
  return TIER_LABELS[level] ?? level;
}

/**
 * What the editor knows about reasoning effort for a node's chosen model.
 *
 * Three states, because there are three — see `ReasoningEffortLevels`. The
 * whole reason this returns a discriminated result rather than a list is that
 * `[]` and "not known" have to produce different UI: one says *no*, the other
 * has no business saying anything.
 */
export type EffortAvailability =
  | { readonly kind: 'supported'; readonly levels: readonly string[] }
  | { readonly kind: 'unsupported'; readonly model: string }
  | { readonly kind: 'unknown' };

export function effortAvailability(
  providers: ProviderRegistry,
  data: Readonly<NodeData>,
): EffortAvailability {
  // The node's own selection, **unresolved** — an empty one is handed to the
  // registry as it stands, because the registry is what knows the open
  // document's default. This used to call `resolveModelSelection(…, {})`,
  // passing an empty settings object where the document's belonged, so every
  // node on "Workflow default" resolved to the offline simulator and the
  // picker read "Not supported by Mock · Offline" on a workflow that reasons
  // perfectly well. The label was wrong; the run was always right.
  const selection = String(data[MODEL_FIELD_KEY] ?? '');
  const levels = providers.reasoningEffortLevelsFor(selection);
  if (levels === undefined) return { kind: 'unknown' };
  if (levels.length === 0) {
    const descriptor = providers.model(selection);
    return { kind: 'unsupported', model: descriptor?.label ?? selection };
  }
  return { kind: 'supported', levels: [...levels] };
}

/**
 * The options the effort picker shows for a given node's data.
 *
 * The unsupported branch is the point of this whole module. The house rule —
 * recorded twice in the CHANGELOG, once for the Table listbox and once for the
 * five model-less pickers — is that **a control that reaches nothing is worse
 * than no control**. So a model known not to reason gets no tiers at all: one
 * inert option that names the model and states the fact. It is still a select,
 * so the card keeps a stable shape and the field keeps a stable key, but there
 * is nothing to choose and nothing that could be silently discarded.
 *
 * The unknown branch is the honest opposite. The editor cannot enumerate every
 * model a discovered catalogue might return, and pretending otherwise is how a
 * hardcoded capability list goes stale. So the common tiers are offered and the
 * hint says who settles it — the runtime, which reports what it did.
 */
export function effortOptionsFor(
  providers: ProviderRegistry,
  data: Readonly<NodeData>,
): readonly FieldOption[] {
  const availability = effortAvailability(providers, data);
  if (availability.kind === 'unsupported') {
    return [
      {
        value: MODEL_DEFAULT_EFFORT,
        label: `Not supported by ${availability.model}`,
      },
    ];
  }
  const levels =
    availability.kind === 'supported' ? availability.levels : [...COMMON_EFFORT_LEVELS];
  return [
    { value: MODEL_DEFAULT_EFFORT, label: "Model's default" },
    ...levels.map((level) => ({ value: level, label: labelFor(level) })),
  ];
}

/**
 * The chosen tier, or `undefined` for "do not send one".
 *
 * A blank must become an omitted key rather than an empty string on the wire:
 * every adapter here tests `request.effort` for truthiness to decide whether to
 * include the parameter at all, and an empty string that survived would be sent
 * to a provider as a level it has never heard of.
 */
export function effortFrom(data: Readonly<NodeData>): string | undefined {
  const chosen = String(data[REASONING_EFFORT_FIELD_KEY] ?? '').trim();
  return chosen || undefined;
}

/**
 * The reasoning-effort picker, declared **once** for every node family that
 * drives a model.
 *
 * Sits beside the model picker because that is what it is a property of. Not a
 * workflow-level default with a per-node override: the *model* already resolves
 * node-first-then-workflow, and effort is meaningless without the model it
 * qualifies — a workflow default effort would apply to nodes running six
 * different models with six different tier vocabularies, which is precisely the
 * mismatch this feature exists to prevent.
 */
export function effortField(providers: ProviderRegistry): SelectFieldSchema {
  return {
    kind: 'select',
    key: REASONING_EFFORT_FIELD_KEY,
    label: 'Reasoning',
    // Resolved per render from the node's own data, so changing the model
    // changes this list in place rather than leaving a stale tier behind.
    options: (data) => effortOptionsFor(providers, data),
    // The data half of that is free — editing the node re-renders the card. The
    // registry half is not: `reasoningEffortLevelsFor` reads the same provider
    // catalogue and `serverReadiness` that `modelOptions` does, so a refreshed
    // Ollama catalogue can turn `unknown` into `supported`, and "Not supported
    // by Mock · Offline" can stop being true, under a card already on screen.
    subscribe: (notify) => providers.onChange(notify),
    defaultValue: MODEL_DEFAULT_EFFORT,
    hint: 'Sent only to models that support it; the run reports it if it could not be.',
    // On the card, beside the model it qualifies — and not folded away as
    // advanced. The unsupported state is the reason: "Not supported by
    // <model>" is a fact about this node that a reader should get off the
    // canvas, in the same glance that tells them which model it runs. Hiding
    // it behind a fold would leave the card silent about a setting the
    // inspector still shows, which is how a card starts lying by omission.
    // Cards measure themselves (`NodeCard`), so the extra row costs layout
    // nothing.
  };
}

/**
 * Gives a node definition the effort picker **iff** it drives a model.
 *
 * Derived from the model field rather than opted into per node type, and that
 * is deliberate. `modelField.ts` exists because the opposite happened: a shared
 * concern was declared on one family and read by six, so five node types ran a
 * model nobody could choose and nothing failed. Repeating that shape here —
 * five imports of `effortField(providers)` — would be five chances to forget,
 * and the sixth family would be silently effort-less in exactly the same way.
 *
 * So the rule is stated once, as a rule: *a node that drives a model can say
 * how hard it should think.* `defineNode` already does this for the LangGraph
 * `add_node` overrides, for the same reason and in the same shape.
 *
 * Inserted directly after the model field, because the two are one decision and
 * an inspector reads top to bottom.
 *
 * Through `extendFields` rather than a spread: a definition's `create` closes
 * over the definition object itself, so a copy would give the palette the field
 * and every node built from it the old list. That is documented at the seam, in
 * `ModelRegistry`, because it is a property of `defineNode` and not of this
 * feature.
 */
export function withReasoningEffort(
  definition: INodeDefinition,
  providers: ProviderRegistry,
): INodeDefinition {
  const index = definition.fields.findIndex((field) => field.key === MODEL_FIELD_KEY);
  if (index < 0) return definition;
  if (definition.fields.some((field) => field.key === REASONING_EFFORT_FIELD_KEY)) {
    return definition;
  }
  // No separate defaults to merge: `AbstractNodeModel` builds its data from
  // `defaultsFrom(definition.fields)`, so the schema is the only declaration
  // and a field added here is initialised by the same path as every other.
  return extendFields(definition, (fields) => {
    const next = [...fields];
    next.splice(index + 1, 0, effortField(providers));
    return next;
  });
}
