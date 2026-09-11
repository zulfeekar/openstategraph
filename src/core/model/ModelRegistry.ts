import { Registry } from '@core/kernel/Registry';
import type { AbstractNodeModel } from './AbstractNodeModel';
import type { FieldSchema, NodeData } from './contracts/fields';
import type {
  INodeCategory,
  INodeDefinition,
  NodeCategoryId,
  NodeInit,
  NodeKind,
  NodeTypeId,
} from './contracts/node';
import type { IPortDescriptor, IPortTypeDefinition, PortTypeId } from './contracts/ports';
import type { ICompositionTerm } from '@core/runtime/compositionVocabulary';

/**
 * The vocabulary of the editor: which node types exist, which port types
 * exist, and how the palette is sectioned.
 *
 * Injected rather than global so tests can stand up an editor with three
 * node types, and so a future workspace could host two editors with
 * different catalogues in the same page.
 */
export class ModelRegistry {
  readonly nodeTypes = new Registry<INodeDefinition>('nodeTypes');
  readonly portTypes = new Registry<IPortTypeDefinition>('portTypes');
  readonly categories = new Registry<INodeCategory>('nodeCategories');
  /**
   * The words a mount card counts a child document's nodes in.
   *
   * A registry for the same reason the three above are: these used to be a
   * hardcoded table inside `core/runtime/compositionSummary.ts`, so a new
   * node family was invisible in every mount card until somebody edited
   * `core/` (reviews-2026-08-14 ticket 13). The built-in words are
   * `CENSUS_TERMS` in `src/nodes/vocabulary.ts`.
   *
   * Reading order is **not** registration order — a term names a group and
   * `CENSUS_GROUPS` owns the order — so a plugin registering late cannot
   * rearrange the card.
   */
  readonly censusTerms = new Registry<ICompositionTerm>('censusTerms');

  /**
   * Palette contents: categories in declared order, each with its visible
   * node types in registration order.
   */
  paletteSections(): readonly { category: INodeCategory; nodes: readonly INodeDefinition[] }[] {
    // Grouped here rather than by a `Registry.groupBy` verb: this is the only
    // place in the repository that wants it, and a collection utility on the
    // registry vocabulary is surface every extension point pays for
    // (install-experience 21).
    const byCategory = new Map<NodeCategoryId, INodeDefinition[]>();
    for (const def of this.nodeTypes.list()) {
      const bucket = byCategory.get(def.category);
      if (bucket) bucket.push(def);
      else byCategory.set(def.category, [def]);
    }
    return this.categories
      .list()
      .slice()
      .sort((a, b) => a.order - b.order)
      .map((category) => ({
        category,
        nodes: (byCategory.get(category.id) ?? []).filter((def) => !def.hiddenInPalette),
      }))
      .filter((section) => section.nodes.length > 0);
  }

  /**
   * Whether a value on `sourceType` may flow into `targetType`.
   *
   * Compatibility is declared by the *consumer* — a port states what it
   * accepts. That direction matters: adding a new producer type must not
   * require editing every existing consumer.
   */
  canConnectTypes(sourceType: PortTypeId, targetType: PortTypeId): boolean {
    if (sourceType === targetType) return true;
    const target = this.portTypes.get(targetType);
    if (!target) return false;
    const accepts = target.accepts;
    if (!accepts) return false;
    return accepts.includes('*') || accepts.includes(sourceType);
  }

  /** Presentation for a port type, falling back to a neutral placeholder. */
  portType(id: PortTypeId): IPortTypeDefinition {
    return (
      this.portTypes.get(id) ?? {
        id,
        label: id,
        iconId: 'port-any',
        accent: 'neutral',
      }
    );
  }
}

/* ------------------------------------------------------------------ *
 * defineNode — the authoring helper.
 *
 * Node modules describe themselves with this instead of hand-writing an
 * INodeDefinition, which keeps the required/optional split honest and
 * gives every node type the same defaults.
 * ------------------------------------------------------------------ */

export interface NodeSpec {
  readonly id: NodeTypeId;
  readonly kind?: NodeKind;
  readonly category: NodeCategoryId;
  readonly label: string;
  readonly description: string;
  readonly iconId: string;
  readonly accent: INodeDefinition['accent'];
  readonly fields?: readonly FieldSchema[];
  /** Static port list, or a function of the node's data for dynamic ports. */
  readonly ports?:
    readonly IPortDescriptor[] | ((data: Readonly<NodeData>) => readonly IPortDescriptor[]);
  readonly defaultSize: INodeDefinition['defaultSize'];
  readonly maxInstances?: number;
  readonly hiddenInPalette?: boolean;
  readonly bodyId?: string;
  readonly keywords?: readonly string[];
  /** See `INodeDefinition.scope`. Omitted means app-wide. */
  readonly scope?: INodeDefinition['scope'];
  /** See `INodeDefinition.bindsWithoutWiring`. Omitted means "needs an edge". */
  readonly bindsWithoutWiring?: boolean;
  /** See `INodeDefinition.editorOnly`. Omitted means the backend runs it. */
  readonly editorOnly?: boolean;
  /**
   * Whether this family's compiled body is `async def`, and so can be
   * interrupted part-way (`langchain-drift-watch/02`).
   *
   * It gates one thing: whether the card is offered a timeout. LangGraph
   * refuses `add_node(timeout=...)` for a synchronous body **at compile
   * time**, so the field was not merely ignored on such a card — a document
   * that acquired it could not be loaded at all.
   *
   * Named for the property and not for the field, because it is the same
   * question `compile/node_doors.is_interruptible` answers on the Python
   * side: a body a stop can cancel is a body a timeout can interrupt. The two
   * are kept in step by
   * `backend/tests/test_the_editor_offers_timeout_only_where_the_compiler_keeps_it.py`,
   * which builds each type and compares — so this flag cannot quietly drift
   * from the body it describes.
   *
   * Omitted means synchronous, which is the safe default: a family that
   * forgets the flag loses a field, where one that wrongly claims it would
   * ship a document that will not compile.
   */
  readonly interruptible?: boolean;
}

type NodeConstructor = new (definition: INodeDefinition, init: NodeInit) => AbstractNodeModel;

/**
 * `add_node`'s own per-node overrides (LangGraph: `retry_policy`, `timeout`
 * — see `StateGraph.set_node_defaults` for the graph-wide default every
 * node already gets). CLAUDE.md is explicit that these are graph-assembly
 * parameters, not a node-type concern — declaring them once here, appended
 * to every *executable* node's fields, is that rule applied: a new node
 * type inherits the override capability for free, exactly as
 * `resolveMiddleware()`/`resolvePrompt()` are inherited capabilities rather
 * than something each concrete type re-declares.
 *
 * `timeout` is the one with a condition, and it is a property of the *body*
 * rather than of the type: LangGraph refuses it at compile time for a
 * synchronous one, so it is offered only where `NodeSpec.interruptible` says
 * it can be honoured (`langchain-drift-watch/02`). The capability is still
 * inherited rather than re-declared — what varies is whether the family can
 * use it.
 *
 * Empty string means "use the graph's default" — not `0`, which CLAUDE.md's
 * own rule against non-finite/sentinel numbers in a serialisable field
 * rules out as a stand-in for "unbounded" or "unset". `int | None` is the
 * correct shape; a `text` field with an empty-string default is this
 * schema's way of expressing that same optionality, since `FieldValue` has
 * no dedicated "unset" for a `SliderFieldSchema`'s required numeric
 * default.
 */
const FIELD_MAX_RETRIES = 'maxRetries';
const FIELD_TIMEOUT_SECONDS = 'timeoutSeconds';
const FIELD_CACHE_TTL_SECONDS = 'cacheTtlSeconds';

const positiveIntegerOrEmpty = (value: string): string | null => {
  if (value.trim() === '') return null;
  const n = Number(value);
  return Number.isInteger(n) && n > 0 ? null : 'Must be a positive whole number, or blank';
};

const positiveNumberOrEmpty = (value: string): string | null => {
  if (value.trim() === '') return null;
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? null : 'Must be a positive number of seconds, or blank';
};

const EXECUTION_OVERRIDE_FIELDS: readonly FieldSchema[] = [
  {
    kind: 'text',
    key: FIELD_MAX_RETRIES,
    label: 'Max retries (override)',
    hint: 'Blank uses the workflow default (3 attempts).',
    placeholder: '3',
    defaultValue: '',
    onCard: false,
    group: 'Execution',
    advanced: true,
    validate: positiveIntegerOrEmpty,
  },
  {
    kind: 'text',
    key: FIELD_TIMEOUT_SECONDS,
    label: 'Timeout, seconds (override)',
    // Says where it works as well as what it does. The field is only offered
    // on nodes that can honour it now (`NodeSpec.interruptible`), and a
    // developer who has seen it on other cards deserves the reason rather
    // than a silent absence.
    hint: 'Blank means no per-node timeout. Offered only on steps that can be interrupted part-way.',
    placeholder: 'e.g. 30',
    defaultValue: '',
    onCard: false,
    group: 'Execution',
    advanced: true,
    validate: positiveNumberOrEmpty,
  },
  {
    kind: 'text',
    key: FIELD_CACHE_TTL_SECONDS,
    label: 'Cache result for, seconds',
    // Deliberately not "speed this up". Caching is only correct when this
    // node's inputs decide its output, and most nodes here drive a model,
    // so the hint names the condition rather than the benefit — the same
    // reason `stepBudget`'s copy does not simply offer a bigger number.
    hint: 'Blank means never cached. Only safe when the same input must give the same result.',
    placeholder: 'e.g. 300',
    defaultValue: '',
    onCard: false,
    group: 'Execution',
    advanced: true,
    validate: positiveIntegerOrEmpty,
  },
];

/**
 * The keys `defineNode` injects onto every standard node type.
 *
 * Exported for the field-contract tests, which each subtract these before
 * comparing an atom's keys against its Python mirror — they are
 * `StateGraph.add_node` parameters, so no atom declares or mirrors them.
 * Exported rather than retyped: the list was spelled out by hand in four
 * test files, so adding `cacheTtlSeconds` (`organisms-first-class/34`)
 * broke all four at once. Duplication of *knowledge* is the defect.
 */
export const EXECUTION_OVERRIDE_KEYS: readonly string[] = EXECUTION_OVERRIDE_FIELDS.map(
  (f) => f.key,
);

/**
 * The subset every standard type gets, and the one that has a condition.
 *
 * `timeoutSeconds` is not a property of "a node the compiler schedules" — it
 * is a property of a node whose body can be interrupted, which is a smaller
 * set (`langchain-drift-watch/02`). `EXECUTION_OVERRIDE_KEYS` above stays
 * whole on purpose: it is what the field-contract tests subtract, and the key
 * may still legitimately sit in any node's saved `data` — a document written
 * before this distinction existed keeps its value, and the compiler reports
 * it rather than failing.
 */
const ALWAYS_OFFERED = EXECUTION_OVERRIDE_FIELDS.filter((f) => f.key !== FIELD_TIMEOUT_SECONDS);

/**
 * The override keys every standard type is offered, whatever its body does.
 *
 * Exported for the one test that asserts a node's field list *exactly* rather
 * than subtracting — `EXECUTION_OVERRIDE_KEYS` is still the right list to
 * subtract, because the timeout key may legitimately sit in a saved document
 * for any type. Derived, not retyped, for the reason that list already
 * records: spelling it by hand is how adding a field broke four files at once.
 */
export const ALWAYS_OFFERED_OVERRIDE_KEYS: readonly string[] = ALWAYS_OFFERED.map((f) => f.key);
const OFFERED_WHEN_INTERRUPTIBLE = EXECUTION_OVERRIDE_FIELDS.filter(
  (f) => f.key === FIELD_TIMEOUT_SECONDS,
);

/**
 * Binds a spec to the concrete model class that implements it.
 *
 * The definition closes over itself so `create` can hand the instance its
 * own definition — that back-reference is what lets a node read its schema
 * and ports without a registry lookup.
 */
export function defineNode(spec: NodeSpec, Model: NodeConstructor): INodeDefinition {
  const ports = spec.ports ?? [];
  const kind = spec.kind ?? 'standard';
  // Only nodes the compiler actually schedules (`add_node`) can have a
  // per-node override at all — a container or annotation never runs. The
  // timeout is narrower still: see `NodeSpec.interruptible`.
  const fields =
    kind === 'standard'
      ? [
          ...(spec.fields ?? []),
          ...ALWAYS_OFFERED,
          ...(spec.interruptible === true ? OFFERED_WHEN_INTERRUPTIBLE : []),
        ]
      : (spec.fields ?? []);
  const definition: INodeDefinition = {
    id: spec.id,
    kind,
    category: spec.category,
    label: spec.label,
    description: spec.description,
    iconId: spec.iconId,
    accent: spec.accent,
    fields,
    ports: typeof ports === 'function' ? ports : () => ports,
    defaultSize: spec.defaultSize,
    ...(spec.maxInstances != null ? { maxInstances: spec.maxInstances } : {}),
    ...(spec.hiddenInPalette ? { hiddenInPalette: true } : {}),
    ...(spec.bodyId ? { bodyId: spec.bodyId } : {}),
    ...(spec.keywords ? { keywords: spec.keywords } : {}),
    ...(spec.scope ? { scope: spec.scope } : {}),
    ...(spec.bindsWithoutWiring ? { bindsWithoutWiring: true } : {}),
    ...(spec.editorOnly ? { editorOnly: true } : {}),
    // Self-referencing on purpose — every instance reports the definition it
    // was built from. `extendFields` below exists because of this line.
    create: (init) => new Model(definition, init),
  };
  return definition;
}

/**
 * Adds fields to a definition **in place**, and returns the same object.
 *
 * In place, not a copy, and the reason is one line up: `create` closes over the
 * definition `defineNode` built, so `{ ...definition, fields }` produces an
 * object whose palette entry has the new field and whose *node instances* do
 * not. That failure is silent in every test that inspects a definition and
 * visible only in the running editor — found exactly that way, with the
 * reasoning-effort picker present in the registered definition's fields and
 * absent from the inspector of a node created from it.
 *
 * So a definition is one object, and extending it means extending that object.
 * Callers stay honest by going through here rather than spreading, and this
 * comment is why.
 */
export function extendFields(
  definition: INodeDefinition,
  extend: (fields: readonly FieldSchema[]) => readonly FieldSchema[],
): INodeDefinition {
  const mutable = definition as { fields: readonly FieldSchema[] };
  mutable.fields = extend(definition.fields);
  return definition;
}

/**
 * Free-text palette search across label, description and keywords.
 * Exported here rather than in the view so the ranking is testable.
 */
export function matchesQuery(definition: INodeDefinition, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  const haystack = [definition.label, definition.description, ...(definition.keywords ?? [])]
    .join(' ')
    .toLowerCase();
  // Every whitespace-separated term must appear, so "reddit tool" narrows
  // rather than widens.
  return q.split(/\s+/).every((term) => haystack.includes(term));
}
