/**
 * Field schemas.
 *
 * A node type declares its configuration once, as data. That single
 * declaration drives the controls on the node card, the controls in the
 * inspector, serialization defaults, and validation. Without it every new
 * node type would mean touching four places, and they would drift.
 *
 * Rendering is a view concern: `design/` supplies the controls and
 * `view/nodes/FieldRenderer` maps a schema kind to one. A node that needs
 * something the schema cannot express supplies a custom body component
 * instead — the schema stays the source of truth for its *data*.
 */

export type FieldValue = string | number | boolean | null | Array<Record<string, FieldValue>>;

interface FieldSchemaBase<TValue extends FieldValue> {
  /** Key within the node's `data` record. */
  readonly key: string;
  /** Uppercase micro-label above the control. Omit for an unlabelled control. */
  readonly label?: string;
  readonly hint?: string;
  readonly defaultValue: TValue;
  /** Render on the node card. Default `true`. */
  readonly onCard?: boolean;
  /** Render in the inspector panel. Default `true`. */
  readonly inInspector?: boolean;
  /**
   * Inspector section this field renders under. Default "Configuration".
   * Groups appear in the order their first field was declared — the schema
   * stays the single place presentation is decided (ticket 38).
   */
  readonly group?: string;
  /** Collapsed by default in the inspector, inside its group. */
  readonly advanced?: boolean;
  /** Return an error string to block the value, or `null` to accept it. */
  readonly validate?: (value: TValue) => string | null;
}

export interface TextFieldSchema extends FieldSchemaBase<string> {
  readonly kind: 'text';
  readonly placeholder?: string;
  /** Static, non-editable lead-in shown inside the control, e.g. `r/`. */
  readonly prefix?: string;
  readonly suffix?: string;
  readonly maxLength?: number;
  readonly mono?: boolean;
}

export interface TextAreaFieldSchema extends FieldSchemaBase<string> {
  readonly kind: 'textarea';
  readonly placeholder?: string;
  readonly minRows?: number;
  readonly maxLength?: number;
  readonly mono?: boolean;
}

export interface SelectFieldSchema extends FieldSchemaBase<string> {
  readonly kind: 'select';
  /**
   * Static options, or a provider for options that depend on runtime state
   * (the model list depends on which providers hold credentials).
   */
  readonly options: readonly FieldOption[] | (() => readonly FieldOption[]);
}

export interface FieldOption {
  readonly value: string;
  readonly label: string;
  readonly group?: string;
  readonly disabled?: boolean;
}

export interface SliderFieldSchema extends FieldSchemaBase<number> {
  readonly kind: 'slider';
  readonly min: number;
  readonly max: number;
  readonly step?: number;
  /** Formats the readout appended to the label, e.g. `· 500`. */
  readonly format?: (value: number) => string;
}

export interface ToggleFieldSchema extends FieldSchemaBase<boolean> {
  readonly kind: 'toggle';
  readonly description?: string;
}

export interface FileFieldSchema extends FieldSchemaBase<string> {
  readonly kind: 'file';
  /** `accept` attribute for the picker. */
  readonly accept?: string;
  /** Data key the file's text content is written to. */
  readonly contentKey: string;
  readonly actionLabel?: string;
}

/** Non-editable readout of a computed or upstream value. */
export interface ReadonlyFieldSchema extends FieldSchemaBase<string> {
  readonly kind: 'readonly';
  readonly mono?: boolean;
}

/**
 * A repeatable group of fields — each row is an object with stable ids.
 *
 * Used for lists where each item needs its own identity that survives
 * reordering and renaming (e.g. router branches, where an edge references
 * a branch by id, not by name).
 */
export interface RepeatableGroupSchema extends Omit<FieldSchemaBase<FieldValue>, 'defaultValue'> {
  readonly kind: 'repeatable-group';
  readonly defaultValue?: Array<Record<string, FieldValue>>;
  /** The sub-fields for each row. */
  readonly fields: readonly FieldSchema[];
  /** Label for the "add" button, e.g. "Add branch". */
  readonly addLabel: string;
  /** Maximum number of rows. */
  readonly maxRows?: number;
}

export type FieldSchema =
  | TextFieldSchema
  | TextAreaFieldSchema
  | SelectFieldSchema
  | SliderFieldSchema
  | ToggleFieldSchema
  | FileFieldSchema
  | ReadonlyFieldSchema
  | RepeatableGroupSchema;

export type FieldKind = FieldSchema['kind'];

/** Node configuration state: a flat, JSON-safe record keyed by field. */
export type NodeData = Record<string, FieldValue>;

export function resolveOptions(schema: SelectFieldSchema): readonly FieldOption[] {
  return typeof schema.options === 'function' ? schema.options() : schema.options;
}

export function isOnCard(schema: FieldSchema): boolean {
  return schema.onCard ?? true;
}

export function isInInspector(schema: FieldSchema): boolean {
  return schema.inInspector ?? true;
}

/** Builds the initial `data` record for a node type from its schema. */
export function defaultsFrom(schemas: readonly FieldSchema[]): NodeData {
  const data: NodeData = {};
  for (const schema of schemas) {
    data[schema.key] = schema.defaultValue ?? null;
    // A file field carries two keys: the display name and the content it
    // was loaded from. Seed both so the node is never half-initialised.
    if (schema.kind === 'file') data[schema.contentKey] = '';
    // A repeatable-group field needs an empty array default if none provided.
    if (schema.kind === 'repeatable-group' && schema.defaultValue === undefined) {
      data[schema.key] = [];
    }
  }
  return data;
}

/**
 * Merges a partial patch over a data record, dropping `undefined` values.
 *
 * An explicit `undefined` in a patch means "leave this alone", not "set it
 * to nothing" — a spread would write the hole into the record and produce
 * fields that exist but hold no value.
 */
export function mergeData(base: NodeData, patch: Partial<NodeData> | undefined): NodeData {
  if (!patch) return { ...base };
  const merged: NodeData = { ...base };
  for (const [key, value] of Object.entries(patch)) {
    if (value !== undefined) merged[key] = value;
  }
  return merged;
}

/** Runs every field's validator, collecting errors by key. */
export function validateFields(
  schemas: readonly FieldSchema[],
  data: NodeData,
): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const schema of schemas) {
    const validate = schema.validate as ((value: FieldValue) => string | null) | undefined;
    if (!validate) continue;
    const value = data[schema.key] ?? schema.defaultValue ?? null;
    const error = validate(value);
    if (error) errors[schema.key] = error;
  }
  return errors;
}

/** One inspector section: its visible fields, plus the collapsed advanced set. */
export interface InspectorFieldGroup {
  readonly heading: string;
  readonly fields: FieldSchema[];
  readonly advanced: FieldSchema[];
}

/**
 * Sections for the inspector, derived from the schema alone — the node's
 * declaration decides its own presentation, so a new field lands in the
 * right place without touching the panel (ticket 38's progressive
 * disclosure: the card stays small, everything else groups and collapses).
 */
export function groupFieldsForInspector(
  fields: readonly FieldSchema[],
): InspectorFieldGroup[] {
  const groups = new Map<string, { fields: FieldSchema[]; advanced: FieldSchema[] }>();
  for (const schema of fields) {
    if (!isInInspector(schema)) continue;
    const heading = schema.group ?? 'Configuration';
    let bucket = groups.get(heading);
    if (!bucket) {
      bucket = { fields: [], advanced: [] };
      groups.set(heading, bucket);
    }
    (schema.advanced ? bucket.advanced : bucket.fields).push(schema);
  }
  return [...groups.entries()].map(([heading, bucket]) => ({ heading, ...bucket }));
}
