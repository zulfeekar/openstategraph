import { useCallback, useRef, type ChangeEvent } from 'react';
import { Replace } from 'lucide-react';
import {
  Button,
  DisplayRow,
  Field,
  Select,
  Slider,
  TextArea,
  TextInput,
  useFieldId,
  type SelectOption,
} from '@design/primitives';
import {
  resolveOptions,
  type FieldSchema,
  type FieldValue,
  type NodeData,
  type RepeatableGroupSchema,
} from '@core/model/contracts/fields';
import type { NodeId } from '@core/model/contracts/node';
import { useController } from '@app/WorkbenchContext';

interface FieldRendererProps {
  nodeId: NodeId;
  schema: FieldSchema;
  data: Readonly<NodeData>;
  /** Field-level error from workflow validation. */
  error?: string;
}

/**
 * Renders one schema-declared field as a design-system control.
 *
 * This is the payoff of declaring node configuration as data: node types
 * describe their fields once, and both the card and the inspector render
 * them from the same switch. A new field *kind* is a case here; a new
 * *field* on an existing node type needs no view code at all.
 *
 * Every control is wrapped in `data-no-drag`, which the paper's guard uses to
 * let a pointer-down reach the control instead of starting a node drag —
 * without it, dragging a slider would move the node.
 */
export function FieldRenderer({ nodeId, schema, data, error }: FieldRendererProps) {
  const controller = useController();
  const id = useFieldId('field-');

  const set = useCallback(
    (value: FieldValue) => controller.nodes.setField(nodeId, schema.key, value),
    [controller, nodeId, schema.key],
  );

  const common = {
    label: schema.label,
    ...(schema.hint ? { hint: schema.hint } : {}),
    ...(error ? { error } : {}),
    htmlFor: id,
  };

  switch (schema.kind) {
    case 'text': {
      const value = asString(data[schema.key]);
      return (
        <Field {...common}>
          <div data-no-drag>
            <TextInput
              id={id}
              value={value}
              placeholder={schema.placeholder}
              maxLength={schema.maxLength}
              mono={schema.mono}
              invalid={Boolean(error)}
              prefix={schema.prefix}
              suffix={schema.suffix}
              onChange={(event) => set(event.target.value)}
            />
          </div>
        </Field>
      );
    }

    case 'textarea': {
      const value = asString(data[schema.key]);
      return (
        <Field {...common}>
          <div data-no-drag>
            <TextArea
              id={id}
              value={value}
              placeholder={schema.placeholder}
              minRows={schema.minRows}
              maxLength={schema.maxLength}
              mono={schema.mono}
              invalid={Boolean(error)}
              onChange={(event) => set(event.target.value)}
            />
          </div>
        </Field>
      );
    }

    case 'select': {
      const options = resolveOptions(schema).map<SelectOption>((option) => ({
        value: option.value,
        label: option.label,
        ...(option.group ? { group: option.group } : {}),
        ...(option.disabled ? { disabled: true } : {}),
      }));
      const value = asString(data[schema.key]) || schema.defaultValue;
      return (
        <Field {...common}>
          <div data-no-drag>
            <Select id={id} options={options} value={value} onValueChange={set} />
          </div>
        </Field>
      );
    }

    case 'slider': {
      const value = asNumber(data[schema.key], schema.defaultValue);
      return (
        <Field {...common} labelValue={schema.format ? schema.format(value) : `· ${value}`}>
          <div data-no-drag>
            <Slider
              id={id}
              value={value}
              min={schema.min}
              max={schema.max}
              step={schema.step ?? 1}
              // Live updates keep the readout responsive; only the commit
              // records an undo entry, so a drag is one step.
              onValueChange={(next) => set(next)}
              onValueCommit={(next) => set(next)}
            />
          </div>
        </Field>
      );
    }

    case 'toggle': {
      const value = asBoolean(data[schema.key], schema.defaultValue);
      return (
        <Field {...common}>
          <div data-no-drag>
            <Button active={value} onClick={() => set(!value)}>
              {value ? 'On' : 'Off'}
            </Button>
          </div>
        </Field>
      );
    }

    case 'file':
      return <FileField nodeId={nodeId} schema={schema} data={data} labelId={id} />;

    case 'readonly': {
      const value = asString(data[schema.key]);
      return (
        <Field {...common}>
          <DisplayRow value={value || '—'} />
        </Field>
      );
    }

    case 'repeatable-group': {
      const value = data[schema.key];
      const rows = Array.isArray(value) ? (value as Array<Record<string, FieldValue>>) : [];
      return <RepeatableGroupField nodeId={nodeId} schema={schema} rows={rows} {...common} />;
    }
  }
}

/**
 * File picker.
 *
 * Reads the file's text immediately and writes name and content in one
 * command, so undo restores both together — a half-loaded file (name set,
 * content stale) would silently run the wrong instruction.
 */
function FileField({
  nodeId,
  schema,
  data,
  labelId,
}: {
  nodeId: NodeId;
  schema: Extract<FieldSchema, { kind: 'file' }>;
  data: Readonly<NodeData>;
  labelId: string;
}) {
  const controller = useController();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const filename = asString(data[schema.key]);

  const onPick = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const text = await file.text();
    controller.nodes.setFields(
      nodeId,
      { [schema.key]: file.name, [schema.contentKey]: text },
      `Load ${file.name}`,
    );
    // Clear the input so re-picking the same file fires a change event.
    event.target.value = '';
  };

  return (
    <Field label={schema.label} htmlFor={labelId}>
      <div data-no-drag>
        <DisplayRow
          value={filename || 'No file selected'}
          action={
            <Button
              size="sm"
              onClick={() => inputRef.current?.click()}
              icon={filename ? undefined : <Replace size={12} strokeWidth={1.75} />}
            >
              {schema.actionLabel ?? (filename ? 'Replace' : 'Choose')}
            </Button>
          }
        />
        <input
          ref={inputRef}
          id={labelId}
          type="file"
          accept={schema.accept}
          className="sr-only"
          onChange={(event) => void onPick(event)}
        />
      </div>
    </Field>
  );
}

const asString = (value: FieldValue | undefined): string =>
  typeof value === 'string' ? value : '';

const asNumber = (value: FieldValue | undefined, fallback: number): number =>
  typeof value === 'number' && Number.isFinite(value) ? value : fallback;

const asBoolean = (value: FieldValue | undefined, fallback: boolean): boolean =>
  typeof value === 'boolean' ? value : fallback;

/**
 * Repeatable group field — a list of rows, each with stable ids.
 *
 * Used for router branches: each row has {id, name} where id is generated
 * once and survives renames, so edges referencing `branch:${id}` don't
 * break when the user renames a branch.
 */
function RepeatableGroupField({
  nodeId,
  schema,
  rows,
  ...common
}: {
  nodeId: NodeId;
  schema: RepeatableGroupSchema;
  rows: Array<Record<string, FieldValue>>;
  label?: string;
  hint?: string;
  error?: string;
  htmlFor: string;
}) {
  const controller = useController();

  const addRow = () => {
    const newRow: Record<string, FieldValue> = {};
    for (const field of schema.fields) {
      newRow[field.key] = field.defaultValue ?? null;
    }
    // Generate a stable id for new rows.
    if (!newRow.id) {
      newRow.id = `r${Date.now()}`;
    }
    const nextRows = [...rows, newRow];
    controller.nodes.setField(nodeId, schema.key, nextRows);
  };

  const removeRow = (index: number) => {
    const nextRows = rows.filter((_, i) => i !== index);
    controller.nodes.setField(nodeId, schema.key, nextRows);
  };

  const updateRow = (index: number, key: string, value: FieldValue) => {
    const nextRows = rows.map((row, i) => (i === index ? { ...row, [key]: value } : row));
    controller.nodes.setField(nodeId, schema.key, nextRows);
  };

  const canAdd = schema.maxRows === undefined || rows.length < schema.maxRows;

  return (
    <Field {...common}>
      <div data-no-drag>
        <div className="repeatable-group">
          {rows.map((row, index) => (
            <div key={(row.id as string) ?? index} className="repeatable-group__row">
              {schema.fields.map((field) => (
                <div key={field.key} className="repeatable-group__field">
                  {field.kind === 'text' && (
                    <TextInput
                      value={asString(row[field.key])}
                      placeholder={field.placeholder}
                      onChange={(e) => updateRow(index, field.key, e.target.value)}
                      mono={field.mono}
                    />
                  )}
                  {field.kind === 'textarea' && (
                    <TextArea
                      value={asString(row[field.key])}
                      placeholder={field.placeholder}
                      minRows={field.minRows}
                      onChange={(e) => updateRow(index, field.key, e.target.value)}
                      mono={field.mono}
                    />
                  )}
                  {field.kind === 'select' && (
                    <Select
                      options={resolveOptions(field).map((opt) => ({
                        value: opt.value,
                        label: opt.label,
                        group: opt.group,
                        disabled: opt.disabled,
                      }))}
                      value={asString(row[field.key]) || field.defaultValue}
                      onValueChange={(val) => updateRow(index, field.key, val)}
                    />
                  )}
                </div>
              ))}
              <button
                type="button"
                onClick={() => removeRow(index)}
                className="repeatable-group__remove"
                aria-label="Remove row"
              >
                ×
              </button>
            </div>
          ))}
          {canAdd && (
            <button type="button" onClick={addRow} className="repeatable-group__add">
              + {schema.addLabel}
            </button>
          )}
        </div>
      </div>
    </Field>
  );
}
