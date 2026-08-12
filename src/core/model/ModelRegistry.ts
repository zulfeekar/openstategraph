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
   * Palette contents: categories in declared order, each with its visible
   * node types in registration order.
   */
  paletteSections(): readonly { category: INodeCategory; nodes: readonly INodeDefinition[] }[] {
    const byCategory = this.nodeTypes.groupBy<NodeCategoryId>((def) => def.category);
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
    hint: 'Blank means no per-node timeout.',
    placeholder: 'e.g. 30',
    defaultValue: '',
    onCard: false,
    group: 'Execution',
    advanced: true,
    validate: positiveNumberOrEmpty,
  },
];

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
  // per-node retry/timeout override — a container or annotation never runs.
  const fields =
    kind === 'standard'
      ? [...(spec.fields ?? []), ...EXECUTION_OVERRIDE_FIELDS]
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
