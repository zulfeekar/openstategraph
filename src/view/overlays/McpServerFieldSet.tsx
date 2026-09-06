import { Button, DisplayRow, Field, Select, TextInput } from '@design/primitives';
import {
  nextRowId,
  resolveOptions,
  type FieldSchema,
  type FieldValue,
  type RepeatableGroupSchema,
} from '@core/model/contracts/fields';

/**
 * The `tool.mcp` card's own field set, rendered in the app-level panel.
 *
 * This component holds **no knowledge of MCP at all** — no transport list, no
 * auth types, no hint text, no validator. Every one of those arrives as a
 * `FieldSchema` from `mcpServerFields()`, the factory ticket 02 extracted
 * (`1688aca`) for exactly this reuse. Adding a fourth auth type is a change in
 * that one module and this panel renders it without being touched, which is
 * the whole point of the map's *two scopes, one field-set* decision.
 *
 * **Why it is not `FieldRenderer`**, which renders the same schemas on the
 * canvas: that component writes through `controller.nodes.setField`, i.e.
 * through a command, onto a node, in an undo history. A server definition is
 * none of those things — it is a plain record that leaves through an HTTP
 * route. Sharing the *knowledge* (the schemas) and not the *binding* (the
 * controller) is the boundary CLAUDE.md's DRY rule draws: duplication of
 * knowledge is the defect, duplication of shape is often fine.
 */
export function McpServerFieldSet({
  fields,
  values,
  onChange,
}: {
  readonly fields: readonly FieldSchema[];
  readonly values: Readonly<Record<string, FieldValue>>;
  readonly onChange: (key: string, value: FieldValue) => void;
}) {
  return (
    <>
      {fields.map((schema) => (
        <SchemaField key={schema.key} schema={schema} values={values} onChange={onChange} />
      ))}
    </>
  );
}

function SchemaField({
  schema,
  values,
  onChange,
}: {
  schema: FieldSchema;
  values: Readonly<Record<string, FieldValue>>;
  onChange: (key: string, value: FieldValue) => void;
}) {
  const raw = values[schema.key];
  const error = errorFor(schema, raw);
  const common = {
    label: schema.label ?? schema.key,
    ...(schema.hint ? { hint: schema.hint } : {}),
    ...(error ? { error } : {}),
  };

  switch (schema.kind) {
    case 'text':
      return (
        <Field {...common}>
          <TextInput
            value={asString(raw)}
            placeholder={schema.placeholder}
            mono={schema.mono}
            invalid={Boolean(error)}
            autoComplete="off"
            onChange={(event) => onChange(schema.key, event.target.value)}
          />
        </Field>
      );

    case 'select':
      return (
        <Field {...common}>
          <Select
            options={resolveOptions(schema, values).map((option) => ({
              value: option.value,
              label: option.label,
            }))}
            value={asString(raw) || schema.defaultValue}
            onValueChange={(value) => onChange(schema.key, value)}
          />
        </Field>
      );

    case 'readonly':
      // The locked note: machinery shown, never a pre-filled editable box —
      // and read from the schema first, because since ticket 52 the prose is
      // deliberately not in anybody's `data`.
      return (
        <Field {...common}>
          <DisplayRow value={String(schema.defaultValue ?? '') || asString(raw)} />
        </Field>
      );

    case 'repeatable-group':
      return <RowsField schema={schema} rows={asRows(raw)} onChange={onChange} {...common} />;

    default:
      // Honest refusal beats silence: a kind this panel cannot draw would
      // otherwise be a field that silently does not exist, and a developer
      // would conclude they had configured something.
      return (
        <Field {...common}>
          <DisplayRow value={`This field (${schema.kind}) can only be set on the card.`} />
        </Field>
      );
  }
}

/** The tool filter: rows of one name. Empty means every tool, now and later. */
function RowsField({
  schema,
  rows,
  onChange,
  ...common
}: {
  schema: RepeatableGroupSchema;
  rows: Array<Record<string, FieldValue>>;
  onChange: (key: string, value: FieldValue) => void;
  label?: string;
  hint?: string;
  error?: string;
}) {
  const field = schema.fields[0];
  const write = (next: Array<Record<string, FieldValue>>) => onChange(schema.key, next);

  return (
    <Field {...common}>
      <div className="repeatable-group">
        {rows.map((row, index) => (
          <div key={(row.id as string) ?? index} className="repeatable-group__row">
            <div className="repeatable-group__field">
              <TextInput
                mono
                value={asString(row[field?.key ?? 'name'])}
                placeholder={field?.kind === 'text' ? field.placeholder : undefined}
                onChange={(event) =>
                  write(
                    rows.map((current, at) =>
                      at === index
                        ? { ...current, [field?.key ?? 'name']: event.target.value }
                        : current,
                    ),
                  )
                }
              />
            </div>
            <button
              type="button"
              className="repeatable-group__remove"
              aria-label="Remove tool"
              onClick={() => write(rows.filter((_, at) => at !== index))}
            >
              ×
            </button>
          </div>
        ))}
        <Button size="sm" onClick={() => write([...rows, { id: nextRowId(), name: '' }])}>
          {schema.addLabel ?? 'Add'}
        </Button>
      </div>
    </Field>
  );
}

/**
 * The schema's own validator, run where the schema declared it.
 *
 * For the credential field this is the check that refuses a pasted key —
 * shape *and* prefix, from ticket 02's list. Running the schema's function
 * rather than restating the rule is what stops this panel and the card
 * disagreeing about what a variable name is.
 */
function errorFor(schema: FieldSchema, raw: FieldValue | undefined): string | undefined {
  switch (schema.kind) {
    case 'text':
    case 'textarea':
    case 'select':
    case 'combobox':
    case 'file':
    case 'readonly':
      return schema.validate?.(asString(raw)) ?? undefined;
    default:
      return undefined;
  }
}

const asString = (value: FieldValue | undefined): string =>
  typeof value === 'string' ? value : '';

const asRows = (value: FieldValue | undefined): Array<Record<string, FieldValue>> =>
  Array.isArray(value) ? (value as Array<Record<string, FieldValue>>) : [];
