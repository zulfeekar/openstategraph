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

/**
 * **The paragraph kind.** A field whose content is prose — rules, criteria, a
 * refusal message, a note — declares `textarea` and inherits a box that grows
 * with what is written in it.
 *
 * Deliberately *not* a second `paragraph` kind (ticket 26, which offered the
 * choice). The contract already had this one, seventeen fields already used
 * it, and a `paragraph` that rendered as a growing textarea beside a
 * `textarea` that rendered as a growing textarea would be two names for one
 * piece of knowledge — the duplication the DRY rule names as the defect. What
 * was missing was not a kind. It was the **ceiling**: growth stopped at a
 * hard-coded `max-height: 180px` in the card's stylesheet, a number no schema
 * could see, state or change, so a system prompt and a two-word note were
 * given the same nine lines and every longer field scrolled inside a slot.
 *
 * So the two bounds are declared here, in the one place a node describes its
 * own configuration, and the stylesheet reads them rather than deciding them.
 */
export interface TextAreaFieldSchema extends FieldSchemaBase<string> {
  readonly kind: 'textarea';
  readonly placeholder?: string;
  /**
   * Lines reserved before there is anything to show. The floor, not the size:
   * an empty box this tall says "a paragraph belongs here". Default 2, which
   * suits a one-sentence field; anything that is genuinely a paragraph should
   * say 3 or more.
   */
  readonly minRows?: number;
  /**
   * Lines the box may grow to before it starts scrolling. The ceiling exists
   * because a card is a card — a node that grew to hold a 200-line prompt
   * would swallow the canvas — but it is per-field, because how much room a
   * paragraph deserves is a property of the paragraph. Default 12.
   */
  readonly maxRows?: number;
  readonly maxLength?: number;
  readonly mono?: boolean;
}

export interface SelectFieldSchema extends FieldSchemaBase<string> {
  readonly kind: 'select';
  /**
   * Static options, or a provider for options that depend on runtime state
   * (the model list depends on which providers hold credentials) **or on the
   * node's own data** (the reasoning tiers depend on which model is chosen).
   *
   * Taking `data` mirrors `INodeDefinition.ports`, which is already a function
   * of the node's data for exactly this reason, and it is what lets a select
   * obey the house rule that a control reaching nothing is worse than no
   * control: the alternative is a live-looking listbox whose value the chosen
   * model will discard.
   */
  readonly options: readonly FieldOption[] | ((data: Readonly<NodeData>) => readonly FieldOption[]);
}

/**
 * A text box with a list of suggestions — pick what exists, type what does not.
 *
 * **Decided rather than defaulted** (production-ready ticket 05, which asked
 * for exactly that). A listbox would make a typo unreachable, and would also
 * make it impossible to mount a package you have not created yet — and
 * drafting in that order is a real way to work: sketch the parent, then go and
 * build the child. A combobox keeps the typo off the *normal* path, which is
 * what the ticket asked for, without outlawing the order.
 *
 * The value is a plain string, unchanged: `data.workflow` is a serialised
 * contract, and swapping the control must not alter what is written.
 */
export interface ComboboxFieldSchema extends FieldSchemaBase<string> {
  readonly kind: 'combobox';
  /** Suggestions, resolved the same way a `select`'s options are. */
  readonly options: readonly FieldOption[] | ((data: Readonly<NodeData>) => readonly FieldOption[]);
  readonly placeholder?: string;
  readonly mono?: boolean;
  /** Shown under the box when there is nothing to suggest. */
  readonly emptyHint?: string;
  /**
   * Where the suggestions come from, so the control re-renders when they move.
   *
   * `options` is synchronous because it is called during a render, while every
   * interesting list — the workflow catalogue, the MCP registry — arrives over
   * HTTP. Something has to tell React the answer changed, and the field is the
   * only thing that knows *which* store answers its question. The renderer
   * subscribed to one hardcoded catalogue before mcp-connect ticket 07, which
   * meant a second live picker could not be added without editing the
   * renderer — the closed engine this project's O rule forbids.
   *
   * Returns an unsubscribe. Omit it for a list that cannot move.
   */
  readonly subscribe?: (notify: () => void) => () => void;
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
  /** An on-demand check of one row against the world. See `RowProbe`. */
  readonly rowProbe?: RowProbe;
}

/**
 * What a row's on-demand check answers with.
 *
 * `ok` rather than a tone, because a tone is the view's word: green means one
 * thing only and every failure shares the other colour, so the renderer needs
 * a boolean and the schema has no business naming a design token. The `label`
 * is what the badge says and the `detail` is the sentence under the row —
 * short and long, because "unreachable" and *why* answer different questions.
 */
export interface RowVerdict {
  readonly ok: boolean;
  /** Two or three words, e.g. `live`, `auth required`. */
  readonly label: string;
  /** The full sentence, from whoever actually knows — usually the runtime. */
  readonly detail?: string;
}

/**
 * A per-row check, run when a developer asks for it.
 *
 * Declared on the schema for the same reason `validate` and `options` are: a
 * field group states what it needs and the renderer stays a renderer. The
 * alternative — the row renderer knowing that a `servers` group means MCP and
 * which endpoint validates one — is the "extend by editing the engine" the
 * registry rules forbid.
 *
 * **On demand, never on render.** A probe opens a network connection, and a
 * group that checked every row on every keystroke would hammer somebody's
 * server from a text box. The verdict is a fact with a timestamp; the button
 * is what says when it was taken.
 */
export interface RowProbe {
  /** Button text, e.g. `Check`. */
  readonly label: string;
  readonly run: (row: Readonly<Record<string, FieldValue>>) => Promise<RowVerdict>;
}

export type FieldSchema =
  | TextFieldSchema
  | TextAreaFieldSchema
  | SelectFieldSchema
  | ComboboxFieldSchema
  | SliderFieldSchema
  | ToggleFieldSchema
  | FileFieldSchema
  | ReadonlyFieldSchema
  | RepeatableGroupSchema;

/** Node configuration state: a flat, JSON-safe record keyed by field. */
export type NodeData = Record<string, FieldValue>;

/**
 * A field's options, whether they are a literal list or a function of the
 * node's own data.
 *
 * Takes the *option-carrying* shape rather than `SelectFieldSchema`
 * specifically: a combobox resolves its suggestions the same way a select
 * resolves its choices, and narrowing to one kind would have meant a second
 * copy of this one line for the other.
 */
export function resolveOptions(
  schema: Pick<SelectFieldSchema, 'options'>,
  data: Readonly<NodeData> = {},
): readonly FieldOption[] {
  return typeof schema.options === 'function' ? schema.options(data) : schema.options;
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
export function groupFieldsForInspector(fields: readonly FieldSchema[]): InspectorFieldGroup[] {
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
